"""
QQ Zone initialization and lifecycle management.
Extracted from main.py to reduce its responsibilities.
"""

import asyncio

from astrbot.api import logger
from astrbot.api.star import StarTools
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_platform_adapter import (
    AiocqhttpAdapter,
)

try:
    from .llm_action import LLMAction
    from .operate import PostOperator
    from .qzone_api import Qzone
    from .scheduler import AutoPublish  # noqa: F401

    QZONE_AVAILABLE = True
except ImportError as e:
    QZONE_AVAILABLE = False
    logger.warning(f"QQ空间模块未完全加载: {e}")


async def initialize_qzone(state, context) -> bool:
    """Initialize QQ zone subsystem (Qzone client, LLMAction, PostOperator, AutoPublish).

    Args:
        state: SharedState instance (mutated in-place with qzone/llm/operator etc.)
        context: AstrBot Context for platform lookup.

    Returns:
        True if initialization succeeded, False otherwise.
    """
    if state._qzone_initialized:
        logger.debug("[QQ空间] 已初始化，跳过重复调用")
        return False
    state._qzone_initialized = True

    logger.info("[QQ空间] 开始初始化")

    if not QZONE_AVAILABLE:
        logger.warning("[QQ空间] QZONE_AVAILABLE=False, 模块不可用")
        return False

    # 1. Find aiocqhttp client
    logger.info("[QQ空间] 查找 aiocqhttp 客户端...")
    client = None
    for inst in context.platform_manager.platform_insts:
        if isinstance(inst, AiocqhttpAdapter):
            if client := inst.get_client():
                logger.info(f"[QQ空间] 找到 aiocqhttp 客户端: {type(inst).__name__}")
                break
    if not client:
        logger.warning("[QQ空间] 未找到 aiocqhttp 客户端，初始化终止")
        return False

    # 2. Wait for WebSocket if needed (caller should handle this before calling)
    logger.info("[QQ空间] 创建Qzone对象...")
    state.qzone = Qzone(client)
    logger.info("[QQ空间] Qzone对象创建完成")

    # 3. Login
    logger.info("[QQ空间] 登录QQ空间...")
    await state.qzone.ready()
    if not state.qzone.ctx:
        logger.warning("[QQ空间] 登录失败，ctx未初始化，部分功能可能不可用")
    else:
        logger.info(f"[QQ空间] 登录成功，uin={state.qzone.ctx.uin}")

    # 4. Create LLMAction
    logger.info("[QQ空间] 创建LLMAction对象...")
    state.llm = LLMAction(context, state.config, client)
    state.llm.experience_bank = state.experience_bank
    state.llm.personality_evolution = state.personality_evolution
    logger.info("[QQ空间] LLMAction对象创建完成")

    # 5. Create PostOperator
    logger.info("[QQ空间] 创建PostOperator...")
    from .post import PostDB

    db_path = StarTools.get_data_dir("astrbot_plugin_realistic_persona") / "posts.db"
    state.post_db = PostDB(db_path)
    await state.post_db.initialize()
    logger.info(f"[QQ空间] 数据库已初始化: {db_path}")

    state.operator = PostOperator(
        context,
        state.config,
        state.qzone,
        state.post_db,
        state.llm,
        state.style,
        state.local_data_manager,
    )
    logger.info("[QQ空间] PostOperator创建完成")

    # 6. Start AutoPublish or standalone comment checker
    _setup_publish_or_comment_check(state, context)

    logger.info("[QQ空间] 初始化完成！")
    logger.info(
        f"[QQ空间] 组件状态: qzone={'OK' if state.qzone is not None else 'MISSING'}, "
        f"llm={'OK' if state.llm is not None else 'MISSING'}, "
        f"operator={'OK' if state.operator is not None else 'MISSING'}"
    )

    # 7. Bind llm_action to async thinking scheduler
    if state.enable_async_thinking and state.async_thinking_scheduler and state.llm:
        state.async_thinking_scheduler.llm_action = state.llm
        logger.debug("[QQ空间] 已将 llm_action 绑定到异步思考调度器")

    return True


def _setup_publish_or_comment_check(state, context):
    """Set up AutoPublish scheduler or standalone comment checker."""
    publish_times = state.config.get("publish_times_per_day", 0)
    insomnia_prob = state.config.get("insomnia_probability", 0)

    if state.config.get("enable_qzone") and (publish_times > 0 or insomnia_prob > 0):
        logger.info("[QQ空间] 创建AutoPublish...")
        state.auto_publish = AutoPublish(context, state.config, state.operator)
        # start() is async but AutoPublish handles its own scheduling
        # We fire-and-forget here; errors are logged internally
        import asyncio

        asyncio.create_task(state.auto_publish.start())
        logger.info("[QQ空间] AutoPublish创建完成")
    else:
        logger.info(
            "[QQ空间] 未启用自动发说说（enable_qzone=False 或 publish_times_per_day=0 且 insomnia_probability=0）"
        )
        if state.config.get("enable_qzone") and state.config.get(
            "enable_auto_reply_comments", True
        ):
            _start_standalone_comment_check(state, context)


def _start_standalone_comment_check(state, context):
    """Start a standalone comment check scheduler (without AutoPublish)."""
    try:
        import zoneinfo

        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.interval import IntervalTrigger

        tz = context.get_config().get("timezone")
        timezone = zoneinfo.ZoneInfo(tz) if tz else zoneinfo.ZoneInfo("Asia/Shanghai")

        state._comment_check_scheduler = AsyncIOScheduler(timezone=timezone)
        interval_minutes = state.config.get("qzone_comment_check_interval_minutes", 60)
        state._comment_check_scheduler.add_job(
            func=_standalone_check_and_reply_comments,
            trigger=IntervalTrigger(minutes=interval_minutes, timezone=timezone),
            kwargs={"state": state},
            name="standalone_comment_checker",
            max_instances=1,
        )
        state._comment_check_scheduler.start()
        logger.info(f"[QQ空间][独立评论检查] 已启动，每{interval_minutes}分钟检查一次")
    except Exception as e:
        logger.error(f"[QQ空间][独立评论检查] 启动失败: {e}")


async def _standalone_check_and_reply_comments(state):
    """Check and reply to QQ space comments (standalone, without AutoPublish)."""
    try:
        if state.operator is None:
            logger.debug("[独立评论检查] operator 未初始化，跳过")
            return
        if state.operator.qzone is None:
            logger.debug("[独立评论检查] operator.qzone 未初始化，跳过")
            return
        if state.operator.qzone.ctx is None:
            logger.debug("[独立评论检查] operator.qzone.ctx 未初始化，跳过")
            return
        logger.debug("[独立评论检查] 开始检查新评论并回复")
        await state.operator.auto_reply_to_comments()
        logger.debug("[独立评论检查] 评论检查和回复完成")
    except Exception as e:
        logger.error(f"[独立评论检查] 检查和回复评论失败: {e}")


async def wait_for_qzone_ws(state, context, timeout: int = 10):
    """Wait for aiocqhttp WebSocket connection before initializing Qzone."""
    client = None
    for inst in context.platform_manager.platform_insts:
        if isinstance(inst, AiocqhttpAdapter):
            if client := inst.get_client():
                break

    if not client:
        logger.warning("[QQ空间] 未找到 aiocqhttp 客户端")
        return

    ws_connected = asyncio.Event()

    @client.on_websocket_connection
    def _(_):
        ws_connected.set()

    try:
        await asyncio.wait_for(ws_connected.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("等待 aiocqhttp WebSocket 连接超时")
