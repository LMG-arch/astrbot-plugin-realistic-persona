"""
拟人化角色行为系统插件 (Realistic Persona Plugin)
整合了情绪感知、生活模拟、QQ空间日记、AI配图等功能

版本: v1.21.0
作者: LMG-arch
最后更新: 2025-05-13
符合AstrBot插件开发完全指南规范
"""

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import BaseMessageComponent, Image, Plain
from astrbot.api.provider import LLMResponse, ProviderRequest
from astrbot.api.star import Context, Star, StarTools, register
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_platform_adapter import (
    AiocqhttpAdapter,
)

try:
    import pillowmd

    PILLOWMD_AVAILABLE = True
except ImportError:
    PILLOWMD_AVAILABLE = False
    logger.warning("pillowmd 未安装，部分渲染功能将不可用")

try:
    from .core.llm_action import LLMAction
    from .core.operate import PostOperator
    from .core.qzone_api import Qzone
    from .core.scheduler import AutoPublish  # noqa: F401
    from .core.utils import get_image_urls  # noqa: F401

    QZONE_AVAILABLE = True
except ImportError as e:
    QZONE_AVAILABLE = False
    logger.warning(f"QQ空间模块未完全加载: {e}")

from .core.utils import stable_hash
from .managers import (
    EmotionManager,
    ExperienceManager,
    ImageManager,
    LifeManager,
    ProactiveManagerWrapper,
    ProfileManager,
    SharedState,
    ThinkingManager,
)


class ThinkingLLM:
    """轻量级LLM助手，用于异步思考和活动生成，不依赖QQ平台"""

    def __init__(self, context, provider_id: str = "", persona_profile: str = ""):
        self.context = context
        self.provider_id = provider_id
        self.persona_profile = persona_profile

    def _get_provider(self):
        provider = None
        if self.provider_id:
            provider = self.context.get_provider_by_id(self.provider_id)
        if not provider:
            provider = self.context.get_using_provider()
        return provider

    def _build_system_prompt(self, mode: str = "thought") -> str:
        persona = self.persona_profile.strip()
        persona_clause = f"你就是这个人：{persona}\n" if persona else ""
        if mode == "thought":
            return (
                f"{persona_clause}"
                "请完全以角色的身份进行内心独白。要求：\n"
                "1. 真实自然，像真人内心独白，有具体的情绪和感受\n"
                "2. 长度15-50字\n"
                "3. 必须结合给定的真实情境（日程、天气、最近聊天、经历）来思考\n"
                "4. 不要泛泛的感叹（如'又度过充实的一天'），要对具体事情有感受\n"
                "5. 符合你的人设特点，有个人情感色彩\n"
                "6. 直接返回思考内容，不要添加解释或引号"
            )
        else:
            return (
                f"{persona_clause}"
                "请完全以角色的身份描述此刻正在做的一件日常小事。要求：\n"
                "1. 真实自然，贴近生活，有具体动作和细节\n"
                "2. 长度10-30字\n"
                "3. 结合给定的日程、天气、时间段来描述\n"
                "4. 不要重复之前做过的事\n"
                "5. 直接返回活动内容，不要添加解释或引号"
            )

    async def generate_thought(self, prompt: str) -> str | None:
        provider = self._get_provider()
        if not provider:
            logger.warning("[思考LLM] 未配置LLM提供商，无法生成思考")
            return None
        try:
            resp = await provider.text_chat(
                system_prompt=self._build_system_prompt("thought"),
                prompt=prompt,
            )
            text = (resp.completion_text or "").strip()
            if not text:
                logger.warning("[思考LLM] LLM返回空内容")
                return None
            text = text.split("\n")[0].strip()
            if text.startswith('"') and text.endswith('"'):
                text = text[1:-1]
            if text.startswith("「") and text.endswith("」"):
                text = text[1:-1]
            return text if text else None
        except Exception as e:
            logger.error(f"[思考LLM] 生成思考失败: {e}")
            return None

    async def generate_activity(self, prompt: str) -> str | None:
        provider = self._get_provider()
        if not provider:
            logger.warning("[思考LLM] 未配置LLM提供商，无法生成活动")
            return None
        try:
            resp = await provider.text_chat(
                system_prompt=self._build_system_prompt("activity"),
                prompt=prompt,
            )
            text = (resp.completion_text or "").strip()
            if not text:
                logger.warning("[思考LLM] LLM返回空内容")
                return None
            text = text.split("\n")[0].strip()
            if text.startswith('"') and text.endswith('"'):
                text = text[1:-1]
            return text if text else None
        except Exception as e:
            logger.error(f"[思考LLM] 生成活动失败: {e}")
            return None


@register(
    "astrbot_plugin_realistic_persona",
    "LMG-arch",
    "拟人化角色行为系统：情绪感知、生活模拟、QQ空间日记、AI配图、异步思考、人格演化、人生故事引擎等",
    "1.21.0",
    "https://github.com/LMG-arch/astrbot-plugin-realistic-persona.git",
)
class Main(Star):
    """拟人化角色行为系统主类 - 委托给各Manager实现"""

    DB_VERSION = 4

    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        if config is None:
            config = {}

        self.state = SharedState(context, config)
        self.state.initialize_sub_modules()

        self.emotion_manager = EmotionManager(self.state)
        self.life_manager = LifeManager(self.state)
        self.image_manager = ImageManager(self.state)
        self.proactive_mgr = ProactiveManagerWrapper(self.state)
        self.profile_manager = ProfileManager(self.state)
        self.thinking_manager = ThinkingManager(self.state)
        self.experience_manager = ExperienceManager(self.state)

        self._register_event_handlers()

        if self.state.enable_qzone and QZONE_AVAILABLE:
            self._init_qzone_settings(config)

        if not self.state.api_key:
            logger.warning("API密钥未配置，部分功能将不可用")

    def _init_qzone_settings(self, config):
        configured_dir = config.get("pillowmd_style_dir")
        if configured_dir:
            self.state.pillowmd_style_dir = Path(configured_dir)
        else:
            plugin_src_dir = Path(__file__).parent / "default_style"
            data_dir = (
                StarTools.get_data_dir("astrbot_plugin_realistic_persona")
                / "default_style"
            )
            if plugin_src_dir.exists():
                self.state.pillowmd_style_dir = plugin_src_dir
            elif data_dir.exists():
                self.state.pillowmd_style_dir = data_dir
            else:
                self.state.pillowmd_style_dir = plugin_src_dir
                logger.warning(f"pillowmd样式目录不存在: {plugin_src_dir}")

        self.state.cache = (
            StarTools.get_data_dir("astrbot_plugin_realistic_persona") / "cache"
        )
        self.state.cache.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _patch_toolset_openai_schema():
        from astrbot.core.agent.tool import ToolSet

        logger.warning(
            "[MonkeyPatch] 正在替换 ToolSet.openai_schema 以修复 description=None 导致的400错误。"
            "此补丁在AstrBot核心更新后可能失效，请关注插件更新。"
        )

        _original = ToolSet.openai_schema

        def _fixed_openai_schema(self, omit_empty_parameter_field=False):
            result = []
            for tool in self.tools:
                func_def = {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description or tool.name,
                    },
                }
                if tool.parameters is not None:
                    if (
                        tool.parameters and tool.parameters.get("properties")
                    ) or not omit_empty_parameter_field:
                        func_def["function"]["parameters"] = tool.parameters
                result.append(func_def)
            return result

        ToolSet.openai_schema = _fixed_openai_schema
        logger.info("[补丁] 已修复 ToolSet.openai_schema (description=None 400错误)")

    async def initialize(self):
        try:
            logger.info("拟人化角色行为系统插件正在加载...")

            try:
                self._patch_toolset_openai_schema()
            except Exception as e:
                logger.warning(f"[补丁] ToolSet补丁应用失败: {e}")

            try:
                now = datetime.now()
                today_str = now.strftime("%Y-%m-%d")
                cached_schedule = self.state.local_data_manager.get_schedule_data(
                    today_str
                )
                if cached_schedule:
                    self.state.today_schedule_display = (
                        f"[当前日程 - {today_str}]\n\n{cached_schedule}"
                    )
                    logger.info("已加载当天日程到配置显示")
            except Exception as e:
                logger.debug(f"加载日程显示失败: {e}")

            try:
                story_dir = (
                    StarTools.get_data_dir("astrbot_plugin_realistic_persona")
                    / "life_story"
                )
                state_file = story_dir / "engine_state.json"
                life_story_file = story_dir / "life_story.json"

                if state_file.exists():
                    with open(state_file, encoding="utf-8") as f:
                        state = json.load(f)
                    ch_num = state.get("current_chapter", 0)
                    update_count = state.get("update_count", 0)
                    last_ts = state.get("last_update_time", 0)
                    last_str = (
                        datetime.fromtimestamp(last_ts).strftime("%Y-%m-%d %H:%M")
                        if last_ts > 0
                        else "未更新"
                    )

                    chapter_count = 0
                    if life_story_file.exists():
                        with open(life_story_file, encoding="utf-8") as f:
                            story = json.load(f)
                        chapter_count = len(story.get("timeline", []))

                    self.state.config["life_story_display"] = (
                        f"📊 引擎状态 | 第{ch_num}章 | 更新{update_count}次 | 上次: {last_str}\n"
                        f"📜 共记录 {chapter_count} 章人生经历\n\n"
                        f"💡 使用 /life_story 命令查看完整人生故事预览"
                    )
                    logger.info("已加载人生故事摘要到配置显示")
                else:
                    self.state.config["life_story_display"] = (
                        "（人生故事尚未生成，请等待系统自动生成）"
                    )
            except Exception as e:
                logger.debug(f"加载人生故事显示失败: {e}")

            if self.state.enable_async_thinking and self.state.async_thinking_scheduler:
                try:
                    # Bind runtime callbacks before starting the scheduler
                    self.state.async_thinking_scheduler.context_provider = (
                        self.life_manager.get_thinking_context
                    )
                    if (
                        self.state.enable_profile_update_from_thinking
                        and self.profile_manager
                    ):
                        self.state.async_thinking_scheduler.on_thought_generated = (
                            self.profile_manager.on_thought_for_profile_update
                        )
                    self.state.async_thinking_scheduler.start()
                    logger.info("异步思考循环已启动")
                except Exception as e:
                    logger.error(f"启动异步思考循环失败: {e}")

            if self.state.enable_proactive_messages:
                try:
                    task = asyncio.create_task(
                        self.state.proactive_manager.start_scheduler(
                            self.proactive_mgr.send_proactive_message
                        )
                    )
                    self.state._background_tasks.add(task)
                    task.add_done_callback(self.state._background_tasks.discard)
                    logger.info(
                        f"主动消息功能已启动，空闲延迟: {self.state.idle_greeting_delay}秒"
                    )
                except Exception as e:
                    logger.error(f"启动主动消息调度器失败: {e}")

            if (
                self.state.enable_proactive_messages
                and self.state.enable_proactive_sharing
            ):
                try:
                    import zoneinfo

                    from apscheduler.schedulers.asyncio import AsyncIOScheduler
                    from apscheduler.triggers.interval import IntervalTrigger

                    tz = self.context.get_config().get("timezone")
                    share_timezone = (
                        zoneinfo.ZoneInfo(tz)
                        if tz
                        else zoneinfo.ZoneInfo("Asia/Shanghai")
                    )

                    self.state._proactive_share_scheduler = AsyncIOScheduler(
                        timezone=share_timezone
                    )
                    self.state._proactive_share_scheduler.add_job(
                        func=self._check_and_share_life,
                        trigger=IntervalTrigger(
                            minutes=self.state.proactive_share_interval_minutes,
                            timezone=share_timezone,
                        ),
                        name="proactive_share",
                        max_instances=1,
                    )
                    self.state._proactive_share_scheduler.start()
                    logger.info(
                        f"[主动分享] 已启动，每{self.state.proactive_share_interval_minutes}分钟检查，"
                        f"时间段: {self.state.proactive_share_time_ranges}"
                    )
                except Exception as e:
                    logger.error(f"启动主动分享调度器失败: {e}")
            else:
                self.state._proactive_share_scheduler = None

            if self.state.enable_qzone and QZONE_AVAILABLE:
                self.state.style = None
                if PILLOWMD_AVAILABLE:
                    try:
                        self.state.style = pillowmd.LoadMarkdownStyles(
                            self.state.pillowmd_style_dir
                        )
                    except Exception as e:
                        logger.error(f"无法加载pillowmd样式：{e}")

                task = asyncio.create_task(
                    self.initialize_qzone(wait_ws_connected=False)
                )
                self.state._background_tasks.add(task)
                task.add_done_callback(self.state._background_tasks.discard)

            self._print_plugin_status()
            logger.info("拟人化角色行为系统插件加载完毕！")
        except Exception as e:
            logger.error(f"插件初始化失败: {e}", exc_info=True)
            raise

    def _print_plugin_status(self):
        emotion_status = "开启" if self.state.enable_emotion_detection else "关闭"
        selfie_status = "开启" if self.state.enable_auto_selfie else "关闭"
        context_status = "开启" if self.state.enable_context_events else "关闭"
        life_sim_status = "开启" if self.state.enable_life_simulation else "关闭"
        qzone_status = "开启" if self.state.enable_qzone else "关闭"

        logger.info("=" * 50)
        logger.info("功能状态与使用场景：")
        logger.info(f"情绪检测: {emotion_status}")
        if self.state.enable_emotion_detection:
            logger.info("  • 在每次对话中分析用户情绪，并注入到LLM系统提示中")

        logger.info(f"自动自拍: {selfie_status}")
        if self.state.enable_auto_selfie:
            logger.info(
                f"  • 检测到特定情绪时，以{self.state.selfie_trigger_chance * 100}%概率触发自拍生成"
            )

        logger.info(f"上下文事件: {context_status}")
        if self.state.enable_context_events:
            logger.info("  • 检测对话中的问候、话题切换等事件")

        logger.info(f"生活模拟: {life_sim_status}")
        if self.state.enable_life_simulation:
            logger.info("  • 在对话中注入日程、天气、新闻等背景信息")
            logger.info(f"  • 日程生成时间：每天{self.state.schedule_hour}点")
            logger.info(f"  • 新闻学习时间：每天{self.state.news_hour}点")

        logger.info(f"QQ空间功能: {qzone_status}")
        proactive_status = "开启" if self.state.enable_proactive_messages else "关闭"
        logger.info(f"主动消息: {proactive_status}")
        if self.state.enable_proactive_messages:
            logger.info(f"  • 空闲问候延迟: {self.state.idle_greeting_delay}秒")
            if self.state.enable_proactive_sharing:
                logger.info(
                    f"  • 主动分享: 开启（每{self.state.proactive_share_interval_minutes}分钟，"
                    f"时间段: {self.state.proactive_share_time_ranges}）"
                )
        logger.info("=" * 50)

    async def terminate(self):
        try:
            logger.info("拟人化角色行为系统插件正在卸载...")

            for task in self.state._background_tasks:
                task.cancel()
            if self.state._background_tasks:
                await asyncio.gather(
                    *self.state._background_tasks, return_exceptions=True
                )
            self.state._background_tasks.clear()

            if self.state.enable_async_thinking and self.state.async_thinking_scheduler:
                try:
                    self.state.async_thinking_scheduler.stop()
                    logger.info("异步思考循环已停止")
                except Exception as e:
                    logger.error(f"停止异步思考循环失败: {e}")

            if self.state.proactive_manager:
                try:
                    self.state.proactive_manager.stop_scheduler()
                    logger.debug("主动消息调度器已停止")
                except Exception as e:
                    logger.debug(f"停止主动消息调度器失败: {e}")

            if self.state._proactive_share_scheduler is not None:
                try:
                    self.state._proactive_share_scheduler.shutdown(wait=False)
                    logger.debug("主动分享调度器已停止")
                except Exception as e:
                    logger.debug(f"停止主动分享调度器失败: {e}")

            self.state.emotion_contexts.clear()
            self.state._weather_cache.clear()
            self.state._news_cache.clear()
            self.state._schedule_cache.clear()
            self.state.favorability.clear()
            self.state.life_state.clear()

            if self.state.enable_qzone and QZONE_AVAILABLE:
                if self.state.qzone is not None:
                    try:
                        await self.state.qzone.terminate()
                        logger.debug("QQ空间模块已清理")
                    except Exception as e:
                        logger.debug(f"清理QQ空间模块失败: {e}")
                if self.state.auto_publish is not None:
                    try:
                        await self.state.auto_publish.terminate()
                        logger.debug("自动发布模块已清理")
                    except Exception as e:
                        logger.debug(f"清理自动发布模块失败: {e}")
                if self.state._comment_check_scheduler is not None:
                    try:
                        self.state._comment_check_scheduler.shutdown(wait=False)
                        logger.debug("独立评论检查调度器已清理")
                    except Exception as e:
                        logger.debug(f"清理独立评论检查调度器失败: {e}")

            logger.info("拟人化角色行为系统插件已卸载")
        except Exception as e:
            logger.error(f"插件卸载时发生错误: {e}", exc_info=True)

    @filter.on_platform_loaded()
    async def on_platform_loaded(self):
        if self.state.enable_qzone and QZONE_AVAILABLE:
            task = asyncio.create_task(self.initialize_qzone(wait_ws_connected=True))
            self.state._background_tasks.add(task)
            task.add_done_callback(self.state._background_tasks.discard)

    async def initialize_qzone(self, wait_ws_connected: bool = False):
        if self.state._qzone_initialized:
            logger.debug("[QQ空间] 已初始化，跳过重复调用")
            return
        self.state._qzone_initialized = True

        logger.info(f"[QQ空间] 开始初始化, wait_ws_connected={wait_ws_connected}")

        if not QZONE_AVAILABLE:
            logger.warning("[QQ空间] QZONE_AVAILABLE=False, 模块不可用")
            return

        logger.info("[QQ空间] 查找 aiocqhttp 客户端...")
        client = None
        for inst in self.context.platform_manager.platform_insts:
            if isinstance(inst, AiocqhttpAdapter):
                if client := inst.get_client():
                    logger.info(
                        f"[QQ空间] 找到 aiocqhttp 客户端: {type(inst).__name__}"
                    )
                    break
        if not client:
            logger.warning("[QQ空间] 未找到 aiocqhttp 客户端，初始化终止")
            return

        if wait_ws_connected:
            ws_connected = asyncio.Event()

            @client.on_websocket_connection
            def _(_):
                ws_connected.set()

            try:
                await asyncio.wait_for(ws_connected.wait(), timeout=10)
            except asyncio.TimeoutError:
                logger.warning("等待 aiocqhttp WebSocket 连接超时")

        logger.info("[QQ空间] 创建Qzone对象...")
        self.state.qzone = Qzone(client)
        logger.info("[QQ空间] Qzone对象创建完成")

        logger.info("[QQ空间] 登录QQ空间...")
        await self.state.qzone.ready()
        if not self.state.qzone.ctx:
            logger.warning("[QQ空间] 登录失败，ctx未初始化，部分功能可能不可用")
        else:
            logger.info(f"[QQ空间] 登录成功，uin={self.state.qzone.ctx.uin}")

        logger.info("[QQ空间] 创建LLMAction对象...")
        self.state.llm = LLMAction(self.context, self.state.config, client)
        self.state.llm.experience_bank = self.state.experience_bank
        self.state.llm.personality_evolution = self.state.personality_evolution
        logger.info("[QQ空间] LLMAction对象创建完成")

        enable_qzone = self.state.config.get("enable_qzone", False)
        publish_times = self.state.config.get("publish_times_per_day", 0)
        insomnia_prob = self.state.config.get("insomnia_probability", 0)
        logger.info(
            f"[QQ空间] 配置: enable_qzone={enable_qzone}, publish_times_per_day={publish_times}, insomnia_probability={insomnia_prob}"
        )

        logger.info("[QQ空间] 创建PostOperator...")
        from .core.post import PostDB

        db_path = (
            StarTools.get_data_dir("astrbot_plugin_realistic_persona") / "posts.db"
        )
        self.state.post_db = PostDB(db_path)
        await self.state.post_db.initialize()
        logger.info(f"[QQ空间] 数据库已初始化: {db_path}")

        self.state.operator = PostOperator(
            self.context,
            self.state.config,
            self.state.qzone,
            self.state.post_db,
            self.state.llm,
            self.state.style,
            self.state.local_data_manager,
        )
        logger.info("[QQ空间] PostOperator创建完成")

        self.state._comment_check_scheduler = None
        if self.state.config.get("enable_qzone") and (
            self.state.config.get("publish_times_per_day", 0) > 0
            or self.state.config.get("insomnia_probability", 0) > 0
        ):
            logger.info("[QQ空间] 创建AutoPublish...")
            from .core.scheduler import AutoPublish

            self.state.auto_publish = AutoPublish(
                self.context, self.state.config, self.state.operator
            )
            await self.state.auto_publish.start()
            logger.info("[QQ空间] AutoPublish创建完成")
        else:
            logger.info(
                "[QQ空间] 未启用自动发说说（enable_qzone=False 或 publish_times_per_day=0 且 insomnia_probability=0）"
            )
            if self.state.config.get("enable_qzone") and self.state.config.get(
                "enable_auto_reply_comments", True
            ):
                self._start_standalone_comment_check()

        logger.info("[QQ空间] 初始化完成！")
        logger.info(
            f"[QQ空间] 组件状态: qzone={'OK' if self.state.qzone is not None else 'MISSING'}, "
            f"llm={'OK' if self.state.llm is not None else 'MISSING'}, "
            f"operator={'OK' if self.state.operator is not None else 'MISSING'}"
        )

        # Now that llm_action is available, bind it to the thinking scheduler
        if (
            self.state.enable_async_thinking
            and self.state.async_thinking_scheduler
            and self.state.llm
        ):
            self.state.async_thinking_scheduler.llm_action = self.state.llm
            logger.debug("[QQ空间] 已将 llm_action 绑定到异步思考调度器")

    def _start_standalone_comment_check(self):
        try:
            import zoneinfo

            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from apscheduler.triggers.interval import IntervalTrigger

            tz = self.context.get_config().get("timezone")
            timezone = (
                zoneinfo.ZoneInfo(tz) if tz else zoneinfo.ZoneInfo("Asia/Shanghai")
            )

            self.state._comment_check_scheduler = AsyncIOScheduler(timezone=timezone)
            interval_minutes = self.state.config.get(
                "qzone_comment_check_interval_minutes", 60
            )
            self.state._comment_check_scheduler.add_job(
                func=self._standalone_check_and_reply_comments,
                trigger=IntervalTrigger(minutes=interval_minutes, timezone=timezone),
                name="standalone_comment_checker",
                max_instances=1,
            )
            self.state._comment_check_scheduler.start()
            logger.info(
                f"[QQ空间][独立评论检查] 已启动，每{interval_minutes}分钟检查一次"
            )
        except Exception as e:
            logger.error(f"[QQ空间][独立评论检查] 启动失败: {e}")

    async def _standalone_check_and_reply_comments(self):
        try:
            if self.state.operator is None:
                logger.debug("[独立评论检查] operator 未初始化，跳过")
                return
            if self.state.operator.qzone is None:
                logger.debug("[独立评论检查] operator.qzone 未初始化，跳过")
                return
            if self.state.operator.qzone.ctx is None:
                logger.debug("[独立评论检查] operator.qzone.ctx 未初始化，跳过")
                return
            logger.debug("[独立评论检查] 开始检查新评论并回复")
            await self.state.operator.auto_reply_to_comments()
            logger.debug("[独立评论检查] 评论检查和回复完成")
        except Exception as e:
            logger.error(f"[独立评论检查] 检查和回复评论失败: {e}")

    def _register_event_handlers(self):
        from .context_events import EventType

        self.state.event_trigger.register_handler(
            EventType.GREETING, self._handle_greeting_event
        )
        self.state.event_trigger.register_handler(
            EventType.TOPIC_CHANGE, self._handle_topic_change_event
        )
        self.state.event_trigger.register_handler(
            EventType.CONVERSATION_START, self._handle_conversation_start_event
        )

    async def _handle_greeting_event(self, event):
        logger.debug(f"检测到问候: {event.data.get('message')}")

    async def _handle_topic_change_event(self, event):
        logger.debug(
            f"话题切换: {event.data.get('old_topic')} -> {event.data.get('new_topic')}"
        )

    async def _handle_conversation_start_event(self, event):
        logger.debug(f"对话开始: {event.data.get('message')}")

    @filter.on_llm_request()
    async def on_llm_request_handler(
        self, event: AstrMessageEvent, request: ProviderRequest
    ):
        self.state._current_events[event.get_session_id()] = event
        return await self._on_llm_request_handler(event, request)

    async def _on_llm_request_handler(
        self, event: AstrMessageEvent, request: ProviderRequest
    ):
        analysis: dict | None = None

        try:
            now = datetime.now()
            time_str = now.strftime("%Y年%m月%d日 %H:%M:%S")
            time_info = f"[当前时间：{time_str}]"

            if hasattr(request, "system_prompt"):
                if request.system_prompt:
                    request.system_prompt = time_info + "\n" + request.system_prompt
                else:
                    request.system_prompt = time_info
            logger.debug(f"[时间信息] 已注入时间: {time_str}")
        except Exception as e:
            logger.debug(f"[时间信息] 注入失败: {e}")

        try:
            if hasattr(request, "messages") and request.messages:
                now = datetime.now()
                current_timestamp = now.timestamp()

                for msg in request.messages:
                    if isinstance(msg, dict) and "content" in msg:
                        if "time_info" not in msg:
                            msg_timestamp = msg.get("timestamp", current_timestamp)
                            time_diff_seconds = max(
                                0, int(current_timestamp - msg_timestamp)
                            )

                            if time_diff_seconds < 60:
                                time_diff_str = f"{time_diff_seconds}秒前"
                            elif time_diff_seconds < 3600:
                                time_diff_str = f"{time_diff_seconds // 60}分钟前"
                            elif time_diff_seconds < 86400:
                                time_diff_str = f"{time_diff_seconds // 3600}小时前"
                            else:
                                time_diff_str = f"{time_diff_seconds // 86400}天前"

                            if msg["role"] == "user" and not msg["content"].startswith(
                                "[用户说话时间:"
                            ):
                                msg["content"] = (
                                    f"[用户说话时间: {time_diff_str}]\n{msg['content']}"
                                )
                            elif msg["role"] == "assistant" and not msg[
                                "content"
                            ].startswith("[我的回复时间:"):
                                msg["content"] = (
                                    f"[我的回复时间: {time_diff_str}]\n{msg['content']}"
                                )

                logger.debug(
                    f"[历史消息] 已为 {len(request.messages)} 条消息注入时间戳"
                )
        except Exception as e:
            logger.debug(f"[历史消息时间戳] 处理失败: {e}")

        if self.state.enable_async_thinking and self.state.life_story_engine:
            try:
                current_persona = await self.life_manager.get_system_persona_profile()
                if current_persona:
                    self.state.life_story_engine.set_base_persona(current_persona)

                if self.state.life_story_engine.should_update():
                    if hasattr(self.state, "llm") and self.state.llm:
                        task = asyncio.create_task(
                            self.thinking_manager.update_life_story_async()
                        )
                        self.state._background_tasks.add(task)
                        task.add_done_callback(self.state._background_tasks.discard)
                        logger.info("[人生故事] 后台更新经历线已触发")

                story_context = self.state.life_story_engine.get_context_for_llm()
                if story_context:
                    context_hint = f"\n[背景上下文]\n{story_context}"
                    if hasattr(request, "system_prompt"):
                        if request.system_prompt:
                            request.system_prompt += context_hint
                        else:
                            request.system_prompt = context_hint
                    logger.debug(
                        f"[人生故事] 已注入上下文，长度: {len(story_context)}字符"
                    )

            except Exception as e:
                logger.error(f"人生故事引擎处理失败: {e}")

        if self.state.enable_emotion_detection:
            try:
                logger.debug("[情绪检测] 开始分析用户消息...")
                analysis = await self.emotion_manager.process_emotion_and_events(event)
                if analysis and analysis.get("emotion"):
                    emotion = analysis["emotion"]
                    session_id = event.get_session_id()
                    emotion_context = self.emotion_manager.get_context(session_id)

                    logger.info(f"[情绪检测] 检测到用户情绪: {emotion.value}")

                    emotion_info = f"\n[当前检测到用户情绪: {emotion.value}]"

                    trend = emotion_context.get_emotion_trend()
                    if trend:
                        emotion_info += f"\n[情绪趋势: {trend}]"

                    if analysis.get("should_selfie"):
                        emotion_info += "\n[建议: 可以考虑使用 draw 工具生成一张真人自拍图片，表现当前情绪状态，保持真实感]"

                    if hasattr(request, "system_prompt"):
                        if request.system_prompt:
                            request.system_prompt += emotion_info
                        else:
                            request.system_prompt = emotion_info

                    self.state.context_state.update_state(
                        session_id, "last_emotion", emotion.value
                    )
                    self.state.context_state.update_state(
                        session_id, "emotion_analysis", analysis
                    )
            except Exception as e:
                logger.error(f"情绪分析失败: {e}")

        if self.state.enable_life_simulation:
            try:
                user_message = (
                    event.message_obj.message_str
                    if hasattr(event, "message_obj")
                    else ""
                )

                simple_greetings = [
                    "你是谁",
                    "你好",
                    "hi",
                    "hello",
                    "在吗",
                    "在不在",
                    "是你吗",
                ]
                is_simple_question = any(
                    greeting in user_message.lower() for greeting in simple_greetings
                )

                if not is_simple_question and len(user_message) > 5:
                    logger.debug("[生活模拟] 开始构建生活上下文信息...")
                    life_info = await self.life_manager.build_life_context(
                        event, analysis
                    )
                    if life_info:
                        logger.info(f"[生活模拟] 已注入背景信息：{life_info[:50]}...")
                        life_context = (
                            f"\n\n[背景信息 - 仅供参考，不影响主要回答]\n{life_info}"
                        )
                        if hasattr(request, "system_prompt"):
                            if request.system_prompt:
                                request.system_prompt += life_context
                            else:
                                request.system_prompt = life_context
            except Exception as e:
                logger.error(f"生活模拟上下文构建失败: {e}")

        if (
            self.state.enable_async_thinking
            and self.state.personality_evolution
            and stable_hash(event.get_session_id()) % 10 == 0
        ):
            try:
                summary = self.state.personality_evolution.get_personality_summary()
                if summary:
                    phase = summary.get("current_phase", "stable")
                    phase_name = "稳定期" if phase == "stable" else "变化期"
                    expr = summary.get("expression_levels", {})
                    vocab = expr.get("vocabulary", 5)
                    humor = expr.get("humor", 5)
                    complexity = expr.get("complexity", 5)
                    habits = summary.get("core_habits", [])
                    personality_hint = (
                        f"\n[表达风格提示 - {phase_name}] "
                        f"词汇水平{vocab}/10，幽默感{humor}/10，句式复杂度{complexity}/10"
                    )
                    if habits:
                        personality_hint += f"。核心习惯：{', '.join(habits[:3])}"
                    if hasattr(request, "system_prompt"):
                        if request.system_prompt:
                            request.system_prompt += personality_hint
                        else:
                            request.system_prompt = personality_hint
            except Exception as e:
                logger.debug(f"注入人格演化上下文失败: {e}")

        if (
            self.state.enable_async_thinking
            and self.state.experience_bank
            and self.state.async_thinking_scheduler
        ):
            try:
                user_message = event.message_obj.message_str or ""
                session_id = event.get_session_id()
                unified_msg_origin = event.unified_msg_origin

                await self.experience_manager.record_interaction_async(
                    session_id, user_message, unified_msg_origin
                )

                if self.state.personality_evolution:
                    self.state.personality_evolution.daily_routine()

            except Exception as e:
                logger.error(f"记录用户交互失败: {e}")

        return None

    async def _check_and_share_life(self):
        await self.proactive_mgr.check_and_share_life(life_manager=self.life_manager)

    @filter.llm_tool(name="draw")
    async def draw(self, event: AstrMessageEvent, prompt: str, size: str = ""):
        """Generate an image using AI drawing based on the given prompt.

        Args:
            prompt(string): The drawing prompt describing the desired image content.
            size(string): The image size, e.g. '1024x1024'. Optional, defaults to configured size.
        """
        if not size:
            size = self.state.size

        logger.info(f"[绘图工具] 被调用 - prompt: {prompt[:50]}..., size: {size}")

        if not self.state.llm_tool_enabled:
            return "绘图工具已被禁用"

        if not self.state.api_key:
            return "API密钥未配置，无法生成图片"

        try:
            session_id = event.get_session_id()
            emotion_analysis = self.state.context_state.get_state(
                session_id, "emotion_analysis"
            )
            if emotion_analysis and emotion_analysis.get("emotion"):
                emotion = emotion_analysis["emotion"]
                logger.debug(f"[绘图工具] 检测到情绪: {emotion.value}")

            logger.info("[绘图工具] 开始根据上下文生成绘图提示词（LLM增强模式）...")
            enhanced_prompt = await self.image_manager.enhance_drawing_prompt(
                prompt,
                event=event,
                life_manager=self.life_manager,
                emotion_manager=self.emotion_manager,
            )
            if enhanced_prompt and enhanced_prompt != prompt:
                logger.info(
                    f"[绘图工具] ✅ 已使用LLM生成上下文感知提示词: {enhanced_prompt[:150]}..."
                )
            else:
                logger.info(
                    f"[绘图工具] ℹ️ 使用原始提示词（未经过LLM增强）: {enhanced_prompt[:150]}..."
                )

            logger.info("[绘图工具] 开始请求图片生成...")
            image_url = await self.image_manager.request_image(enhanced_prompt, size)
            logger.info(f"[绘图工具] 图片生成成功: {image_url}")

            chain: list[BaseMessageComponent] = [Image.fromURL(image_url)]

            logger.info("[绘图工具] 发送图片给用户...")
            await event.send(event.chain_result(chain))
            logger.info("[绘图工具] 图片已发送")

            return (
                f"图片已发送给用户。\n"
                f"图片内容：{prompt}\n\n"
                f"请不要重复描述图片内容，而是根据当前场景和情境，"
                f"用第一人称自然地表达你此刻的感受、心情或想法。\n"
                '例如："发你了，江边风景真的很好，风也舒服。"'
            )

        except Exception as e:
            error_msg = f"生成图片时遇到问题: {str(e)}"
            logger.error(f"[绘图工具] 失败: {error_msg}")
            await event.send(event.plain_result(error_msg))
            return f"图片生成失败：{str(e)}"

    @filter.command("aiimg")
    async def generate_image_command(self, event: AstrMessageEvent):
        full_message = event.message_obj.message_str
        parts = full_message.split(" ", 1)
        prompt = parts[1].strip() if len(parts) > 1 else ""

        if not prompt:
            yield event.plain_result("请提供提示词！使用方法：/aiimg <提示词>")
            return

        if not self.state.api_key:
            yield event.plain_result("API密钥未配置，无法生成图片")
            return

        try:
            image_url = await self.image_manager.request_image(prompt, self.state.size)
            chain: list[BaseMessageComponent] = [
                Plain(f"提示词：{prompt}\n"),
                Image.fromURL(image_url),
            ]
            yield event.chain_result(chain)
        except Exception as e:
            yield event.plain_result(f"生成图片失败: {str(e)}")

    @filter.command("sessions")
    async def list_sessions(self, event: AstrMessageEvent):
        try:
            sessions = await self.proactive_mgr.get_available_sessions()
            if not sessions:
                yield event.plain_result(
                    "暂无可用会话数据。\n"
                    "提示：请直接使用当前会话ID配置主动消息白名单。\n"
                    f"当前会话: {event.unified_msg_origin}"
                )
                return

            lines = ["📋 可用会话列表：\n"]
            for i, s in enumerate(sessions[:20], 1):
                sid = s["session_id"]
                title = s.get("title") or s.get("persona_name") or ""
                lines.append(f"{i}. {sid}" + (f" ({title})" if title else ""))

            lines.append(f"\n当前会话: {event.unified_msg_origin}")
            lines.append(
                "\n💡 将上述会话ID复制到「主动消息目标会话白名单」配置中即可。"
            )
            yield event.plain_result("\n".join(lines))
        except Exception as e:
            yield event.plain_result(f"获取会话列表失败: {e}")

    @filter.command("emotion_status")
    async def check_emotion_status(self, event: AstrMessageEvent):
        if not self.state.enable_emotion_detection:
            yield event.plain_result("情绪检测功能未启用")
            return

        session_id = event.get_session_id()
        status = self.emotion_manager.get_status(session_id)
        yield event.plain_result(status)

    @filter.command("life_story")
    async def show_life_story(self, event: AstrMessageEvent):
        if not self.state.enable_life_story or not self.state.life_story_engine:
            yield event.plain_result("人生故事引擎未启用")
            return

        try:
            story_dir = (
                StarTools.get_data_dir("astrbot_plugin_realistic_persona")
                / "life_story"
            )
            life_story_file = story_dir / "life_story.json"
            context_cache_file = story_dir / "context_cache.json"
            state_file = story_dir / "engine_state.json"

            display_parts = ["📖 人生故事预览\n"]

            if state_file.exists():
                with open(state_file, encoding="utf-8") as f:
                    state = json.load(f)
                ch_num = state.get("current_chapter", 0)
                update_count = state.get("update_count", 0)
                last_ts = state.get("last_update_time", 0)
                last_str = (
                    datetime.fromtimestamp(last_ts).strftime("%Y-%m-%d %H:%M")
                    if last_ts > 0
                    else "未更新"
                )
                display_parts.append(
                    f"📊 引擎状态\n"
                    f"  当前章节: 第{ch_num}章\n"
                    f"  更新次数: {update_count}\n"
                    f"  上次更新: {last_str}\n"
                )

            if life_story_file.exists():
                with open(life_story_file, encoding="utf-8") as f:
                    story = json.load(f)
                timeline = story.get("timeline", [])
                if timeline:
                    display_parts.append("━━━━ 📜 人生经历线 ━━━━\n")
                    for ch in timeline[-5:]:
                        chapter = ch.get("chapter", "?")
                        content = ch.get("content", "")
                        time_str = ch.get("time", "")[:10]
                        if len(content) > 200:
                            content = content[:200] + "..."
                        display_parts.append(
                            f"📕 第{chapter}章 ({time_str})\n{content}\n"
                        )
                else:
                    display_parts.append("📜 人生故事尚未生成\n")
            else:
                display_parts.append("📜 人生故事尚未生成\n")

            if context_cache_file.exists():
                with open(context_cache_file, encoding="utf-8") as f:
                    cache = json.load(f)
                compact = cache.get("compact_context", "")
                if compact:
                    if len(compact) > 300:
                        compact = compact[:300] + "..."
                    display_parts.append(f"━━━━ 📝 当前精简上下文 ━━━━\n{compact}\n")

            if len(display_parts) <= 1:
                display_parts.append("（人生故事尚未生成，请等待系统自动生成）")

            yield event.plain_result("\n".join(display_parts))
        except Exception as e:
            yield event.plain_result(f"获取人生故事失败: {str(e)}")

    @filter.command("personality_status")
    async def check_personality_status(self, event: AstrMessageEvent):
        if not self.state.enable_async_thinking or not self.state.personality_evolution:
            yield event.plain_result("人格演化系统未启用")
            return

        try:
            summary = self.state.personality_evolution.get_personality_summary()
            phase_name = "稳定期" if summary["current_phase"] == "stable" else "变化期"

            status = f"""🌱 人格演化状态

💬 表达能力：
- 词汇水平: {summary["expression_levels"]["vocabulary"]}/10
- 幽默成熟度: {summary["expression_levels"]["humor"]}/10
- 句式复杂度: {summary["expression_levels"]["complexity"]}/10

🔄 当前阶段: {summary["current_phase"]}
({phase_name})

❤️ 核心习惯：
{chr(10).join("- " + h for h in summary["core_habits"][:3])}

🌟 临时习惯：
{chr(10).join("- " + h for h in summary["temporary_habits"])}
            """

            yield event.plain_result(status)
        except Exception as e:
            yield event.plain_result(f"获取人格状态失败: {str(e)}")

    @filter.command("experience_status")
    async def check_experience_status(self, event: AstrMessageEvent):
        if not self.state.enable_async_thinking or not self.state.experience_bank:
            yield event.plain_result("经历银行未启用（需启用异步思考系统）")
            return

        try:
            parts = ["🏦 经历银行状态\n"]

            growth_summary = self.state.experience_bank.get_growth_summary()
            if growth_summary:
                skills = growth_summary.get("skills", {})
                if skills:
                    skill_lines = []
                    for name, info in skills.items():
                        if isinstance(info, dict):
                            level = info.get("level", 1)
                            skill_lines.append(f"  • {name}: Lv.{level}")
                        else:
                            skill_lines.append(f"  • {name}: Lv.{info}")
                    parts.append("💪 技能:")
                    parts.extend(skill_lines[:10])

                interests = growth_summary.get("interests", [])
                if interests:
                    interest_names = [
                        i.get("item", str(i)) if isinstance(i, dict) else str(i)
                        for i in interests[:8]
                    ]
                    parts.append(f"🎯 兴趣: {', '.join(interest_names)}")

                views = growth_summary.get("views", [])
                if views:
                    view_names = [
                        v.get("view", str(v)) if isinstance(v, dict) else str(v)
                        for v in views[:5]
                    ]
                    parts.append(f"💭 观点: {', '.join(view_names)}")

            conv_file = self.state.experience_bank.conversations_file
            if conv_file.exists():
                with open(conv_file, encoding="utf-8") as f:
                    line_count = sum(1 for line in f if line.strip())
                parts.append(f"\n📝 对话记录数: {line_count}")

            evt_file = self.state.experience_bank.events_file
            if evt_file.exists():
                with open(evt_file, encoding="utf-8") as f:
                    evt_count = sum(1 for line in f if line.strip())
                parts.append(f"📋 事件记录数: {evt_count}")

            rel_file = self.state.experience_bank.relationships_file
            if rel_file.exists():
                with open(rel_file, encoding="utf-8") as f:
                    rels = json.load(f)
                if rels:
                    parts.append(f"👥 记住的用户数: {len(rels)}")
                    for uid, rel in list(rels.items())[:5]:
                        count = rel.get("interaction_count", 0)
                        parts.append(f"  • 用户 {uid}: {count} 次互动")

            yield event.plain_result("\n".join(parts))
        except Exception as e:
            yield event.plain_result(f"获取经历银行状态失败: {str(e)}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("发说说")
    async def publish_feed(self, event: AiocqhttpMessageEvent):
        if not self.state.enable_qzone:
            await event.send(
                event.plain_result("QQ空间功能未启用，请在配置中开启 enable_qzone")
            )
            return
        if not QZONE_AVAILABLE:
            await event.send(
                event.plain_result(
                    "QQ空间模块加载失败，请检查 aiocqhttp/apscheduler 等依赖是否安装"
                )
            )
            return
        if not hasattr(self.state, "operator"):
            await event.send(event.plain_result("QQ空间模块初始化中，请稍后重试"))
            return
        if not self.state.style:
            await event.send(
                event.plain_result(
                    "pillowmd样式未加载，无法生成说说图片。请检查 pillowmd 是否正确安装以及 default_style 目录是否存在"
                )
            )
            return

        from .core.utils import get_image_urls

        text = event.message_str.partition(" ")[2]
        images = await get_image_urls(event)
        await self.state.operator.publish_feed(event=event, text=text, images=images)

    @filter.command("写说说", alias={"写稿", "写草稿"})
    async def write_draft(self, event: AiocqhttpMessageEvent, topic: str | None = None):
        if not self.state.enable_qzone:
            await event.send(
                event.plain_result("QQ空间功能未启用，请在配置中开启 enable_qzone")
            )
            return
        if not QZONE_AVAILABLE:
            await event.send(
                event.plain_result(
                    "QQ空间模块加载失败，请检查 aiocqhttp/apscheduler 等依赖是否安装"
                )
            )
            return
        if not hasattr(self.state, "llm") or not hasattr(self.state, "operator"):
            await event.send(event.plain_result("QQ空间模块初始化中，请稍后重试"))
            return

        from .core.utils import get_image_urls

        persona_profile = await self.state.get_persona_profile()
        text = await self.state.llm.generate_diary(
            group_id=event.get_group_id(), topic=topic, persona_profile=persona_profile
        )

        if not text:
            await event.send(
                event.plain_result("生成说说内容失败，请检查LLM配置或重试")
            )
            return

        logger.debug(f"[写说说] 生成的说说内容: {text}")
        images = await get_image_urls(event)

        if not images:
            try:
                user_id = self.state.config.get("diary_user_id", "")
                group_id = event.get_group_id() or ""
                image_prompt = await self.state.llm.generate_image_prompt_from_diary(
                    text, group_id=group_id, user_id=user_id
                )
                if image_prompt:
                    image_url = await self.state.llm._request_image_with_fallback(
                        image_prompt, self.state.size
                    )
                    if image_url:
                        images = [image_url]
            except Exception as e:
                logger.error(f"[写说说] 自动配图失败: {e}", exc_info=True)

        await self.state.operator.publish_feed(event, text, images, publish=True)

    @staticmethod
    def parse_tool_call(text: str) -> dict | None:
        if "<minimax:tool_call>" not in text:
            return None

        try:
            tool_match = re.search(r'invoke name="([^"]+)"', text)
            if not tool_match:
                return None

            tool_name = tool_match.group(1)

            prompt_match = re.search(r"<prompt>\s*(.+?)\s*</prompt>", text, re.DOTALL)
            if prompt_match:
                prompt = prompt_match.group(1).strip()
            else:
                alt_match = re.search(
                    r"<prompt>\s*(.+?)\s*</parameter>", text, re.DOTALL
                )
                if alt_match:
                    full_content = alt_match.group(1)
                    param_tag_match = re.search(
                        r"^(.+?)(?=<parameter)", full_content, re.DOTALL
                    )
                    if param_tag_match:
                        prompt = param_tag_match.group(1).strip()
                    else:
                        prompt = full_content.strip()
                else:
                    prompt = ""

            params = {"prompt": prompt}
            param_matches = re.findall(
                r'<parameter name="([^"]+)">([^<]+)</parameter>', text
            )
            for param_name, param_value in param_matches:
                params[param_name] = param_value.strip()

            return {"tool_name": tool_name, **params}
        except Exception as e:
            logger.error(f"[工具调用] 解析失败: {e}")
            return None

    async def execute_tool_call(
        self, tool_name: str, params: dict, event=None
    ) -> str | None:
        if tool_name == "draw":
            original_prompt = params.get("prompt", "")
            if not original_prompt:
                return None

            if not hasattr(self.state, "llm") or not self.state.llm:
                return None

            if not self.state.llm.ms_api_key:
                return None

            try:
                enhanced_prompt = await self.image_manager.enhance_drawing_prompt(
                    original_prompt,
                    event=event,
                    life_manager=self.life_manager,
                    emotion_manager=self.emotion_manager,
                )

                size = params.get("size", self.state.config.get("size", "1024x1024"))

                image_url = await self.state.llm._request_modelscope(
                    enhanced_prompt, size=size
                )
                if image_url:
                    return image_url
                return None
            except Exception as e:
                logger.error(f"[工具调用] 执行 draw 失败: {e}")
                return None
        else:
            logger.warning(f"[工具调用] 未知的工具: {tool_name}")
            return f"工具 '{tool_name}' 尚未实现"

    @filter.on_llm_response()
    async def on_llm_response_handler(self, event: AstrMessageEvent, resp: LLMResponse):
        text = resp.completion_text or ""
        if not text:
            return resp

        if self.state.enable_async_thinking and self.state.experience_bank:
            try:
                session_id = event.get_session_id()
                self.state.experience_bank.update_last_bot_response(
                    session_id, text[:500]
                )
            except Exception as e:
                logger.debug(f"[经历银行] 记录AI回复失败: {e}")

        if self.state.auto_profile_updater and isinstance(event, AiocqhttpMessageEvent):
            from .emotions import EMOTION_INTENSITY_MAP, EmotionAnalyzer

            self.state._cached_bot = event.bot

            try:
                bot_emotion = EmotionAnalyzer.analyze_emotion(text)
                if bot_emotion:
                    intensity = EMOTION_INTENSITY_MAP.get(bot_emotion, 0.5)
                    if intensity >= self.state.auto_profile_updater.threshold:
                        logger.info(
                            f"[Profile更新] 角色自身情绪: {bot_emotion.value} (强度: {intensity:.2f})"
                        )
                        task = asyncio.create_task(
                            self.profile_manager.auto_update_profile_on_emotion(
                                event=event, emotion=bot_emotion, intensity=intensity
                            )
                        )
                        self.state._background_tasks.add(task)
                        task.add_done_callback(self.state._background_tasks.discard)
            except Exception as e:
                logger.debug(f"[Profile更新] 角色情绪分析失败: {e}")

        tool_call = self.parse_tool_call(text)
        if tool_call:
            logger.info(f"[工具调用] 检测到工具调用: {tool_call}")
            tool_name = tool_call.pop("tool_name")
            result = await self.execute_tool_call(tool_name, tool_call, event=event)

            if result:
                return LLMResponse(completion_text=f"![image]({result})")
            else:
                return LLMResponse(completion_text="抱歉，图片生成失败了😥")

        image_gen_detected = (
            await self.image_manager.detect_and_handle_image_generation(
                text, event, draw_func=self.draw
            )
        )
        if image_gen_detected:
            return resp

        return resp
