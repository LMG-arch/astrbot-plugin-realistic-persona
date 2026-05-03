"""
拟人化角色行为系统插件 (Realistic Persona Plugin)
整合了情绪感知、生活模拟、QQ空间日记、AI配图等功能

版本: v1.17.0
作者: LMG-arch
最后更新: 2026-05-03
符合AstrBot插件开发完全指南规范
"""

import asyncio
import functools
import json
import random
import re
import time
from datetime import datetime
from pathlib import Path

import aiohttp

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import BaseMessageComponent, Image, Plain
from astrbot.api.provider import LLMResponse, ProviderRequest
from astrbot.api.star import Context, Star, StarTools, register
from astrbot.core.config.default import VERSION
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_platform_adapter import (
    AiocqhttpAdapter,
)
from astrbot.core.utils.version_comparator import VersionComparator


# 错误处理装饰器
def error_handler(func):
    """统一错误处理装饰器，用于捕获并记录异常"""

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            func_name = func.__name__
            logger.error(f"[错误处理] {func_name} 执行失败: {str(e)}", exc_info=True)
            # 不重新抛出异常，保证系统稳定性
            return None

    return wrapper


# 导入子模块
try:
    import pillowmd

    PILLOWMD_AVAILABLE = True
except ImportError:
    PILLOWMD_AVAILABLE = False
    logger.warning("pillowmd 未安装，部分渲染功能将不可用")

# 导入情绪和事件模块
from .context_events import (  # noqa: E402
    ContextEvent,
    ContextState,
    EventTrigger,
    EventType,
    ProactiveMessageManager,
)
from .core.async_thinking_scheduler import AsyncThinkingScheduler  # noqa: E402
from .core.auto_profile_updater import AutoProfileUpdater  # noqa: E402
from .core.experience_bank import ExperienceBank  # noqa: E402
from .core.life_story_engine import LifeStoryEngine  # noqa: E402

# 导入本地数据管理模块
from .core.local_data_manager import LocalDataManager  # noqa: E402
from .core.memory_manager import MemoryManager  # noqa: E402
from .core.news_getter import NewsGetter  # noqa: E402
from .core.personality_evolution import PersonalityEvolutionManager  # noqa: E402
from .core.psychology_engine import PsychologyEngine  # noqa: E402
from .core.thought_engine import ThoughtEngine  # noqa: E402
from .core.timeline_verifier import TimelineVerifier  # noqa: E402
from .emotions import EmotionAnalyzer, EmotionContext, EmotionType  # noqa: E402

# 导入QQ空间核心模块（如果可用）
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


class ThinkingLLM:
    """轻量级LLM助手，用于异步思考和活动生成，不依赖QQ平台

    Args:
        context: AstrBot插件上下文
        provider_id: 指定的LLM提供商ID，留空则使用默认提供商
    """

    def __init__(self, context, provider_id: str = ""):
        self.context = context
        self.provider_id = provider_id

    def _get_provider(self):
        """获取LLM提供商实例"""
        provider = None
        if self.provider_id:
            provider = self.context.get_provider_by_id(self.provider_id)
        if not provider:
            provider = self.context.get_using_provider()
        return provider

    async def generate_thought(self, prompt: str) -> str | None:
        """让大模型根据提示生成一段思考或内心独白"""
        provider = self._get_provider()
        if not provider:
            logger.warning("[思考LLM] 未配置LLM提供商，无法生成思考")
            return None
        try:
            resp = await provider.text_chat(
                system_prompt="你是一个善于思考的人。根据给定的情境，生成一段自然、真实的内心独白。要求：1.真实自然，像真人内心独白；2.长度15-50字；3.结合情境特点；4.直接返回思考内容，不要添加解释。",
                prompt=prompt,
            )
            text = (resp.completion_text or "").strip()
            # 清理：取第一行，去引号
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
        """让大模型根据提示生成一段日常活动描述"""
        provider = self._get_provider()
        if not provider:
            logger.warning("[思考LLM] 未配置LLM提供商，无法生成活动")
            return None
        try:
            resp = await provider.text_chat(
                system_prompt="你是一个正在度过日常生活的人。根据给定的情境，描述你此刻正在做的一件日常小事。要求：1.真实自然，贴近生活；2.长度10-30字；3.具体且有画面感；4.直接返回活动内容，不要添加解释。",
                prompt=prompt,
            )
            text = (resp.completion_text or "").strip()
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
    "1.17.0",
    "https://github.com/LMG-arch/astrbot-plugin-realistic-persona.git",
)
class Main(Star):
    """拟人化角色行为系统主类

    整合了多个模块以实现真实可信的AI角色体验：
    - 情绪感知系统：自动检测用户情绪并调整回复
    - 生活模拟系统：生成日程、获取天气和新闻
    - AI绘图功能：集成ModelScope文生图API
    - QQ空间日记：自动生成并发布说说
    - 异步思考系统：后台持续思考和经历累积
    - 人格演化系统：表达风格和习惯的渐进式演化
    """

    # 数据库版本
    DB_VERSION = 4

    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        """初始化插件

        Args:
            context: 插件上下文，提供对AstrBot核心服务的访问
            config: 插件配置字典 (AstrBotConfig)
        """
        super().__init__(context)
        self.context = context
        # 获取配置，优先使用传入的config，否则使用空dict
        if config is None:
            config = {}
        self.config = config

        # 存储当前请求的event（用于工具调用解析）
        self._current_event = None

        # 检查版本
        if not VersionComparator.compare_version(VERSION, "4.1.0") >= 0:
            raise Exception("AstrBot 版本过低, 请升级至 4.1.0 或更高版本")

        # ========== AI绘图配置 ==========
        self.api_key = config.get("api_key")
        self.model = config.get("ms_model", "Qwen/Qwen-Image")
        self.size = config.get("size", "1024x1024")
        self.api_url = config.get("api_url", "https://api-inference.modelscope.cn/")
        self.provider = config.get("provider", "ms")

        # ========== 图像生成检测配置 ==========
        self.enable_image_generation_detection = config.get(
            "enable_image_generation_detection", True
        )

        # ========== 情绪感知与事件配置 ==========
        self.enable_emotion_detection = config.get("enable_emotion_detection", True)
        self.enable_auto_selfie = config.get("enable_auto_selfie", False)
        self.selfie_trigger_chance = config.get("selfie_trigger_chance", 0.3)
        self.enable_proactive_messages = config.get("enable_proactive_messages", False)
        self.idle_greeting_delay = config.get("idle_greeting_delay", 600)
        self.enable_context_events = config.get("enable_context_events", True)
        self.llm_tool_enabled = config.get("llm_tool_enabled", True)

        # ========== 生活模拟与人设配置 ==========
        self.enable_life_simulation = config.get("enable_life_simulation", True)
        # 插件独立人设，优先级高于系统人设
        self.persona_name = config.get("persona_name", "她")
        self.persona_profile = config.get(
            "persona_profile", ""
        )  # 插件独立人设，留空则使用系统人设
        self.schedule_hour = config.get("schedule_hour", 7)
        self.news_hour = config.get("news_hour", 7)  # 默认早上7点获取新闻
        self.weather_location = config.get("weather_location", "")
        self.news_topics = config.get(
            "news_topics", ["科技", "生活方式", "兴趣相关话题"]
        )
        self.schedule_prompt = config.get("schedule_prompt", "")  # 日程生成提示词
        self.news_prompt = config.get("news_prompt", "")  # 新闻获取提示词

        # ========== QQ空间配置 ==========
        self.enable_qzone = config.get("enable_qzone", False)
        self.publish_cron = config.get("publish_cron", "")
        self.publish_times_per_day = config.get(
            "publish_times_per_day", 1
        )  # 每天发说说次数
        self.publish_time_ranges = config.get(
            "publish_time_ranges", ["9-12", "14-18", "19-22"]
        )  # 发说说时间段
        self.insomnia_probability = config.get(
            "insomnia_probability", 0.2
        )  # 失眠发说说概率
        self.diary_max_msg = config.get("diary_max_msg", 200)
        self.diary_user_id = config.get("diary_user_id", "")  # 优先使用的对话用户ID
        self.diary_prompt = config.get("diary_prompt", "")
        self.comment_prompt = config.get("comment_prompt", "")

        # ========== 个人资料自动更新配置 ==========
        self.enable_auto_profile_update = config.get(
            "enable_auto_profile_update", False
        )
        self.enable_auto_nickname = config.get("enable_auto_nickname", False)
        self.enable_auto_signature = config.get("enable_auto_signature", True)
        self.enable_auto_avatar = config.get("enable_auto_avatar", False)
        self.profile_update_cooldown = config.get("profile_update_cooldown", 1800)
        self.emotion_change_threshold = config.get("emotion_change_threshold", 0.6)

        # ========== 人生故事引擎配置 ==========
        self.enable_life_story = config.get(
            "enable_life_story", True
        )  # 是否启用人生故事引擎
        self.life_story_update_interval = config.get(
            "life_story_update_interval", 3
        )  # 更新间隔（天）
        self.life_story_collect_days = config.get(
            "life_story_collect_days", 7
        )  # 收集最近N天的经历
        self.life_story_context_max_length = config.get(
            "life_story_context_max_length", 200
        )  # 精简上下文最大长度
        self.life_story_cache_days = config.get(
            "life_story_cache_days", 7
        )  # 缓存有效期（天）

        # ========== 新闻获取配置 ==========
        self.enable_news_getter = config.get(
            "enable_news_getter", True
        )  # 是否启用新闻获取模块
        self.news_online_fetch = config.get(
            "news_online_fetch", True
        )  # 是否启用联网获取新闻

        # ========== 初始化状态管理 ==========
        self.emotion_contexts: dict[str, EmotionContext] = {}
        self.event_trigger = EventTrigger()
        self.proactive_manager = ProactiveMessageManager()
        self.context_state = ContextState()
        self.life_state: dict[str, dict] = {}
        self.favorability: dict[str, float] = {}

        # Token优化：缓存天气和新闻数据
        self._weather_cache = {"data": "", "timestamp": 0}  # 缓存1小时
        self._news_cache = {"data": "", "date": ""}  # 每天缓存一次
        self._schedule_cache = {"data": "", "date": ""}  # 每天缓存一次

        # 初始化本地数据管理器
        data_dir = (
            StarTools.get_data_dir("astrbot_plugin_realistic_persona") / "local_data"
        )
        self.local_data_manager = LocalDataManager(data_dir)

        # 初始化异步思考系统
        self.enable_async_thinking = config.get("enable_async_thinking", True)
        self.async_think_provider_id = config.get("async_think_provider_id", "")
        self.think_interval_minutes = config.get("think_interval_minutes", 20)
        self.activity_interval_minutes = config.get("activity_interval_minutes", 25)
        self.thought_engine = None
        self.experience_bank = None
        self.async_thinking_scheduler = None
        self.psychology_engine = None
        self.memory_manager = None
        self.timeline_verifier = None
        self.personality_evolution = None  # 人格演化管理器
        self.auto_profile_updater = None  # 自动Profile更新器
        self.life_story_engine = None  # 人生故事引擎
        self.news_getter = None  # 新闻获取器
        self._thinking_llm = None  # 轻量级思考LLM助手（不依赖QQ）

        # 初始化自动Profile更新器
        if self.enable_auto_profile_update:
            profile_dir = (
                StarTools.get_data_dir("astrbot_plugin_realistic_persona")
                / "auto_profile"
            )
            self.auto_profile_updater = AutoProfileUpdater(
                data_dir=profile_dir,
                enable_nickname=self.enable_auto_nickname,
                enable_signature=self.enable_auto_signature,
                enable_avatar=self.enable_auto_avatar,
                cooldown=self.profile_update_cooldown,
                threshold=self.emotion_change_threshold,
                persona_name=self.persona_name,
            )
            logger.info("自动Profile更新器已初始化")

        if self.enable_async_thinking:
            thought_dir = (
                StarTools.get_data_dir("astrbot_plugin_realistic_persona") / "thoughts"
            )
            exp_dir = (
                StarTools.get_data_dir("astrbot_plugin_realistic_persona")
                / "experience"
            )
            psych_dir = (
                StarTools.get_data_dir("astrbot_plugin_realistic_persona")
                / "psychology"
            )
            mem_dir = (
                StarTools.get_data_dir("astrbot_plugin_realistic_persona") / "memory"
            )
            timeline_dir = (
                StarTools.get_data_dir("astrbot_plugin_realistic_persona") / "timeline"
            )
            self.thought_engine = ThoughtEngine(thought_dir)
            self.experience_bank = ExperienceBank(exp_dir)
            self.psychology_engine = PsychologyEngine(psych_dir)
            self.memory_manager = MemoryManager(mem_dir)
            self.timeline_verifier = TimelineVerifier(timeline_dir)
            # 创建轻量级思考LLM助手（不依赖QQ平台，可独立使用）
            self._thinking_llm = ThinkingLLM(self.context, self.async_think_provider_id)
            self.async_thinking_scheduler = AsyncThinkingScheduler(
                self.thought_engine,
                self.experience_bank,
                llm_action=self._thinking_llm,
                persona_profile=self.persona_profile,
                context_provider=self._get_thinking_context,
                think_interval_minutes=self.think_interval_minutes,
                activity_interval_minutes=self.activity_interval_minutes,
            )

            # 初始化人格演化系统
            evolution_dir = (
                StarTools.get_data_dir("astrbot_plugin_realistic_persona")
                / "personality_evolution"
            )
            self.personality_evolution = PersonalityEvolutionManager(evolution_dir)
            logger.info("人格演化系统已初始化")

            # 初始化人生故事引擎
            if self.enable_life_story:
                story_dir = (
                    StarTools.get_data_dir("astrbot_plugin_realistic_persona")
                    / "life_story"
                )
                self.life_story_engine = LifeStoryEngine(
                    data_dir=story_dir,
                    experience_bank=self.experience_bank,
                    personality_evolution=self.personality_evolution,
                    thought_engine=self.thought_engine,
                    update_interval=86400
                    * self.life_story_update_interval,  # 使用配置的间隔
                    collect_days=self.life_story_collect_days,  # 使用配置的收集天数
                    context_max_length=self.life_story_context_max_length,  # 使用配置的最大长度
                    cache_days=self.life_story_cache_days,  # 使用配置的缓存天数
                )
                logger.info(
                    f"人生故事引擎已初始化（更新间隔: {self.life_story_update_interval}天, 收集范围: {self.life_story_collect_days}天）"
                )
            else:
                logger.info("人生故事引擎未启用")

            # 初始化新闻获取模块
            if self.enable_news_getter:
                news_dir = (
                    StarTools.get_data_dir("astrbot_plugin_realistic_persona")
                    / "news_data"
                )
                self.news_getter = NewsGetter(
                    data_dir=news_dir,
                    enable_online_fetch=self.news_online_fetch,
                    topics=self.news_topics,
                )
                logger.info(
                    f"新闻获取模块已初始化（联网获取: {self.news_online_fetch}, 主题: {self.news_topics}）"
                )
            else:
                logger.info("新闻获取模块未启用")

        # 注册事件处理器
        self._register_event_handlers()

        # QQ空间相关
        if self.enable_qzone and QZONE_AVAILABLE:
            self._init_qzone_settings(config)

        if not self.api_key:
            logger.warning("API密钥未配置，部分功能将不可用")

    def _init_qzone_settings(self, config):
        """初始化QQ空间相关设置"""
        # pillowmd样式目录 - 优先使用配置值，否则查找插件源目录下的 default_style
        configured_dir = config.get("pillowmd_style_dir")
        if configured_dir:
            self.pillowmd_style_dir = Path(configured_dir)
        else:
            # 尝试在插件源目录查找 default_style（StarTools.get_data_dir 指向 plugin_data，
            # 但默认样式文件随插件源码一起分发，位于 data/plugins/xxx/default_style）
            plugin_src_dir = Path(__file__).parent / "default_style"
            data_dir = (
                StarTools.get_data_dir("astrbot_plugin_realistic_persona")
                / "default_style"
            )
            if plugin_src_dir.exists():
                self.pillowmd_style_dir = plugin_src_dir
            elif data_dir.exists():
                self.pillowmd_style_dir = data_dir
            else:
                self.pillowmd_style_dir = plugin_src_dir  # fallback
                logger.warning(f"pillowmd样式目录不存在: {plugin_src_dir}")

        # 缓存目录
        self.cache = (
            StarTools.get_data_dir("astrbot_plugin_realistic_persona") / "cache"
        )
        self.cache.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _patch_toolset_openai_schema():
        """Monkey-patch ToolSet.openai_schema to always include description.

        Fixes AstrBot core bug where empty-string description causes OpenAI API
        400 BadRequestError (ToolDescription description=None) when tool re-query
        is performed after tool execution.
        """
        from astrbot.core.agent.tool import ToolSet

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
        """插件激活时调用，用于初始化资源和启动服务"""
        try:
            logger.info("拟人化角色行为系统插件正在加载...")

            # Monkey-patch AstrBot核心以修复400错误
            try:
                self._patch_toolset_openai_schema()
            except Exception as e:
                logger.warning(f"[补丁] ToolSet补丁应用失败: {e}")

            # 加载当天日程到配置显示
            try:
                now = datetime.now()
                today_str = now.strftime("%Y-%m-%d")
                cached_schedule = self.local_data_manager.get_schedule_data(today_str)
                if cached_schedule:
                    self.config["today_schedule_display"] = (
                        f"[当前日程 - {today_str}]\n\n{cached_schedule}"
                    )
                    logger.info("已加载当天日程到配置显示")
            except Exception as e:
                logger.debug(f"加载日程显示失败: {e}")

            # 加载人生故事到配置显示
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

                    # Count timeline entries
                    chapter_count = 0
                    if life_story_file.exists():
                        with open(life_story_file, encoding="utf-8") as f:
                            story = json.load(f)
                        chapter_count = len(story.get("timeline", []))

                    self.config["life_story_display"] = (
                        f"📊 引擎状态 | 第{ch_num}章 | 更新{update_count}次 | 上次: {last_str}\n"
                        f"📜 共记录 {chapter_count} 章人生经历\n\n"
                        f"💡 使用 /life_story 命令查看完整人生故事预览"
                    )
                    logger.info("已加载人生故事摘要到配置显示")
                else:
                    self.config["life_story_display"] = (
                        "（人生故事尚未生成，请等待系统自动生成）"
                    )
            except Exception as e:
                logger.debug(f"加载人生故事显示失败: {e}")

            # 启动异步思考循环
            if self.enable_async_thinking and self.async_thinking_scheduler:
                try:
                    self.async_thinking_scheduler.start()
                    logger.info("异步思考循环已启动")
                except Exception as e:
                    logger.error(f"启动异步思考循环失败: {e}")

            # 启动主动消息调度器
            if self.enable_proactive_messages:
                try:
                    asyncio.create_task(
                        self.proactive_manager.start_scheduler(
                            self._send_proactive_message
                        )
                    )
                    logger.info(
                        f"主动消息功能已启动，空闲延迟: {self.idle_greeting_delay}秒"
                    )
                except Exception as e:
                    logger.error(f"启动主动消息调度器失败: {e}")

            # 初始化QQ空间相关设置
            if self.enable_qzone and QZONE_AVAILABLE:
                # 实例化pillowmd样式
                self.style = None
                if PILLOWMD_AVAILABLE:
                    try:
                        self.style = pillowmd.LoadMarkdownStyles(
                            self.pillowmd_style_dir
                        )
                    except Exception as e:
                        logger.error(f"无法加载pillowmd样式：{e}")

                asyncio.create_task(self.initialize_qzone(wait_ws_connected=False))

            # 打印状态和使用说明
            self._print_plugin_status()

            logger.info("拟人化角色行为系统插件加载完毕！")
        except Exception as e:
            logger.error(f"插件初始化失败: {e}", exc_info=True)
            raise

    def _print_plugin_status(self):
        """打印插件状态信息"""
        emotion_status = "开启" if self.enable_emotion_detection else "关闭"
        selfie_status = "开启" if self.enable_auto_selfie else "关闭"
        context_status = "开启" if self.enable_context_events else "关闭"
        life_sim_status = "开启" if self.enable_life_simulation else "关闭"
        qzone_status = "开启" if self.enable_qzone else "关闭"

        logger.info("=" * 50)
        logger.info("功能状态与使用场景：")
        logger.info(f"情绪检测: {emotion_status}")
        if self.enable_emotion_detection:
            logger.info("  • 在每次对话中分析用户情绪，并注入到LLM系统提示中")

        logger.info(f"自动自拍: {selfie_status}")
        if self.enable_auto_selfie:
            logger.info(
                f"  • 检测到特定情绪时，以{self.selfie_trigger_chance * 100}%概率触发自拍生成"
            )

        logger.info(f"上下文事件: {context_status}")
        if self.enable_context_events:
            logger.info("  • 检测对话中的问候、话题切换等事件")

        logger.info(f"生活模拟: {life_sim_status}")
        if self.enable_life_simulation:
            logger.info("  • 在对话中注入日程、天气、新闻等背景信息")
            logger.info(f"  • 日程生成时间：每天{self.schedule_hour}点")
            logger.info(f"  • 新闻学习时间：每天{self.news_hour}点")

        logger.info(f"QQ空间功能: {qzone_status}")
        logger.info("=" * 50)

    async def terminate(self):
        """插件停用时调用，用于清理资源和停止服务"""
        try:
            logger.info("拟人化角色行为系统插件正在卸载...")

            # 停止异步思考循环
            if self.enable_async_thinking and self.async_thinking_scheduler:
                try:
                    self.async_thinking_scheduler.stop()
                    logger.info("异步思考循环已停止")
                except Exception as e:
                    logger.error(f"停止异步思考循环失败: {e}")

            # 停止主动消息调度器
            if self.proactive_manager:
                try:
                    self.proactive_manager.stop_scheduler()
                    logger.debug("主动消息调度器已停止")
                except Exception as e:
                    logger.debug(f"停止主动消息调度器失败: {e}")

            # 清空情绪上下文
            if hasattr(self, "emotion_contexts"):
                self.emotion_contexts.clear()

            # 清理缓存
            if hasattr(self, "_weather_cache"):
                self._weather_cache.clear()
            if hasattr(self, "_news_cache"):
                self._news_cache.clear()
            if hasattr(self, "_schedule_cache"):
                self._schedule_cache.clear()
            if hasattr(self, "favorability"):
                self.favorability.clear()
            if hasattr(self, "life_state"):
                self.life_state.clear()

            # 清理QQ空间相关资源
            if self.enable_qzone and QZONE_AVAILABLE:
                if hasattr(self, "qzone"):
                    try:
                        await self.qzone.terminate()
                        logger.debug("QQ空间模块已清理")
                    except Exception as e:
                        logger.debug(f"清理QQ空间模块失败: {e}")
                if hasattr(self, "auto_publish"):
                    try:
                        await self.auto_publish.terminate()
                        logger.debug("自动发布模块已清理")
                    except Exception as e:
                        logger.debug(f"清理自动发布模块失败: {e}")

            logger.info("拟人化角色行为系统插件已卸载")
        except Exception as e:
            logger.error(f"插件卸载时发生错误: {e}", exc_info=True)

    @filter.on_platform_loaded()
    async def on_platform_loaded(self):
        """平台加载完成时"""
        if self.enable_qzone and QZONE_AVAILABLE:
            asyncio.create_task(self.initialize_qzone(wait_ws_connected=True))

    async def initialize_qzone(self, wait_ws_connected: bool = False):
        """初始化QQ空间相关模块"""
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

        # 等待 ws 连接完成
        if wait_ws_connected:
            ws_connected = asyncio.Event()

            @client.on_websocket_connection
            def _(_):
                ws_connected.set()

            try:
                await asyncio.wait_for(ws_connected.wait(), timeout=10)
            except asyncio.TimeoutError:
                logger.warning("等待 aiocqhttp WebSocket 连接超时")

        # 加载QQ空间模块
        logger.info("[QQ空间] 创建Qzone对象...")
        self.qzone = Qzone(client)
        logger.info("[QQ空间] Qzone对象创建完成")

        # 登录QQ空间以初始化ctx
        logger.info("[QQ空间] 登录QQ空间...")
        await self.qzone.ready()
        if not self.qzone.ctx:
            logger.warning("[QQ空间] 登录失败，ctx未初始化，部分功能可能不可用")
        else:
            logger.info(f"[QQ空间] 登录成功，uin={self.qzone.ctx.uin}")

        # llm内容生成器
        logger.info("[QQ空间] 创建LLMAction对象...")
        self.llm = LLMAction(self.context, self.config, client)  # type: ignore[arg-type]
        # 注入经历银行和人格演化引用，用于生成日记时获取上下文
        self.llm.experience_bank = self.experience_bank
        self.llm.personality_evolution = self.personality_evolution
        logger.info("[QQ空间] LLMAction对象创建完成")

        # 输出配置信息
        enable_qzone = self.config.get("enable_qzone", False)
        publish_times = self.config.get("publish_times_per_day", 0)
        insomnia_prob = self.config.get("insomnia_probability", 0)
        logger.info(
            f"[QQ空间] 配置: enable_qzone={enable_qzone}, publish_times_per_day={publish_times}, insomnia_probability={insomnia_prob}"
        )

        # 创建PostOperator（手动命令和自动发布都需要）
        logger.info("[QQ空间] 创建PostOperator...")
        # 初始化数据库
        from .core.post import PostDB

        db_path = (
            StarTools.get_data_dir("astrbot_plugin_realistic_persona") / "posts.db"
        )
        self.post_db = PostDB(db_path)
        await self.post_db.initialize()
        logger.info(f"[QQ空间] 数据库已初始化: {db_path}")

        self.operator = PostOperator(  # type: ignore[arg-type,call-arg]
            self.context,
            self.config,
            self.qzone,
            self.post_db,
            self.llm,
            self.style,  # type: ignore[arg-type]
        )
        logger.info("[QQ空间] PostOperator创建完成")

        # 加载自动发说说模块（仅在启用时）
        if self.config.get("enable_qzone") and (
            self.config.get("publish_times_per_day", 0) > 0
            or self.config.get("insomnia_probability", 0) > 0
        ):
            logger.info("[QQ空间] 创建AutoPublish...")
            from .core.scheduler import AutoPublish

            self.auto_publish = AutoPublish(self.context, self.config, self.operator)  # type: ignore[arg-type]
            logger.info("[QQ空间] AutoPublish创建完成")
        else:
            logger.info(
                "[QQ空间] 未启用自动发说说（enable_qzone=False 或 publish_times_per_day=0 且 insomnia_probability=0）"
            )

        logger.info("[QQ空间] 初始化完成！")
        logger.info(
            f"[QQ空间] 组件状态: qzone={'OK' if hasattr(self, 'qzone') else 'MISSING'}, llm={'OK' if hasattr(self, 'llm') else 'MISSING'}, operator={'OK' if hasattr(self, 'operator') else 'MISSING'}"
        )

    # ========== 事件处理器注册 ==========

    def _register_event_handlers(self):
        """注册事件处理器"""
        self.event_trigger.register_handler(
            EventType.GREETING, self._handle_greeting_event
        )
        self.event_trigger.register_handler(
            EventType.TOPIC_CHANGE, self._handle_topic_change_event
        )
        self.event_trigger.register_handler(
            EventType.CONVERSATION_START, self._handle_conversation_start_event
        )

    async def _handle_greeting_event(self, event: ContextEvent):
        """处理问候事件"""
        logger.debug(f"检测到问候: {event.data.get('message')}")

    async def _handle_topic_change_event(self, event: ContextEvent):
        """处理话题切换事件"""
        logger.debug(
            f"话题切换: {event.data.get('old_topic')} -> {event.data.get('new_topic')}"
        )

    async def _handle_conversation_start_event(self, event: ContextEvent):
        """处理对话开始事件"""
        logger.debug(f"对话开始: {event.data.get('message')}")

    # ========== 情绪与上下文处理 ==========

    def _get_emotion_context(self, session_id: str) -> EmotionContext:
        """获取或创建情绪上下文"""
        if session_id not in self.emotion_contexts:
            self.emotion_contexts[session_id] = EmotionContext()
        return self.emotion_contexts[session_id]

    async def _process_emotion_and_events(self, event: AstrMessageEvent) -> dict | None:
        """处理情绪分析和事件检测"""
        message = event.message_obj.message_str
        session_id = event.get_session_id()

        # 更新好感度
        self._update_favorability(event)

        result = {
            "emotion": None,
            "should_selfie": False,
            "selfie_prompt": None,
            "events": [],
        }

        # 情绪检测
        if self.enable_emotion_detection:
            logger.debug("情绪检测已启用，开始分析...")
            emotion = EmotionAnalyzer.analyze_emotion(message)
            if emotion:
                result["emotion"] = emotion
                logger.info(f"检测到情绪: {emotion.value} 在会话 {session_id}")

                # 记录情绪
                emotion_context = self._get_emotion_context(session_id)
                emotion_context.add_emotion(emotion, message, time.time())

                # 检查是否应该自拍
                if self.enable_auto_selfie:
                    if EmotionAnalyzer.should_trigger_selfie(
                        emotion, self.selfie_trigger_chance
                    ):
                        result["should_selfie"] = True
                        result["selfie_prompt"] = EmotionAnalyzer.get_selfie_prompt(
                            emotion
                        )
                        logger.info(
                            f"触发自拍，情绪: {emotion.value}, 提示词: {result['selfie_prompt']}"
                        )

                # 自动修改个人资料（基于情绪变化）
                # 注意：只有 AiocqhttpMessageEvent 才有 bot 属性
                if self.auto_profile_updater and isinstance(
                    event, AiocqhttpMessageEvent
                ):
                    # 计算情绪强度
                    intensity_map = {
                        EmotionType.EXCITED: 0.9,
                        EmotionType.HAPPY: 0.6,
                        EmotionType.SAD: 0.7,
                        EmotionType.ANGRY: 0.8,
                        EmotionType.SURPRISED: 0.7,
                        EmotionType.ANXIOUS: 0.8,
                        EmotionType.BORED: 0.4,
                        EmotionType.CONFUSED: 0.5,
                        EmotionType.CURIOUS: 0.6,
                        EmotionType.CALM: 0.2,
                    }
                    intensity = intensity_map.get(emotion, 0.5)

                    # 异步调用Profile更新
                    asyncio.create_task(
                        self._auto_update_profile_on_emotion(
                            event=event, emotion=emotion, intensity=intensity
                        )
                    )
        else:
            logger.debug("情绪检测功能未启用")  # 终端日志

        # 检测明确的自拍请求
        if EmotionAnalyzer.detect_selfie_request(message):
            result["should_selfie"] = True
            if not result["selfie_prompt"]:
                result["selfie_prompt"] = (
                    f"一个友好可爱的{self.persona_name}自拍照，真人自拍，自然光线，日常装扮"
                )
            logger.info(f"检测到明确的自拍请求，会话: {session_id}")

        # 上下文事件检测
        if self.enable_context_events:
            events = self.event_trigger.detect_event(message)
            result["events"] = events

            # 触发事件处理器
            for evt in events:
                logger.debug(f"触发事件: {evt.event_type.value}，数据: {evt.data}")
                await self.event_trigger.trigger_event(evt)
        else:
            logger.debug("上下文事件检测未启用")

        logger.debug(
            f"情绪分析完成，结果: {result['emotion'].value if result['emotion'] else '无'}, 自拍: {result['should_selfie']}"
        )  # 终端日志
        return result

    async def _auto_update_profile_on_emotion(
        self, event: AiocqhttpMessageEvent, emotion: EmotionType, intensity: float
    ):
        """
        根据情绪自动更新个人资料

        Args:
            event: 消息事件
            emotion: 当前情绪
            intensity: 情绪强度（0-1）
        """
        if not self.auto_profile_updater:
            return

        try:
            # 获取LLM操作实例（用于生成头像）
            llm_action = None
            if self.enable_auto_avatar and hasattr(self, "llm"):
                llm_action = self.llm

            # 调用更新器
            result = await self.auto_profile_updater.check_and_update(
                event=event,
                emotion=emotion.value,
                intensity=intensity,
                llm_action=llm_action,
            )

            # 记录更新结果
            if any(result.values()):
                updates = [k for k, v in result.items() if v]
                logger.info(f"[Profile更新] 已更新: {', '.join(updates)}")
        except Exception as e:
            logger.error(f"[自动更新Profile] 失败: {e}", exc_info=True)

    def _update_favorability(self, event: AstrMessageEvent) -> None:
        """根据会话活动简单累计好感度"""
        try:
            session_id = event.get_session_id()
        except Exception:
            return
        current = self.favorability.get(session_id, 0.0)
        self.favorability[session_id] = current + 1.0

    async def _get_persona_profile(self) -> str:
        """
        获取人设配置，优先使用插件配置，其次使用系统人设

        Returns:
            人设描述文本
        """
        # 1. 优先使用插件自己的人设配置
        if self.persona_profile and self.persona_profile.strip():
            logger.debug("使用插件配置的人设")
            return self.persona_profile.strip()

        # 2. 回退到系统人设
        try:
            persona_mgr = self.context.persona_manager
            default_persona = await persona_mgr.get_default_persona_v3()
            system_profile = default_persona.get("prompt", "")
            if system_profile:
                logger.debug("使用系统配置的人设")
                return system_profile
        except Exception as e:
            logger.debug(f"获取系统人设失败: {e}")

        # 3. 都没有则返回空
        logger.debug("未配置人设，使用空字符串")
        return ""

    # ========== LLM请求钩子 ==========

    @filter.on_llm_request()
    async def on_llm_request_handler(
        self, event: AstrMessageEvent, request: ProviderRequest
    ):
        """LLM请求前钩子：存储事件并注入情绪/生活模拟上下文"""
        self._current_event = event
        return await self._on_llm_request_handler(event, request)

    async def _on_llm_request_handler(
        self, event: AstrMessageEvent, request: ProviderRequest
    ):
        """LLM 请求前处理：注入情绪信息与"生活模拟"上下文"""
        analysis: dict | None = None

        # 在每次对话前注入当前时间信息
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

        # 为历史消息注入时间戳，让LLM知道上一次对话距离现在的时间间隔
        try:
            if hasattr(request, "messages") and request.messages:
                now = datetime.now()
                current_timestamp = now.timestamp()

                # 遍历消息历史，为每条消息添加时间戳信息
                for i, msg in enumerate(request.messages):
                    if isinstance(msg, dict) and "content" in msg:
                        # 如果消息中没有时间信息，尝试添加
                        if "time_info" not in msg:
                            # 计算该消息距离现在的时间差
                            msg_timestamp = msg.get("timestamp", current_timestamp)
                            time_diff_seconds = int(current_timestamp - msg_timestamp)

                            # 转换为易读的时间差格式
                            if time_diff_seconds < 60:
                                time_diff_str = f"{time_diff_seconds}秒前"
                            elif time_diff_seconds < 3600:
                                time_diff_str = f"{time_diff_seconds // 60}分钟前"
                            elif time_diff_seconds < 86400:
                                time_diff_str = f"{time_diff_seconds // 3600}小时前"
                            else:
                                time_diff_str = f"{time_diff_seconds // 86400}天前"

                            # 为消息内容添加时间戳标记（避免重复添加）
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

        # 人生故事引擎：自动更新经历线并注入上下文
        if self.enable_async_thinking and self.life_story_engine:
            try:
                # 设置基础人设（仅首次）
                current_persona = await self._get_persona_profile()
                if current_persona:
                    self.life_story_engine.set_base_persona(current_persona)

                # 检查是否需要更新经历线
                if self.life_story_engine.should_update():
                    # 异步更新，不阻塞当前对话
                    if hasattr(self, "llm") and self.llm:
                        asyncio.create_task(self._update_life_story_async())
                        logger.info("[人生故事] 后台更新经历线已触发")

                # 获取精简的上下文提示
                story_context = self.life_story_engine.get_context_for_llm()
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

        # 情绪与上下文事件分析
        if self.enable_emotion_detection:
            try:
                logger.debug("[情绪检测] 开始分析用户消息...")
                analysis = await self._process_emotion_and_events(event)
                if analysis and analysis.get("emotion"):
                    emotion = analysis["emotion"]
                    session_id = event.get_session_id()
                    emotion_context = self._get_emotion_context(session_id)

                    logger.info(f"[情绪检测] 检测到用户情绪: {emotion.value}")

                    # 将情绪信息添加到系统提示中
                    emotion_info = f"\n[当前检测到用户情绪: {emotion.value}]"

                    # 获取情绪趋势
                    trend = emotion_context.get_emotion_trend()
                    if trend:
                        emotion_info += f"\n[情绪趋势: {trend}]"

                    # 如果情绪符合条件，提示 AI 可以考虑生成图片（注：这里的自拍指真人自拍，不是AI生成）
                    if analysis.get("should_selfie"):
                        emotion_info += "\n[建议: 可以考虑使用 draw 工具生成一张真人自拍图片，表现当前情绪状态，保持真实感]"

                    if hasattr(request, "system_prompt"):
                        if request.system_prompt:
                            request.system_prompt += emotion_info
                        else:
                            request.system_prompt = emotion_info

                    # 将情绪信息储存到上下文状态
                    self.context_state.update_state(
                        session_id, "last_emotion", emotion.value
                    )
                    self.context_state.update_state(
                        session_id, "emotion_analysis", analysis
                    )
            except Exception as e:
                logger.error(f"情绪分析失败: {e}")
                # 即使情绪分析失败，也要确保不影响LLM请求
                pass

        # 生活模拟：根据日程、天气、新闻等构造额外系统提示
        # 但要确保不干扰正常对话，只在需要时添加背景信息
        if self.enable_life_simulation:
            try:
                # 获取用户消息，判断是否需要生活背景
                user_message = (
                    event.message_obj.message_str
                    if hasattr(event, "message_obj")
                    else ""
                )

                # 如果是简单问题（如“你是谁”、“你好”等），不添加生活上下文
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
                    life_info = await self._build_life_context_info(event, analysis)
                    if life_info:
                        logger.info(
                            f"[生活模拟] 已注入背景信息：{life_info[:50]}..."
                        )  # 只显示前50字符
                        # 作为辅助信息添加，不是主要上下文
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
                # 即使生活模拟失败，也要确保不影响LLM请求
                pass

        # 人格演化：注入表达风格上下文（每10次对话注入一次，避免过度token消耗）
        if (
            self.enable_async_thinking
            and self.personality_evolution
            and abs(hash(event.get_session_id())) % 10 == 0
        ):
            try:
                summary = self.personality_evolution.get_personality_summary()
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

        # 记录用户交互到经历银行（异步思考系统）
        if (
            self.enable_async_thinking
            and self.experience_bank
            and self.async_thinking_scheduler
        ):
            try:
                user_message = event.message_obj.message_str
                session_id = event.get_session_id()
                unified_msg_origin = event.unified_msg_origin

                # 记录用户交互到经历银行
                # 注：此时还没有AI回复，会在之后的访问中更新
                await self._record_interaction_async(
                    session_id, user_message, unified_msg_origin
                )

                # 人格演化：每日例行检查
                if self.personality_evolution:
                    self.personality_evolution.daily_routine()

            except Exception as e:
                logger.error(f"记录用户交互失败: {e}")

        # 确保函数返回None
        return None

    # ========== 经历累积辅助方法 ==========

    async def _build_life_context_info(
        self, event: AstrMessageEvent, analysis: dict | None
    ) -> str:
        """构建生活上下文信息（日程、天气、新闻等）"""
        try:
            now = datetime.now()
            context_parts = []

            # 获取日程
            schedule = await self._maybe_generate_schedule(now)
            if schedule:
                context_parts.append(f"今日安排：{schedule[:200]}...")  # 限制长度

            # 获取天气
            weather = await self._get_weather_desc()
            if weather:
                context_parts.append(f"天气情况：{weather}")

            # 获取新闻（仅在早上）
            if now.hour >= self.news_hour and now.hour < self.news_hour + 3:
                news = await self._maybe_fetch_news(now)
                if news:
                    context_parts.append(f"今日新闻：{news[:150]}...")  # 限制长度

            # Recent thoughts & activities (from async thinking system)
            if self.thought_engine:
                try:
                    recent_thoughts = self.thought_engine.get_today_thoughts()
                    if recent_thoughts:
                        thought_texts = [
                            t.get("content", "")
                            for t in recent_thoughts[-3:]
                            if t.get("content")
                        ]
                        if thought_texts:
                            context_parts.append(
                                f"最近内心想法：{'；'.join(thought_texts)}"
                            )
                    recent_activities = self.thought_engine.get_today_activities()
                    if recent_activities:
                        act_texts = [
                            a.get("content", "")
                            for a in recent_activities[-3:]
                            if a.get("content")
                        ]
                        if act_texts:
                            context_parts.append(
                                f"最近在做的事：{'；'.join(act_texts)}"
                            )
                except Exception as e:
                    logger.debug(f"获取最近思考/活动失败: {e}")

            return "\n".join(context_parts) if context_parts else ""
        except Exception as e:
            logger.error(f"构建生活上下文失败: {e}")
            return ""

    # ========== 经历累积辅助方法 ==========

    async def _record_interaction_async(
        self, session_id: str, user_message: str, unified_msg_origin: str = ""
    ) -> None:
        """记录用户交互到经历银行"""
        if not self.experience_bank:
            return

        try:
            # 记录对话
            self.experience_bank.record_conversation(
                user_id=session_id,
                user_message=user_message,
                bot_response="",  # 此时还没有AI回复
                session_id=session_id,
            )

            # 主动消息：更新最后互动时间并调度空闲问候
            if self.enable_proactive_messages:
                current_time = time.time()

                # 更新最后互动时间
                self.context_state.update_state(
                    session_id, "last_interaction_time", current_time
                )

                # 清除该会话之前调度的主动消息（因为用户已经发消息）
                self.proactive_manager.clear_scheduled_messages(
                    unified_msg_origin or session_id
                )

                # 检查是否在目标会话白名单中
                target_sessions = self.config.get("proactive_target_sessions", "")
                if target_sessions and unified_msg_origin:
                    allowed = [
                        s.strip() for s in target_sessions.split(",") if s.strip()
                    ]
                    if allowed and unified_msg_origin not in allowed:
                        logger.debug(
                            f"[主动消息] 会话 {unified_msg_origin} 不在白名单中，跳过调度"
                        )
                        return

                # 调度一条新的主动消息（在空闲延迟后发送）
                proactive_msg = await self._generate_proactive_greeting(session_id)

                # 使用完整的 unified_msg_origin 作为 session_id
                # AstrBot send_message 需要 "platform_id:message_type:session_id" 格式
                send_session_id = (
                    unified_msg_origin if unified_msg_origin else session_id
                )

                self.proactive_manager.schedule_message(
                    message=proactive_msg,
                    delay=self.idle_greeting_delay,
                    session_id=send_session_id,
                    context_data={
                        "triggered_by": "idle_detection",
                        "user_id": session_id,
                        "platform": unified_msg_origin.split(":")[0]
                        if ":" in unified_msg_origin
                        else "unknown",
                    },
                )
                logger.debug(
                    f"[主动消息] 已调度空闲问候，{self.idle_greeting_delay}秒后发送"
                )

            # 从用户消息中提取技能、兴趣等，自动更新成長追踪
            self._extract_and_update_growth(user_message)

            # 检测并记录长期项目
            self._detect_and_record_projects(user_message, session_id)

            # 检测并记录承诺
            self._detect_and_record_promises(user_message, session_id)

            # 记录生物钟状态
            self._record_circadian_state()

            # 执行关系网络智能压缩（每30次交互执行一次）
            if self.experience_bank and abs(hash(session_id)) % 30 == 0:
                self._analyze_relationship_network(session_id)

            # 更新心理引擎（内在驱动力、情绪、价值观）
            if self.psychology_engine:
                # 记录互动（满足连接需求）
                self.psychology_engine.record_interaction()

                # 检测是否感到孤独或新增需求互动
                connection_check = self.psychology_engine.check_connection_need()
                if connection_check.get("feels_lonely"):
                    logger.debug("[PSYCHOLOGY] 新增需求互动")

            # 记忆管理（优先级权量、琐碎淘汰）
            if self.memory_manager:
                # 记录此次对话，自动计算重要性
                context_clues = []
                if "记得" in user_message or "求你" in user_message:
                    context_clues.append("需要记录")

                self.memory_manager.record_weighted_conversation(
                    user_id=session_id,
                    user_message=user_message,
                    bot_response="",  # 此时还没有回复
                    context_clues=context_clues,
                    session_id=session_id,
                )

                # 自动应用记忆衰减 (每30次交互执行一次)
                if abs(hash(session_id)) % 30 == 0:
                    logger.debug("[记忆管理] 执行记忆衰减")
                    self.memory_manager.apply_memory_decay(days_threshold=30)

            # 时间线验证 - 验证经历的时间一致性
            if self.timeline_verifier:
                # 找到用户提及的时间信息
                time_markers = ["上月", "上周", "去年", "是日", "昨天"]
                mentioned_time = None
                for marker in time_markers:
                    if marker in user_message:
                        mentioned_time = marker
                        break

                # 如果检测到时间信息，验证更新时间线
                if mentioned_time:
                    self.timeline_verifier.add_experience(
                        experience_id=f"{session_id}_{datetime.now().timestamp()}",
                        content=user_message[:100],
                        event_date=mentioned_time,
                        event_type="conversation",
                    )

            logger.debug(f"用户交互已记录: {session_id}")

        except Exception as e:
            logger.debug(f"记录用户交互失败: {e}")

    def _extract_and_update_growth(self, message: str) -> None:
        """从用户消息中提取兴趣、技能等，自动更新成長追蹤"""
        if not self.experience_bank:
            return

        try:
            message_lower = message.lower()

            # 检测技能
            for skill in ["python", "java", "javascript", "c++", "latex"]:
                if skill.lower() in message_lower:
                    self.experience_bank.update_growth("skills", skill)

            # 检测兴趣
            for interest in ["编程", "旅游", "音乐", "电影", "游戏"]:
                if interest in message:
                    self.experience_bank.update_growth("interests", interest)

            # 检测观点
            if "成长" in message or "加油" in message:
                self.experience_bank.update_growth("views", "乐观向上")
            if "伤心" in message or "难过" in message:
                self.experience_bank.update_growth("views", "需要陪伴")

        except Exception as e:
            logger.debug(f"提取成長信息失败: {e}")

    def _detect_and_record_projects(self, message: str, session_id: str) -> None:
        """检测并记录长期项目进展"""
        if not self.experience_bank:
            return

        try:
            # 检测上月、上周等的时间前缀
            if "上月" in message or "上周" in message:
                # 検测项目完成
                if "学完" in message or "学了" in message or "学习" in message:
                    project = self._extract_project_name(message)
                    if project:
                        self.experience_bank.record_project(
                            project_name=project,
                            description=f"用户提及：{message[:100]}",
                            status="in_progress",
                            metadata={"user_id": session_id},
                        )
                        logger.debug(f"项目已记录: {project}")

        except Exception as e:
            logger.debug(f"検测项目失败: {e}")

    def _detect_and_record_promises(self, message: str, session_id: str) -> None:
        """检测并记录承诺

        检测样式：
        - "上次答应..." → 完成承诺
        - "记得..." → 新建承诺
        """
        if not self.experience_bank:
            return

        try:
            # 检测承诺完成
            completion_keywords = ["完成", "完成了", "做了", "已经", "成功"]
            if any(kw in message for kw in completion_keywords):
                # 提取承诺描述
                promise_desc = self._extract_promise_description(message)
                if promise_desc:
                    self.experience_bank.complete_promise(
                        promise_keyword=promise_desc[:30],
                        completion_note=f"用户提及: {message[:80]}",
                    )
                    logger.debug(f"承诺已标记为完成: {promise_desc}")

            # 检测新承诺
            if "记得" in message or "答应" in message or "承诺" in message:
                promise_desc = self._extract_promise_description(message)
                if promise_desc:
                    self.experience_bank.record_promise(
                        promise=promise_desc,
                        related_user_id=session_id,
                        metadata={"mentioned_in_message": message[:100]},
                    )
                    logger.debug(f"承诺已记录: {promise_desc}")

        except Exception as e:
            logger.debug(f"検测承诺失败: {e}")

    def _extract_project_name(self, message: str) -> str | None:
        """从消息中提取项目名称"""
        # 提取消息中第一个先前出现的中文词语或短语句
        keywords = ["课程", "书籍", "作品", "项目"]
        for kw in keywords:
            if kw in message:
                # 返回第一个100字以内的描述
                idx = message.find(kw)
                return message[max(0, idx - 10) : min(len(message), idx + 30)].strip()
        return None

    def _extract_promise_description(self, message: str) -> str | None:
        """从消息中提取承诺描述"""
        # 简单的提取逻辑，一般是消息的前100个字
        return message[:100].strip() if len(message) > 0 else None

    def _record_circadian_state(self) -> None:
        """根据当前时间记录生物钟状态"""
        if not self.experience_bank:
            return

        try:
            now = datetime.now()
            hour = now.hour

            # 根据时刻判断当前时段
            if 6 <= hour < 9:
                state = "清晨"
                energy = 6
                creativity = 7
            elif 9 <= hour < 12:
                state = "上午"
                energy = 8
                creativity = 8
            elif 12 <= hour < 14:
                state = "中午"
                energy = 5
                creativity = 4
            elif 14 <= hour < 18:
                state = "下午"
                energy = 7
                creativity = 7
            elif 18 <= hour < 21:
                state = "傍晚"
                energy = 6
                creativity = 6
            else:
                state = "深夜"
                energy = 4
                creativity = 5

            # 随机变化一些
            energy += random.randint(-2, 2)
            creativity += random.randint(-2, 2)
            mood = random.choice(["开心", "中性", "沮丧"])

            self.experience_bank.record_circadian_state(state, energy, creativity, mood)

        except Exception as e:
            logger.debug(f"记录生物钟失败: {e}")

    def _analyze_relationship_network(self, user_id: str) -> None:
        """
        执行关系网络的智能压缩
        提取关系里程碑和生成个性化特征描述
        """
        if not self.experience_bank:
            return

        try:
            # 提取关系里程碑(最多10个)
            milestones = self.experience_bank.extract_relationship_milestones(
                user_id, max_milestones=10
            )

            if milestones:
                logger.debug(f"[关系网络] 提取事件: {len(milestones)}个")

            # 生成个性化关系特征描述
            profile = self.experience_bank.generate_relationship_profile(user_id)

            if profile:
                logger.debug(
                    f"[关系网络] 特征: {profile.get('relationship_characteristics')}"
                )

        except Exception as e:
            logger.debug(f"[关系网络] 分析失败: {e}")

    async def _update_life_story_async(self):
        """异步更新人生故事（后台任务）"""
        try:
            logger.info("[人生故事] 开始异步更新经历线...")

            # 确保LLM可用
            if not hasattr(self, "llm") or not self.llm:
                logger.warning("[人生故事] LLM未初始化，跳过更新")
                return

            # 执行更新
            success = await self.life_story_engine.update_life_story(self.llm)

            if success:
                logger.info("[人生故事] 经历线更新成功")
            else:
                logger.warning("[人生故事] 经历线更新失败")

        except Exception as e:
            logger.error(f"[人生故事] 异步更新失败: {e}", exc_info=True)

    async def _send_proactive_message(
        self, message: str, session_id: str, context_data: dict
    ):
        """发送主动消息的回调函数

        Args:
            message: 消息内容
            session_id: 会话 ID
            context_data: 上下文数据
        """
        try:
            logger.info(f"[主动消息] 准备发送到会话 {session_id}: {message[:50]}...")

            if not session_id:
                logger.warning("[主动消息] 缺少session_id，无法发送")
                return

            logger.info(f"[主动消息] 触发 - 会话: {session_id}")
            logger.info(f"[主动消息] 内容: {message}")

            # 通过 AstrBot Context.send_message 发送消息
            from astrbot.api.event import MessageChain

            chain = MessageChain([Plain(message)])
            try:
                sent = await self.context.send_message(session_id, chain)
                if sent:
                    logger.info(f"[主动消息] 已发送到会话 {session_id}")
                else:
                    logger.warning(
                        f"[主动消息] 未找到匹配平台，消息未发送: {session_id}"
                    )
            except Exception as e:
                logger.warning(f"[主动消息] 发送失败: {e}")
                logger.warning(f"[主动消息] 消息已生成但未能发送: {message[:50]}...")

        except Exception as e:
            logger.error(f"[主动消息] 发送失败: {e}", exc_info=True)

    async def _generate_proactive_greeting(self, session_id: str = "") -> str:
        """生成主动问候消息，基于历史对话上下文让LLM生成个性化内容

        Args:
            session_id: 会话ID，用于获取历史对话上下文

        Returns:
            问候消息字符串
        """
        try:
            # 收集各种上下文信息
            context_parts = []
            now = datetime.now()

            # 1. 最近对话历史
            if session_id:
                try:
                    conversation_history = await self._get_recent_conversation_context(
                        session_id
                    )
                    if conversation_history:
                        context_parts.append(
                            f"[最近对话回顾：{' '.join(conversation_history[:3])}]"
                        )
                except Exception as e:
                    logger.debug(f"获取对话历史失败: {e}")

            # 2. 日程信息
            try:
                schedule_info = await self._maybe_generate_schedule(now)
                if schedule_info:
                    context_parts.append(f"[今日日程：{schedule_info[:200]}]")
            except Exception as e:
                logger.debug(f"获取日程失败: {e}")

            # 3. 天气信息
            try:
                if hasattr(self, "_weather_cache") and self._weather_cache:
                    weather_info = self._weather_cache.get("data")
                    if weather_info:
                        context_parts.append(f"[当前天气：{weather_info}]")
            except Exception as e:
                logger.debug(f"获取天气失败: {e}")

            # 4. 新闻信息
            try:
                if hasattr(self, "_news_cache") and self._news_cache:
                    news_info = self._news_cache.get("data")
                    if news_info:
                        context_parts.append(f"[今日新闻：{news_info[:150]}]")
            except Exception as e:
                logger.debug(f"获取新闻失败: {e}")

            # 5. 记忆/经历信息
            try:
                if self.experience_bank and session_id:
                    recent_exp = self.experience_bank.get_recent_conversations(
                        session_id, limit=3
                    )
                    if recent_exp:
                        exp_texts = [
                            c.get("bot_response", "")
                            for c in recent_exp
                            if c.get("bot_response")
                        ]
                        if exp_texts:
                            context_parts.append(
                                f"[最近互动：{'；'.join(exp_texts[:2])}]"
                            )
            except Exception as e:
                logger.debug(f"获取经历信息失败: {e}")

            context_info = "\n".join(context_parts) if context_parts else ""

            # 构建生成问候的提示词
            persona_profile = await self._get_persona_profile()
            greeting_prompt = (
                f"你是{self.persona_name}，{persona_profile}。\n"
                f"现在是{now.strftime('%Y年%m月%d日 %H:%M')}。\n"
                f"你注意到用户很久没来聊天了，想主动联系一下。\n"
                f"{context_info}\n\n"
                "请生成一条自然、亲切、符合你人设的主动问候消息，不要超过15个字。\n"
                "要求：\n"
                "1. 语气自然，像真人一样聊天\n"
                "2. 可以结合当前时间、天气、日程或之前的对话内容\n"
                "3. 表达关心或好奇，邀请用户聊天\n"
                "4. 不要使用过于正式的语言\n"
                "5. 不要提及你是AI或机器人\n\n"
                "消息内容："
            )

            # 尝试通过LLM生成个性化问候
            provider_id = self._get_provider_id()
            if provider_id and self.context and hasattr(self.context, "llm_generate"):
                try:
                    resp = await self.context.llm_generate(
                        chat_provider_id=provider_id,
                        prompt=greeting_prompt,
                    )
                    generated_greeting = (resp.completion_text or "").strip()
                    if generated_greeting:
                        logger.info(f"[主动消息] LLM生成问候: {generated_greeting}")
                        return generated_greeting
                except Exception as e:
                    logger.debug(f"LLM生成问候失败: {e}")

            # 回退到预设问候
            greetings = [
                "在吗？最近怎么样？😊",
                "很久没聊天了，忙吗？",
                "很久不见，有空聊聊吗？",
                f"{self.persona_name}，在忙什么呢？",
                "最近过得好吗？😌",
                "有空聊聊天吗？好久不见了！",
            ]
            return random.choice(greetings)
        except Exception as e:
            logger.error(f"生成主动问候失败: {e}")
            # 发生错误时返回随机问候
            greetings = [
                "在吗？最近怎么样？😊",
                "很久没聊天了，忙吗？",
                "很久不见，有空聊聊吗？",
                f"{self.persona_name}，在忙什么呢？",
                "最近过得好吗？😌",
                "有空聊聊天吗？好久不见了！",
            ]
            return random.choice(greetings)

    async def _get_recent_conversation_context(self, session_id: str) -> list:
        """获取最近的对话上下文"""
        # 这里可以接入AstrBot的对话历史管理功能
        # 暂时返回空列表，实际实现需要根据AstrBot的对话历史API
        try:
            if self.experience_bank:
                # 从经历银行获取最近的对话记录
                recent_conversations = self.experience_bank.get_recent_conversations(
                    session_id, limit=5
                )
                if recent_conversations:
                    # 提取用户消息内容
                    user_messages = []
                    for conv in recent_conversations:
                        if "user_message" in conv and conv["user_message"]:
                            user_messages.append(conv["user_message"])
                    return user_messages
        except Exception as e:
            logger.debug(f"获取对话历史上下文失败: {e}")
        return []

    def _get_provider_id(self) -> str | None:
        """获取当前使用的 LLM 提供者 ID"""
        try:
            provider = self.context.get_using_provider()
            if provider:
                meta = provider.meta()
                return getattr(meta, "id", None)
        except Exception:
            return None
        return None

    async def _maybe_generate_schedule(self, now: datetime) -> str:
        """在需要时生成当天的日程（使用本地数据管理器优化）"""
        today_str = now.strftime("%Y-%m-%d")

        # 首先尝试从本地数据管理器获取
        cached_schedule = self.local_data_manager.get_schedule_data(today_str)
        if cached_schedule:
            logger.info(f"从本地数据获取 {today_str} 的日程信息")
            # 更新缓存
            self._schedule_cache = {"data": cached_schedule, "date": today_str}
            return cached_schedule

        # 检查缓存
        if self._schedule_cache["date"] == today_str and self._schedule_cache["data"]:
            logger.debug(f"使用缓存的日程: {today_str}")
            return self._schedule_cache["data"]

        if now.hour < self.schedule_hour:
            logger.debug(
                f"当前时间 {now.hour} 小于日程生成时间 {self.schedule_hour}，跳过生成"
            )
            return ""

        # 从系统获取人设
        persona_profile = await self._get_system_persona_profile()
        logger.debug(f"获取系统人设成功，长度: {len(persona_profile)} 字符")

        provider_id = self._get_provider_id()
        if not provider_id:
            logger.warning("未找到可用的LLM提供者，无法生成日程")
            return self._build_fallback_schedule(today_str)

        schedule_text = ""
        # 生成详细的日程和穿着，特别强调天气对穿搭的影响
        weather_desc = await self._get_weather_desc()
        weather_hint = ""
        if weather_desc:
            weather_hint = f"当地天气：{weather_desc}。请根据天气选择合适的穿着（例如：下雨带伞、寒冷穿厚衣、热天穿薄衣）。\n"
        else:
            weather_hint = "请根据当剋季节和常规天气选择合适的穿着。\n"

        # 使用自定义提示词或默认提示词
        if self.schedule_prompt and self.schedule_prompt.strip():
            # 使用用户自定义的提示词
            custom_prompt = self.schedule_prompt.strip()
            # 替换模板变量
            custom_prompt = custom_prompt.replace("{persona_name}", self.persona_name)
            custom_prompt = custom_prompt.replace("{persona_profile}", persona_profile)
            custom_prompt = custom_prompt.replace("{today}", today_str)
            custom_prompt = custom_prompt.replace("{weather}", weather_desc or "未知")
            prompt = custom_prompt
            logger.info("使用自定义日程生成提示词")
        else:
            # 使用默认提示词
            prompt = (
                f"你是{self.persona_name}，{persona_profile}。\n"
                f"今天是{today_str}。\n"
                f"{weather_hint}\n"
                "请直接输出今天的详细生活安排：\n\n"
                "1. 今日穿搭：根据人设、当地天气和今天的活动，描述具体穿着（上衣、下装、鞋子、外套/配饰等），必须符合天气情况、角色性格和身份\n"
                "2. 早上（6:00-9:00）：起床时间、洗漱、早餐、出门准备等具体活动\n"
                "3. 上午（9:00-12:00）：主要活动（工作/上课/其他），具体在做什么\n"
                "4. 中午（12:00-14:00）：午餐地点和内容、午休安排\n"
                "5. 下午（14:00-18:00）：下午的具体安排和活动\n"
                "6. 前晚（18:00-20:00）：晚餐、休闲活动\n"
                "7. 晚上（20:00-23:00）：娱乐、学习、社交等活动\n"
                "8. 睡前（23:00-24:00）：洗漱、放松、睡觉准备\n\n"
                "重要：直接输出日程内容，不要添加任何确认、回复或解释性的话。用口语化表达，贴近真实人类生活，不要提到AI。每个时段1-2句话即可。"
            )

        logger.info(f"开始生成 {today_str} 的日程")
        try:
            resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
            )
            schedule_text = (resp.completion_text or "").strip()
            logger.info(f"日程生成成功，长度: {len(schedule_text)} 字符")
        except Exception as e:
            logger.error(f"生成日程失败: {e}")
            # 尝试使用更简化的提示词再次生成
            try:
                simple_prompt = f"为{self.persona_name}规划{today_str}的简单日程，包含穿搭和主要活动。"
                resp = await self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=simple_prompt,
                )
                schedule_text = (resp.completion_text or "").strip()
                if schedule_text:
                    logger.info(
                        f"使用简化提示词生成日程成功，长度: {len(schedule_text)} 字符"
                    )
                else:
                    logger.warning("简化提示词也无法生成日程")
                    schedule_text = self._build_fallback_schedule(today_str)
            except Exception as e2:
                logger.error(f"简化提示词生成日程也失败: {e2}")
                schedule_text = self._build_fallback_schedule(today_str)

        if not schedule_text:
            schedule_text = self._build_fallback_schedule(today_str)

        # 更新缓存
        self._schedule_cache = {"data": schedule_text, "date": today_str}

        # 保存到本地数据管理器
        self.local_data_manager.save_schedule_data(today_str, schedule_text)

        # 更新配置文件中的显示项
        try:
            self.config["today_schedule_display"] = (
                f"[当前日程 - {today_str}]\n\n{schedule_text}"
            )
            # 保存配置（如果支持）
            if hasattr(self.config, "save_config"):
                self.config.save_config()
            logger.debug("已更新配置中的日程显示")
        except Exception as e:
            logger.debug(f"更新配置显示失败: {e}")

        return schedule_text

    async def _maybe_fetch_news(self, now: datetime) -> str:
        """在需要时获取角色关注的早间新闻（基于独立新闻获取模块的实现）"""
        today_str = now.strftime("%Y-%m-%d")

        # 检查是否应该获取新闻（在指定时间后）
        if now.hour < self.news_hour:
            logger.debug(
                f"当前时间 {now.hour} 小于新闻获取时间 {self.news_hour}，跳过获取"
            )
            return ""

        # 首先尝试从本地缓存获取
        if self.news_getter:
            cached_news = self.news_getter.load_news_cache(today_str)
            if cached_news:
                logger.info(f"从本地缓存加载新闻: {today_str}")
                news_text = self.news_getter.generate_news_text(cached_news)
                self._news_cache = {"data": news_text, "date": today_str}
                return news_text

        # 检查内存缓存
        if self._news_cache["date"] == today_str and self._news_cache["data"]:
            logger.debug(f"使用内存缓存的新闻: {today_str}")
            return self._news_cache["data"]

        news_text = ""

        # 优先使用新闻获取模块获取
        if self.enable_news_getter and self.news_getter:
            try:
                logger.info(f"开始通过新闻获取模块获取 {today_str} 的早间新闻")
                news_data = await self.news_getter.fetch_news_data(self.news_topics)

                if news_data:
                    news_text = self.news_getter.generate_news_text(news_data)
                    logger.info(f"新闻获取成功，长度: {len(news_text)} 字符")

                    # 保存到缓存
                    self.news_getter.save_news_cache(today_str, news_data)
                else:
                    logger.warning("新闻获取模块未能获取新闻")
            except Exception as e:
                logger.error(f"新闻获取模块出错: {e}")

        # 如果新闻获取模块失败，回退到LLM联网搜索
        if not news_text:
            try:
                logger.info(f"回退到LLM联网搜索获取 {today_str} 的新闻")
                provider_id = self._get_provider_id()

                if provider_id:
                    topics = ", ".join(self.news_topics)

                    # 使用自定义提示词或默认提示词
                    if self.news_prompt and self.news_prompt.strip():
                        custom_prompt = self.news_prompt.strip()
                        custom_prompt = custom_prompt.replace("{today}", today_str)
                        custom_prompt = custom_prompt.replace("{topics}", topics)
                        prompt = custom_prompt
                        logger.info("使用自定义新闻获取提示词")
                    else:
                        prompt = f"联网搜索{today_str}早间新闻，关注{topics}，列出3条标题+简述。"

                    resp = await self.context.llm_generate(
                        chat_provider_id=provider_id,
                        prompt=prompt,
                    )
                    news_text = (resp.completion_text or "").strip()

                    if news_text and len(news_text) >= 20:
                        logger.info(f"LLM联网搜索成功，长度: {len(news_text)} 字符")
                    else:
                        logger.warning("LLM未能成功获取新闻")
                        news_text = ""
            except Exception as e:
                logger.error(f"LLM联网搜索失败: {e}")

        # 更新缓存
        self._news_cache = {"data": news_text, "date": today_str}

        # 保存到本地数据管理器
        if news_text:
            self.local_data_manager.save_news_data(today_str, news_text)

        return news_text

    async def _get_weather_desc(self) -> str:
        """获取简单的本地天气描述（使用本地数据管理器优化）"""
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")

        if not self.weather_location:
            logger.debug("未配置天气位置，跳过天气查询")
            return ""

        # 首先尝试从本地数据管理器获取
        cached_weather = self.local_data_manager.get_weather_data(today_str)
        if cached_weather:
            logger.info(f"从本地数据获取 {today_str} 的天气信息")
            # 更新内存缓存
            current_time = time.time()
            self._weather_cache = {"data": cached_weather, "timestamp": current_time}
            return cached_weather

        # 检查内存缓存（1小时内有效）
        current_time = time.time()
        if (
            self._weather_cache["data"]
            and (current_time - self._weather_cache["timestamp"]) < 3600
        ):
            logger.debug(f"使用内存缓存的天气数据: {self._weather_cache['data']}")
            return self._weather_cache["data"]

        weather_text = ""

        # 优先使用wttr.in获取实时天气
        try:
            async with aiohttp.ClientSession() as session:
                url = f"https://wttr.in/{self.weather_location}?format=3&lang=zh-cn"
                async with session.get(url, timeout=5) as resp:
                    if resp.status == 200:
                        weather_text = (await resp.text()).strip()
                        # 检查返回的是否是有效的天气信息
                        if (
                            weather_text
                            and "抱歉" not in weather_text
                            and "无法" not in weather_text
                            and "未知" not in weather_text
                        ):
                            logger.info(f"通过wttr.in获取天气成功: {weather_text}")
                        else:
                            weather_text = ""
        except Exception as e:
            logger.debug(f"通过wttr.in获取天气失败: {e}")

        # 如果wttr.in失败，尝试使用LLM的天气工具
        if not weather_text:
            provider_id = self._get_provider_id()
            if provider_id:
                try:
                    # Token优化：精简提示词
                    prompt = f"查询{self.weather_location}天气，仅返回简要描述。"
                    logger.info(f"开始查询 {self.weather_location} 的天气")
                    resp = await self.context.llm_generate(
                        chat_provider_id=provider_id,
                        prompt=prompt,
                    )
                    weather_text = (resp.completion_text or "").strip()
                    # 检查返回的是否是有效的天气信息
                    if (
                        weather_text
                        and "抱歉" not in weather_text
                        and "无法" not in weather_text
                        and "未知" not in weather_text
                    ):
                        logger.info(f"天气查询成功: {weather_text}")
                    else:
                        weather_text = ""
                except Exception as e:
                    logger.debug(f"使用天气工具获取天气失败: {e}")

        # 更新缓存和本地数据
        if weather_text:
            self._weather_cache = {"data": weather_text, "timestamp": current_time}
            # 保存到本地数据管理器
            self.local_data_manager.save_weather_data(today_str, weather_text)

            # 更新异步思考调度器的天气信息
            if self.enable_async_thinking and self.async_thinking_scheduler:
                try:
                    self.async_thinking_scheduler.set_weather(weather_text)
                    logger.debug(f"天气信息已更新到调度器: {weather_text}")
                except Exception as e:
                    logger.debug(f"更新天气信息到调度器失败: {e}")

        return weather_text or ""

    @staticmethod
    def _parse_weather_for_drawing(raw_weather: str) -> str:
        """Parse raw weather data into a clean description for drawing prompts.

        Transforms formats like "zhenxiong: 🌦 +7°C" into clean descriptions
        like "阴天，气温7摄氏度" suitable for LLM prompt generation.

        Args:
            raw_weather: Raw weather string from wttr.in or other source

        Returns:
            Clean weather description for drawing context
        """
        if not raw_weather:
            return ""

        import re

        weather = raw_weather.strip()

        # Remove location prefix (e.g. "zhenxiong: " or "Beijing: ")
        # wttr.in format: "location: emoji temp°C"
        if ":" in weather:
            weather = weather.split(":", 1)[1].strip()

        # Map emoji/weather symbols to Chinese descriptions
        weather_map = {
            "☀": "晴天",
            "🌤": "晴间多云",
            "⛅": "多云",
            "🌥": "阴天",
            "☁": "阴天",
            "🌦": "小雨",
            "🌧": "下雨",
            "⛈": "雷雨",
            "🌩": "雷电",
            "🌨": "下雪",
            "❄": "下雪",
            "🌫": "雾天",
            "🌪": "大风",
            "💨": "大风",
        }

        weather_desc = ""
        for emoji, desc in weather_map.items():
            if emoji in weather:
                weather_desc = desc
                break

        # Extract temperature
        temp_match = re.search(r"[+-]?\d+[°℃]", weather)
        if temp_match:
            temp_str = temp_match.group(0).replace("°C", "").replace("℃", "")
            try:
                temp = int(temp_str)
                if temp < 0:
                    weather_desc = (
                        f"寒冷，{temp}°C"
                        if not weather_desc
                        else f"{weather_desc}，{temp}°C"
                    )
                elif temp < 10:
                    weather_desc = (
                        f"凉爽，{temp}°C"
                        if not weather_desc
                        else f"{weather_desc}，{temp}°C"
                    )
                elif temp < 25:
                    weather_desc = (
                        f"温和，{temp}°C"
                        if not weather_desc
                        else f"{weather_desc}，{temp}°C"
                    )
                elif temp < 35:
                    weather_desc = (
                        f"炎热，{temp}°C"
                        if not weather_desc
                        else f"{weather_desc}，{temp}°C"
                    )
                else:
                    weather_desc = (
                        f"酷热，{temp}°C"
                        if not weather_desc
                        else f"{weather_desc}，{temp}°C"
                    )
            except ValueError:
                pass

        if not weather_desc:
            # If no emoji found, try to return something reasonable
            weather_desc = weather[:30] if weather else ""

        return weather_desc

    @staticmethod
    def _get_current_period_schedule(schedule_text: str, now: datetime) -> str:
        """Extract only the current time period's schedule for drawing prompt.

        Matches time-based schedule segments to the current hour.

        Args:
            schedule_text: Full schedule text for the day
            now: Current datetime

        Returns:
            The schedule segment for the current time period, or empty string
        """
        if not schedule_text:
            return ""

        hour = now.hour
        # Define time period patterns to match
        time_patterns = []
        if 6 <= hour < 9:
            time_patterns = [
                "6:00",
                "6：00",
                "早上",
                "上午(6",
                "早晨",
                "7:00",
                "7：00",
                "8:00",
                "8：00",
            ]
        elif 9 <= hour < 12:
            time_patterns = ["9:00", "9：00", "上午", "工作", "上课", "10:00", "11:00"]
        elif 12 <= hour < 14:
            time_patterns = ["12:00", "12：00", "中午", "午餐", "午休", "13:00"]
        elif 14 <= hour < 18:
            time_patterns = ["14:00", "14：00", "下午", "15:00", "16:00", "17:00"]
        elif 18 <= hour < 20:
            time_patterns = [
                "18:00",
                "18：00",
                "傍晚",
                "晚餐",
                "前晚",
                "19:00",
                "19：00",
            ]
        elif 20 <= hour < 23:
            time_patterns = [
                "20:00",
                "20：00",
                "晚上",
                "21:00",
                "22:00",
                "娱乐",
                "休闲",
            ]
        else:
            time_patterns = ["23:00", "23：00", "睡前", "深夜", "睡觉"]

        lines = schedule_text.split("\n")
        matched_lines = []
        for i, line in enumerate(lines):
            line_clean = line.strip().replace("**", "").replace("*", "")
            for pattern in time_patterns:
                if pattern in line_clean:
                    matched_lines.append(line_clean)
                    # Also include the next line if it's a continuation
                    if i + 1 < len(lines):
                        next_line = (
                            lines[i + 1].strip().replace("**", "").replace("*", "")
                        )
                        if next_line and not any(
                            p in next_line
                            for p in [
                                "6:00",
                                "9:00",
                                "12:00",
                                "14:00",
                                "18:00",
                                "20:00",
                                "23:00",
                            ]
                        ):
                            matched_lines.append(next_line)
                    break

        if matched_lines:
            return "\n".join(matched_lines)

        # Fallback: return first 100 chars of schedule
        return schedule_text[:100]

    async def _get_thinking_context(self) -> dict:
        """为异步思考提供上下文信息（天气、日程、新闻、最近对话和经历）

        Returns:
            dict with keys: weather, schedule, news, recent_conversations, recent_experiences
        """
        ctx: dict = {}
        now = datetime.now()

        # 1. Weather
        try:
            if hasattr(self, "_weather_cache") and self._weather_cache.get("data"):
                ctx["weather"] = self._weather_cache["data"]
            else:
                weather = await self._get_weather_desc()
                if weather:
                    ctx["weather"] = weather
        except Exception as e:
            logger.debug(f"[思考上下文] 获取天气失败: {e}")

        # 2. Schedule
        try:
            schedule = await self._maybe_generate_schedule(now)
            if schedule:
                ctx["schedule"] = schedule
        except Exception as e:
            logger.debug(f"[思考上下文] 获取日程失败: {e}")

        # 3. News
        try:
            if hasattr(self, "_news_cache") and self._news_cache.get("data"):
                ctx["news"] = self._news_cache["data"]
        except Exception as e:
            logger.debug(f"[思考上下文] 获取新闻失败: {e}")

        # 4. Recent conversations
        try:
            if self.experience_bank:
                convs = self.experience_bank.get_recent_conversations(limit=5)
                if convs:
                    conv_summaries = []
                    for c in convs:
                        user_msg = c.get("user_message", "")
                        bot_msg = c.get("bot_response", "")
                        if user_msg or bot_msg:
                            conv_summaries.append(f"用户:{user_msg} 机器人:{bot_msg}")
                    if conv_summaries:
                        ctx["recent_conversations"] = "；".join(conv_summaries[:5])
        except Exception as e:
            logger.debug(f"[思考上下文] 获取最近对话失败: {e}")

        # 5. Recent experiences/events
        try:
            if self.experience_bank:
                events = self.experience_bank.get_recent_events(limit=5)
                if events:
                    event_summaries = [
                        f"[{e.get('event_type', '')}] {e.get('description', '')}"
                        for e in events
                        if e.get("description")
                    ]
                    if event_summaries:
                        ctx["recent_experiences"] = "；".join(event_summaries[:5])
        except Exception as e:
            logger.debug(f"[思考上下文] 获取最近经历失败: {e}")

        return ctx

    def _get_current_activity(self, now: datetime) -> str:
        """根据时间段粗略推断当前生活活动"""
        h = now.hour
        if h < 6 or h >= 23:
            return "已经睡觉或准备睡觉，不太方便频繁看手机"
        if 6 <= h < 9:
            return "刚起床不久，在洗漱、吃早饭或者路上通勤"
        if 9 <= h < 12:
            return "在认真上班/上课/学习，处理中午前需要完成的任务"
        if 12 <= h < 14:
            return "吃午饭、午休或刷手机放松一会儿"
        if 14 <= h < 18:
            return "继续忙工作/学习，中间会偶尔看看消息但回复不一定及时"
        if 18 <= h < 21:
            return "吃晚饭、和朋友聊天、追剧或做一些轻松的娱乐活动"
        return "准备洗漱和收尾今天的事情，一边刷手机一边慢慢放松"

    def _build_fallback_schedule(self, today_str: str) -> str:
        """在 LLM 不可用时的兜底日程模板"""
        return (
            f"{today_str} 的日程：\n\n"
            "今日穿搭：休闲舒适的日常装扮。\n"
            "早上：7:00起床洗漱，简单吃点早餐，整理一下今天要用的东西。\n"
            "上午：处理一些需要专注的任务，中途喝杯水休息一下。\n"
            "中午：吃个简单的午餐，午休放松半小时。\n"
            "下午：继续工作/学习，适当活动活动身体。\n"
            "傍晚：吃晚饭，出去散散步或者做点轻松的事情。\n"
            "晚上：追剧、玩游戏或者和朋友聊天，放松一下。\n"
            "睡前：洗漱，看看明天的计划，23:00左右睡觉。\n"
        )

    async def _get_system_persona_profile(self) -> str:
        """从系统获取人设描述"""
        try:
            # 使用系统的人设管理器获取默认人设
            default_persona = (
                await self.context.persona_manager.get_default_persona_v3()
            )
            return (
                default_persona["prompt"]
                or "一个普通的年轻人，有自己的日程、情绪和兴趣，会像真人一样安排每天的生活。"
            )
        except Exception as e:
            logger.warning(f"获取系统人设失败: {e}，使用默认人设")
            return "一个普通的年轻人，有自己的日程、情绪和兴趣，会像真人一样安排每天的生活。"

    # ========== AI绘图功能 ==========

    async def _request_modelscope(
        self, prompt: str, size: str, session: aiohttp.ClientSession
    ) -> str:
        """向ModelScope API发送请求"""
        common_headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        current_seed = random.randint(1, 2147483647)
        payload = {
            "model": self.model,
            "prompt": prompt,
            "seed": current_seed,
            "size": size,
            "steps": 30,
        }

        async with session.post(
            f"{self.api_url}v1/images/generations",
            headers={**common_headers, "X-ModelScope-Async-Mode": "true"},
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        ) as response:
            response.raise_for_status()
            task_response = await response.json()
            task_id = task_response.get("task_id")

            if not task_id:
                raise Exception("未能获取任务ID，生成图片失败。")

        # 使用指数退避策略轮询结果
        delay = 1
        max_delay = 10
        while True:
            async with session.get(
                f"{self.api_url}v1/tasks/{task_id}",
                headers={
                    **common_headers,
                    "X-ModelScope-Task-Type": "image_generation",
                },
            ) as result_response:
                result_response.raise_for_status()
                data = await result_response.json()

                task_status = data.get("task_status")
                if task_status == "SUCCEED":
                    output_images = data.get("output_images", [])
                    if output_images:
                        return output_images[0]
                    else:
                        raise Exception("图片生成成功但未返回图片URL。")
                elif task_status == "FAILED":
                    raise Exception("图片生成失败。")

                # 指数退避策略
                await asyncio.sleep(delay)
                delay = min(delay * 2, max_delay)

    async def _request_image_with_fallback(self, prompt: str, size: str) -> str:
        """调用图片生成API，支持多平台和自动切换

        Args:
            prompt: 图片生成提示词
            size: 图片尺寸

        Returns:
            图片URL

        Raises:
            Exception: 当所有平台都失败时
        """
        # 获取配置的主平台和备用平台
        primary_provider = self.config.get("provider", "ms")
        backup_providers = self.config.get("backup_providers", ["openai", "aliyun"])

        # 构建平台列表（主平台优先）
        all_providers = [primary_provider] + [
            p for p in backup_providers if p != primary_provider
        ]

        logger.info(f"[绘图] 尝试平台列表: {all_providers}，主平台: {primary_provider}")

        last_error = None
        for provider in all_providers:
            try:
                logger.info(f"[绘图] 尝试使用平台: {provider}")

                if provider.lower() in ["ms", "modelscope"]:
                    # ModelScope 平台
                    if not self.api_key:
                        logger.warning(f"[绘图] {provider} 平台未配置API密钥，跳过")
                        continue
                    async with aiohttp.ClientSession() as session:
                        return await self._request_modelscope(prompt, size, session)
                elif provider.lower() == "openai":
                    # OpenAI 平台
                    openai_api_key = self.config.get("openai_api_key", "")
                    if not openai_api_key:
                        logger.warning("[绘图] OpenAI 平台未配置API密钥，跳过")
                        continue
                    return await self._request_openai_dalle(
                        prompt, size, openai_api_key
                    )
                elif provider.lower() == "aliyun":
                    # 阿里云平台
                    aliyun_api_key = self.config.get("aliyun_api_key", "")
                    if not aliyun_api_key:
                        logger.warning("[绘图] 阿里云平台未配置API密钥，跳过")
                        continue
                    return await self._request_aliyun(prompt, size, aliyun_api_key)
                else:
                    logger.warning(f"[绘图] 不支持的平台: {provider}，跳过")
                    continue

            except Exception as e:
                logger.warning(f"[绘图] {provider} 平台调用失败: {e}")
                last_error = e
                continue  # 尝试下一个平台

        # 如果所有平台都失败了
        if last_error:
            logger.error(f"[绘图] 所有绘图平台都失败了，最后错误: {last_error}")
            raise Exception(f"所有绘图平台都失败了: {last_error}")
        else:
            raise Exception("没有配置任何绘图平台")

    async def _request_openai_dalle(self, prompt: str, size: str, api_key: str) -> str:
        """调用 OpenAI DALL-E 生成图片"""
        # 将尺寸转换为 OpenAI 支持的格式
        # OpenAI DALL-E 支持 256x256, 512x512, 1024x1024
        # 将其他尺寸映射到最接近的 OpenAI 支持的尺寸
        if "256" in size:
            openai_size = "256x256"
        elif "512" in size:
            openai_size = "512x512"
        elif "1024" in size:
            openai_size = "1024x1024"
        else:
            # 默认使用 1024x1024
            openai_size = "1024x1024"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # 从配置文件读取模型名称
        openai_model = self.config.get("openai_model", "dall-e-3")

        # 构建请求数据
        payload = {
            "model": openai_model,
            "prompt": prompt,
            "n": 1,
            "size": openai_size,
        }

        openai_api_url = self.config.get("openai_api_url", "https://api.openai.com/v1")
        url = f"{openai_api_url}/images/generations"
        logger.info(f"[OpenAI DALL-E] 请求URL: {url}")
        logger.info(
            f"[OpenAI DALL-E] 请求参数: size={openai_size}, prompt={prompt[:50]}..."
        )

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                resp_text = await resp.text()
                logger.info(f"[OpenAI DALL-E] 响应状态: {resp.status}")
                logger.info(f"[OpenAI DALL-E] 响应内容: {resp_text[:1000]}...")

                if resp.status != 200:
                    logger.error(f"[OpenAI DALL-E] API调用失败: HTTP {resp.status}")
                    logger.error(f"[OpenAI DALL-E] 错误详情: {resp_text}")
                    raise Exception(
                        f"OpenAI DALL-E API调用失败: HTTP {resp.status}, {resp_text[:200]}"
                    )

                try:
                    data = json.loads(resp_text)
                except json.JSONDecodeError as e:
                    logger.error(f"[OpenAI DALL-E] 响应解析失败: {e}")
                    raise Exception(f"OpenAI DALL-E 响应解析失败: {e}")

        # 从响应中提取图片URL
        if "data" not in data or not data["data"]:
            logger.error("[OpenAI DALL-E] 未找到图片数据")
            logger.error(
                f"[OpenAI DALL-E] 完整响应数据: {json.dumps(data, ensure_ascii=False, indent=2)}"
            )
            raise Exception("OpenAI DALL-E 未返回图片数据")

        image_url = data["data"][0].get("url")
        if not image_url:
            logger.error("[OpenAI DALL-E] 未找到图片URL")
            logger.error(
                f"[OpenAI DALL-E] 完整响应数据: {json.dumps(data, ensure_ascii=False, indent=2)}"
            )
            raise Exception("OpenAI DALL-E 未返回图片 URL")

        return image_url

    async def _request_aliyun(self, prompt: str, size: str, api_key: str) -> str:
        """调用阿里云通义万相生成图片"""
        # 阿里云支持的尺寸格式，如 "1024*1024"
        # 将标准格式转换为阿里云格式
        ali_size = size.replace("x", "*")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # 从配置文件读取模型名称
        aliyun_model = self.config.get("aliyun_model", "wanx-v1")

        # 构建请求数据
        payload = {
            "model": aliyun_model,
            "input": {
                "prompt": prompt,
                "size": ali_size,
            },
            "parameters": {
                "n": 1,
            },
        }

        aliyun_api_url = self.config.get(
            "aliyun_api_url", "https://dashscope.aliyuncs.com/api/v1"
        )
        url = f"{aliyun_api_url}/services/aigc/text2image"
        logger.info(f"[阿里云通义万相] 请求URL: {url}")
        logger.info(
            f"[阿里云通义万相] 请求参数: size={ali_size}, prompt={prompt[:50]}..."
        )

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                resp_text = await resp.text()
                logger.info(f"[阿里云通义万相] 响应状态: {resp.status}")
                logger.info(f"[阿里云通义万相] 响应内容: {resp_text[:1000]}...")

                if resp.status != 200:
                    logger.error(f"[阿里云通义万相] API调用失败: HTTP {resp.status}")
                    logger.error(f"[阿里云通义万相] 错误详情: {resp_text}")
                    raise Exception(
                        f"阿里云通义万相 API调用失败: HTTP {resp.status}, {resp_text[:200]}"
                    )

                try:
                    data = json.loads(resp_text)
                except json.JSONDecodeError as e:
                    logger.error(f"[阿里云通义万相] 响应解析失败: {e}")
                    raise Exception(f"阿里云通义万相 响应解析失败: {e}")

        # 从响应中提取图片URL
        if (
            "output" not in data
            or "results" not in data["output"]
            or not data["output"]["results"]
        ):
            logger.error("[阿里云通义万相] 未找到图片数据")
            logger.error(
                f"[阿里云通义万相] 完整响应数据: {json.dumps(data, ensure_ascii=False, indent=2)}"
            )
            raise Exception("阿里云通义万相 未返回图片数据")

        image_url = data["output"]["results"][0].get("url")
        if not image_url:
            logger.error("[阿里云通义万相] 未找到图片URL")
            logger.error(
                f"[阿里云通义万相] 完整响应数据: {json.dumps(data, ensure_ascii=False, indent=2)}"
            )
            raise Exception("阿里云通义万相 未返回图片 URL")

        return image_url

    async def _request_image(self, prompt: str, size: str) -> str:
        """根据配置的提供商发起请求，返回图片URL"""
        try:
            if not prompt:
                raise ValueError("请提供提示词！")

            # 使用新的多平台支持方法
            return await self._request_image_with_fallback(prompt, size)

        except aiohttp.ClientError as e:
            raise Exception(f"网络请求失败: {str(e)}")
        except json.JSONDecodeError as e:
            raise Exception(f"解析API响应失败: {str(e)}")
        except Exception as e:
            raise e

    @filter.llm_tool(name="draw")
    async def draw(self, event: AstrMessageEvent, prompt: str, size: str = "1024x1024"):
        """根据用户请求生成图片。会先结合对话历史、角色人设、日程、天气、情绪等上下文信息，
        用LLM生成详细的绘图提示词后再生成图片。

        Args:
            prompt (str): 用户的绘图请求描述，例如"发张自拍"、"画一个风景"
            size (str): 图片尺寸，默认为1024x1024。可选项：768x1344（竖屏）、1344x768（横屏）、512x512（小方形）

        Returns:
            str: 返回给LLM的指示信息
        """

        logger.info(f"[绘图工具] 被调用 - prompt: {prompt[:50]}..., size: {size}")
        logger.info(
            f"[绘图工具] 配置状态 - llm_tool_enabled: {self.llm_tool_enabled}, api_key存在: {bool(self.api_key)}"
        )

        if not self.llm_tool_enabled:
            logger.warning("[绘图工具] 被禁用，无法生成图片")
            return "绘图工具已被禁用"

        if not self.api_key:
            logger.warning("[绘图工具] API密钥未配置，无法生成图片")
            return "API密钥未配置，无法生成图片"

        try:
            # Get emotion context for logging
            session_id = event.get_session_id()
            emotion_analysis = self.context_state.get_state(
                session_id, "emotion_analysis"
            )
            if emotion_analysis and emotion_analysis.get("emotion"):
                emotion = emotion_analysis["emotion"]
                logger.debug(f"[绘图工具] 检测到情绪: {emotion.value}")

            # Use LLM to generate context-aware drawing prompt
            logger.info("[绘图工具] 开始根据上下文生成绘图提示词（LLM增强模式）...")
            enhanced_prompt = await self._enhance_drawing_prompt(prompt, event=event)
            if enhanced_prompt and enhanced_prompt != prompt:
                logger.info(
                    f"[绘图工具] ✅ 已使用LLM生成上下文感知提示词: {enhanced_prompt[:150]}..."
                )
            else:
                logger.info(
                    f"[绘图工具] ℹ️ 使用原始提示词（未经过LLM增强）: {enhanced_prompt[:150]}..."
                )

            # Request image with enhanced prompt
            logger.info("[绘图工具] 开始请求图片生成...")
            image_url = await self._request_image(enhanced_prompt, size)
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
                f"例如：“发你了，江边风景真的很好，风也舒服。”"
            )

        except Exception as e:
            error_msg = f"生成图片时遇到问题: {str(e)}"
            logger.error(f"[绘图工具] 失败: {error_msg}")
            await event.send(event.plain_result(error_msg))
            return f"图片生成失败：{str(e)}"

    # ========== 命令处理器 ==========

    @filter.command("aiimg")
    async def generate_image_command(self, event: AstrMessageEvent):
        """命令方式生成图片"""
        full_message = event.message_obj.message_str
        parts = full_message.split(" ", 1)
        prompt = parts[1].strip() if len(parts) > 1 else ""

        if not prompt:
            yield event.plain_result("请提供提示词！使用方法：/aiimg <提示词>")
            return

        if not self.api_key:
            yield event.plain_result("API密钥未配置，无法生成图片")
            return

        try:
            image_url = await self._request_image(prompt, self.size)
            chain: list[BaseMessageComponent] = [
                Plain(f"提示词：{prompt}\n"),
                Image.fromURL(image_url),
            ]
            yield event.chain_result(chain)
        except Exception as e:
            yield event.plain_result(f"生成图片失败: {str(e)}")

    @filter.command("emotion_status")
    async def check_emotion_status(self, event: AstrMessageEvent):
        """查看当前情绪状态"""
        if not self.enable_emotion_detection:
            yield event.plain_result("情绪检测功能未启用")
            return

        session_id = event.get_session_id()
        emotion_context = self._get_emotion_context(session_id)

        recent_emotion = emotion_context.get_recent_emotion()
        trend = emotion_context.get_emotion_trend()

        if recent_emotion:
            status = f"当前情绪: {recent_emotion.value}"
            if trend:
                status += f"\n情绪趋势: {trend}"
            status += f"\n情绪历史记录数: {len(emotion_context.emotion_history)}"
        else:
            status = "暂无情绪数据"

        yield event.plain_result(status)

    @filter.command("life_story")
    async def show_life_story(self, event: AstrMessageEvent):
        """查看人生故事预览"""
        if not self.enable_life_story or not self.life_story_engine:
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

            # Engine state
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

            # Life story timeline
            if life_story_file.exists():
                with open(life_story_file, encoding="utf-8") as f:
                    story = json.load(f)
                timeline = story.get("timeline", [])
                if timeline:
                    display_parts.append("━━━━ 📜 人生经历线 ━━━━\n")
                    for ch in timeline[-5:]:  # Show last 5 chapters
                        chapter = ch.get("chapter", "?")
                        content = ch.get("content", "")
                        time_str = ch.get("time", "")[:10]
                        # Truncate long content for display
                        if len(content) > 200:
                            content = content[:200] + "..."
                        display_parts.append(
                            f"📕 第{chapter}章 ({time_str})\n{content}\n"
                        )
                else:
                    display_parts.append("📜 人生故事尚未生成\n")
            else:
                display_parts.append("📜 人生故事尚未生成\n")

            # Context cache
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
        """查看人格演化状态"""
        if not self.enable_async_thinking or not self.personality_evolution:
            yield event.plain_result("人格演化系统未启用")
            return

        try:
            summary = self.personality_evolution.get_personality_summary()

            # 将阶段名称移出 f-string 表达式
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
        """查看经历银行状态"""
        if not self.enable_async_thinking or not self.experience_bank:
            yield event.plain_result("经历银行未启用（需启用异步思考系统）")
            return

        try:
            parts = ["🏦 经历银行状态\n"]

            # Growth summary
            growth_summary = self.experience_bank.get_growth_summary()
            if growth_summary:
                # Skills
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

                # Interests
                interests = growth_summary.get("interests", [])
                if interests:
                    interest_names = [
                        i.get("item", str(i)) if isinstance(i, dict) else str(i)
                        for i in interests[:8]
                    ]
                    parts.append(f"🎯 兴趣: {', '.join(interest_names)}")

                # Views
                views = growth_summary.get("views", [])
                if views:
                    view_names = [
                        v.get("view", str(v)) if isinstance(v, dict) else str(v)
                        for v in views[:5]
                    ]
                    parts.append(f"💭 观点: {', '.join(view_names)}")

            # Conversation count
            conv_file = self.experience_bank.conversations_file
            if conv_file.exists():
                line_count = sum(
                    1 for line in open(conv_file, encoding="utf-8") if line.strip()
                )
                parts.append(f"\n📝 对话记录数: {line_count}")

            # Event count
            evt_file = self.experience_bank.events_file
            if evt_file.exists():
                evt_count = sum(
                    1 for line in open(evt_file, encoding="utf-8") if line.strip()
                )
                parts.append(f"📋 事件记录数: {evt_count}")

            # Relationships
            rel_file = self.experience_bank.relationships_file
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

    # ========== QQ空间相关命令（仅在启用时可用）==========

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("发说说")
    async def publish_feed(self, event: AiocqhttpMessageEvent):
        """发说说 <内容> <图片>, 由用户指定内容"""
        if not self.enable_qzone:
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

        # 检查模块是否初始化完成
        if not hasattr(self, "operator"):
            await event.send(event.plain_result("QQ空间模块初始化中，请稍后重试"))
            logger.warning(
                f"[发说说] 命令被调用，但QQ空间模块尚未初始化完成 - operator={'MISSING' if not hasattr(self, 'operator') else 'OK'}, llm={'MISSING' if not hasattr(self, 'llm') else 'OK'}"
            )
            return

        # 检查样式是否加载
        if not self.style:
            await event.send(
                event.plain_result(
                    "pillowmd样式未加载，无法生成说说图片。请检查 pillowmd 是否正确安装以及 default_style 目录是否存在"
                )
            )
            return

        from .core.utils import get_image_urls

        text = event.message_str.partition(" ")[2]
        images = await get_image_urls(event)

        # 直接发布说说，不保存草稿
        await self.operator.publish_feed(event=event, text=text, images=images)

    @filter.command("写说说", alias={"写稿", "写草稿"})
    async def write_draft(self, event: AiocqhttpMessageEvent, topic: str | None = None):
        """写说说 <主题> <图片>, 由AI生成说说内容并自动配图"""
        if not self.enable_qzone:
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

        # 检查模块是否初始化完成
        if not hasattr(self, "llm") or not hasattr(self, "operator"):
            await event.send(event.plain_result("QQ空间模块初始化中，请稍后重试"))
            logger.warning(
                f"[写说说] 命令被调用，但QQ空间模块尚未初始化完成 - operator={'MISSING' if not hasattr(self, 'operator') else 'OK'}, llm={'MISSING' if not hasattr(self, 'llm') else 'OK'}"
            )
            return

        from .core.utils import get_image_urls

        # 获取人设（优先使用插件配置，其次系统人设）
        persona_profile = await self._get_persona_profile()

        # 使用LLM生成说说内容
        text = await self.llm.generate_diary(
            group_id=event.get_group_id(), topic=topic, persona_profile=persona_profile
        )

        # 检查是否生成成功
        if not text:
            await event.send(
                event.plain_result("生成说说内容失败，请检查LLM配置或重试")
            )
            logger.error("[写说说] generate_diary 返回空内容")
            return

        logger.info(f"[写说说] 生成的说说内容: {text}")

        # 获取用户上传的图片
        images = await get_image_urls(event)

        # 如果没有图片，自动生成配图（使用多平台 fallback）
        if not images:
            logger.info("[写说说] 没有上传图片，尝试自动生成配图...")
            try:
                # 获取配置的user_id和group_id
                user_id = self.config.get("diary_user_id", "")
                group_id = event.get_group_id() or ""
                logger.info(f"[写说说] 配置的user_id: {user_id}, group_id: {group_id}")

                # 生成图片提示词，传入user_id和group_id
                image_prompt = await self.llm.generate_image_prompt_from_diary(
                    text, group_id=group_id, user_id=user_id
                )
                if image_prompt:
                    logger.info(f"[写说说] 生成的配图提示词: {image_prompt}")
                    # 使用多平台 fallback 生图（ModelScope/OpenAI/阿里云）
                    image_url = await self.llm._request_image_with_fallback(
                        image_prompt
                    )
                    if image_url:
                        images = [image_url]
                        logger.info(f"[写说说] 配图生成成功: {image_url}")
                    else:
                        logger.warning("[写说说] 配图生成失败，所有平台均未返回图片URL")
                else:
                    logger.warning("[写说说] 无法生成图片提示词")
            except Exception as e:
                logger.error(f"[写说说] 自动配图失败: {e}", exc_info=True)
        else:
            logger.info(f"[写说说] 使用用户上传的图片: {len(images)}张")

        # 直接发布，不保存草稿
        await self.operator.publish_feed(event, text, images, publish=True)

    # ==========  工具调用解析 ==========

    @staticmethod
    def parse_tool_call(text: str) -> dict | None:
        """
        解析 MiniMax 工具调用格式

        示例格式:
        <minimax:tool_call>
        invoke name="draw"
        <prompt>描述</prompt>
        <parameter name="size">1024x1024</parameter>
        </invoke>
        </minimax:tool_call>

        Returns:
            字典: {"tool_name": "draw", "prompt": "...", "size": "..."} 或 None
        """
        if "<minimax:tool_call>" not in text:
            return None

        try:
            import re

            # 提取工具名称
            tool_match = re.search(r'invoke name="([^"]+)"', text)
            if not tool_match:
                logger.debug("[工具调用] 未找到工具名称")
                return None

            tool_name = tool_match.group(1)
            logger.debug(f"[工具调用] 解析到工具名称: {tool_name}")

            # 提取prompt（使用 re.DOTALL 匹配换行符）
            # 先尝试正常格式
            prompt_match = re.search(r"<prompt>\s*(.+?)\s*</prompt>", text, re.DOTALL)
            if prompt_match:
                prompt = prompt_match.group(1).strip()
                logger.debug(f"[工具调用] 解析到prompt (正常格式): {prompt[:100]}...")
            else:
                # MiniMax有时会错误地使用 </parameter> 而不是 </prompt>
                # 格式: <prompt>...内容...</parameter>
                alt_match = re.search(
                    r"<prompt>\s*(.+?)\s*</parameter>", text, re.DOTALL
                )
                if alt_match:
                    # 提取内容，但需要移除后续的 <parameter 标签
                    full_content = alt_match.group(1)
                    # 分离出真正的prompt和可能混入的parameter标签
                    param_tag_match = re.search(
                        r"^(.+?)(?=<parameter)", full_content, re.DOTALL
                    )
                    if param_tag_match:
                        prompt = param_tag_match.group(1).strip()
                    else:
                        prompt = full_content.strip()
                    logger.debug(
                        f"[工具调用] 解析到prompt (替代格式): {prompt[:100]}..."
                    )
                else:
                    prompt = ""
                    logger.warning("[工具调用] 未找到prompt内容")

            # 提取参数
            params = {"prompt": prompt}
            param_matches = re.findall(
                r'<parameter name="([^"]+)">([^<]+)</parameter>', text
            )
            for param_name, param_value in param_matches:
                params[param_name] = param_value.strip()
                logger.debug(
                    f"[工具调用] 解析到参数 {param_name}: {param_value.strip()}"
                )

            return {"tool_name": tool_name, **params}
        except Exception as e:
            logger.error(f"[工具调用] 解析失败: {e}")
            return None

    async def _enhance_drawing_prompt(
        self, original_prompt: str, event: AstrMessageEvent | None = None
    ) -> str:
        """
        使用 LLM 根据上下文（人设、日程、天气、情绪、对话历史等）生成详细的绘图提示词。

        优先使用 LLM 生成，若 LLM 不可用则回退到关键词拼接方式。

        Args:
            original_prompt: 原始绘图请求（来自 draw 工具参数）
            event: 当前事件（用于获取会话上下文）

        Returns:
            LLM 生成的详细绘图提示词
        """
        try:
            now = datetime.now()

            # ============ 1. 收集所有上下文信息 ============

            # 人设
            persona_profile = await self._get_persona_profile()
            if not persona_profile:
                persona_profile = await self._get_system_persona_profile()

            # 日程与穿搭
            schedule_text = await self._maybe_generate_schedule(now)
            outfit = ""
            if schedule_text:
                for line in schedule_text.split("\n"):
                    line_clean = line.strip().lstrip("0123456789.、·-").strip()
                    line_clean = line_clean.replace("**", "").replace("*", "").strip()
                    if "穿搭" in line_clean or "穿着" in line_clean:
                        # Extract the actual outfit description
                        for prefix in (
                            "今日穿搭：",
                            "穿搭：",
                            "穿着：",
                            "今日穿搭:",
                            "穿搭:",
                            "穿着:",
                        ):
                            if prefix in line_clean:
                                outfit = line_clean.split(prefix, 1)[1].strip()
                                break
                        if not outfit and (
                            "穿搭" in line_clean or "穿着" in line_clean
                        ):
                            # Try to get text after colon or other separator
                            for sep in ("：", ":", "，"):
                                if sep in line_clean:
                                    outfit = line_clean.split(sep, 1)[1].strip()
                                    break
                        if outfit:
                            break

            # 天气 - parse raw weather data into clean description
            raw_weather = await self._get_weather_desc()
            weather_desc = self._parse_weather_for_drawing(raw_weather)

            # 情绪
            emotion_desc = ""
            if event:
                try:
                    session_id = event.get_session_id()
                    emotion_analysis = self.context_state.get_state(
                        session_id, "emotion_analysis"
                    )
                    if emotion_analysis and emotion_analysis.get("emotion"):
                        em = emotion_analysis["emotion"]
                        emotion_desc = (
                            str(em.value) if hasattr(em, "value") else str(em)
                        )
                except Exception:
                    pass

            # 最近对话
            recent_conv = ""
            try:
                if self.experience_bank:
                    convs = self.experience_bank.get_recent_conversations(limit=5)
                    if convs:
                        conv_items = []
                        for c in convs[-3:]:
                            user_msg = c.get("user_message", "")[:80]
                            if user_msg:
                                conv_items.append(f"用户: {user_msg}")
                        if conv_items:
                            recent_conv = "；".join(conv_items)
            except Exception as e:
                logger.debug(f"[绘图提示词生成] 获取最近对话失败: {e}")

            # 历史绘画（避免重复）
            drawing_history = ""
            try:
                recent_prompts = self.local_data_manager.get_recent_drawing_prompts(
                    days=2, max_count=3
                )
                if recent_prompts:
                    history_items = [
                        item.get("original_prompt", "")[:50]
                        for item in recent_prompts
                        if item.get("original_prompt")
                    ]
                    if history_items:
                        drawing_history = "；".join(history_items)
            except Exception as e:
                logger.debug(f"[绘图提示词生成] 获取历史绘画失败: {e}")

            # 时间
            hour = now.hour
            if 5 <= hour < 8:
                time_desc = "清晨"
            elif 8 <= hour < 12:
                time_desc = "上午"
            elif 12 <= hour < 14:
                time_desc = "中午"
            elif 14 <= hour < 18:
                time_desc = "下午"
            elif 18 <= hour < 20:
                time_desc = "傍晚"
            elif 20 <= hour < 22:
                time_desc = "夜晚"
            else:
                time_desc = "深夜"

            # 禁止规则
            forbidden_rules = self.config.get("image_forbidden_rules", "").strip()

            # 当前时段日程
            current_schedule = self._get_current_period_schedule(schedule_text, now)

            # ============ 2. 使用 LLM 生成详细提示词 ============

            provider_id = self._get_provider_id()
            if provider_id and self.context and hasattr(self.context, "llm_generate"):
                logger.info(
                    "[绘图提示词生成] ✅ LLM可用，使用LLM生成上下文感知提示词..."
                )
                meta_prompt = (
                    f"你是一个专业的AI绘图提示词生成器。根据以下上下文信息，将用户的绘图请求转化为一段详细的、"
                    f"适合AI图片生成模型的英文提示词。\n\n"
                    f"## 用户绘图请求\n{original_prompt}\n\n"
                    f"## 角色人设\n{persona_profile[:500] if persona_profile else '未配置'}\n\n"
                    f"## 今日穿搭\n{outfit if outfit else '未指定'}\n\n"
                    f"## 当前时段活动\n{current_schedule if current_schedule else '无'}\n\n"
                    f"## 天气情况\n{weather_desc if weather_desc else '未知'}\n\n"
                    f"## 当前时间\n{time_desc}\n\n"
                    f"## 情绪状态\n{emotion_desc if emotion_desc else '未知'}\n\n"
                    f"## 最近对话\n{recent_conv if recent_conv else '无'}\n\n"
                    f"## 历史绘画（避免重复）\n{drawing_history if drawing_history else '无'}\n\n"
                    f"## 禁止规则\n{forbidden_rules if forbidden_rules else '无'}\n\n"
                    f"## 要求\n"
                    f"1. 提示词必须是英文\n"
                    f"2. 必须包含人物外貌、穿搭、场景、时间、光线、风格等细节\n"
                    f"3. 确保人物形象与人设一致\n"
                    f"4. 穿搭信息要与今日穿搭匹配\n"
                    f"5. 场景氛围要与天气和时间一致\n"
                    f"6. 结合当前时段活动描述场景\n"
                    f"7. 严格遵守所有禁止规则\n"
                    f"8. 避免与历史绘画重复\n"
                    f"9. 只输出提示词本身，不要有任何解释或前缀\n\n"
                    f"英文提示词："
                )

                try:
                    resp = await self.context.llm_generate(
                        chat_provider_id=provider_id,
                        prompt=meta_prompt,
                    )
                    generated = (resp.completion_text or "").strip()
                    if generated:
                        # Clean up possible markdown formatting
                        generated = generated.strip("`").strip()
                        for prefix in (
                            "Prompt:",
                            "prompt:",
                            "PROMPT:",
                            "English prompt:",
                        ):
                            if generated.startswith(prefix):
                                generated = generated[len(prefix) :].strip()
                        logger.info(
                            f"[绘图提示词生成] ✅ LLM成功生成提示词: {generated[:100]}..."
                        )
                        # Save
                        try:
                            self.local_data_manager.save_drawing_prompt(
                                original_prompt, generated
                            )
                        except Exception as e:
                            logger.debug(f"[绘图提示词生成] 保存失败: {e}")
                        return generated
                    else:
                        logger.warning("[绘图提示词生成] LLM返回空结果，回退到拼接方式")
                except Exception as e:
                    logger.warning(f"[绘图提示词生成] LLM生成失败，回退到拼接方式: {e}")

            # ============ 3. 回退：关键词拼接方式 ============
            logger.info(
                "[绘图提示词生成] ⚠️ LLM不可用或未配置provider，使用关键词拼接方式生成提示词"
            )
            return self._build_drawing_prompt_fallback(
                original_prompt,
                persona_profile=persona_profile,
                outfit=outfit,
                weather_desc=weather_desc,
                time_desc=time_desc,
                forbidden_rules=forbidden_rules,
                conversation_context=recent_conv,
                drawing_history=drawing_history,
            )

        except Exception as e:
            logger.error(f"[绘图提示词生成] 失败: {e}", exc_info=True)
            return original_prompt

    def _build_drawing_prompt_fallback(
        self,
        original_prompt: str,
        persona_profile: str = "",
        outfit: str = "",
        weather_desc: str = "",
        time_desc: str = "",
        forbidden_rules: str = "",
        conversation_context: str = "",
        drawing_history: str = "",
    ) -> str:
        """关键词拼接方式生成绘图提示词（LLM 不可用时的回退方案）"""
        enhanced_parts = [f"画面内容：{original_prompt}"]

        if persona_profile:
            age_match = re.search(r"(\d+)岁", persona_profile)
            gender_hints = []
            if "女" in persona_profile or "她" in persona_profile:
                gender_hints.append("女性")
            elif "男" in persona_profile or "他" in persona_profile:
                gender_hints.append("男性")
            appearance_desc = ""
            if age_match:
                appearance_desc += f"{age_match.group(1)}岁"
            if gender_hints:
                appearance_desc += gender_hints[0]
            if appearance_desc:
                enhanced_parts.append(f"人物：{appearance_desc}")

        if outfit:
            enhanced_parts.append(f"穿着：{outfit}")
        if weather_desc:
            enhanced_parts.append(f"天气：{weather_desc}")

        time_light_map = {
            "清晨": "清晨，柔和的晨光",
            "上午": "上午，明亮的日光",
            "中午": "中午，强烈的阳光",
            "下午": "下午，温暖的光线",
            "傍晚": "傍晚，金色的夕阳",
            "夜晚": "夜晚，柔和的灯光",
            "深夜": "深夜，昏暗的光线",
        }
        enhanced_parts.append(
            f"时间：{time_light_map.get(time_desc, '白天，自然光线')}"
        )

        style_desc = "风格：真实摄影风格，自然光线，高清细节"
        if forbidden_rules:
            style_desc += "。" + forbidden_rules
        enhanced_parts.append(style_desc)

        if conversation_context:
            enhanced_parts.append(f"背景：{conversation_context}")
        if drawing_history:
            enhanced_parts.append(f"参考：{drawing_history}")

        enhanced_prompt = "，".join(enhanced_parts)
        logger.info(f"[绘图提示词回退] 拼接: {enhanced_prompt[:100]}...")
        return enhanced_prompt

    async def execute_tool_call(self, tool_name: str, params: dict) -> str | None:
        """
        执行工具调用

        Args:
            tool_name: 工具名称
            params: 参数字典

        Returns:
            图片URL 或 None
        """
        if tool_name == "draw":
            original_prompt = params.get("prompt", "")
            if not original_prompt:
                logger.warning("[工具调用] draw 工具缺少 prompt 参数")
                return None

            # 检查 LLM 是否初始化
            if not hasattr(self, "llm") or not self.llm:
                logger.warning("[工具调用] LLM 未初始化，无法调用绘图")
                return None

            # 检查 API Key
            if not self.llm.ms_api_key:
                logger.warning("[工具调用] 未配置 ModelScope API Key")
                return None

            try:
                # 增强绘画提示词，结合人设、历史对话、日程和天气
                enhanced_prompt = await self._enhance_drawing_prompt(
                    original_prompt, event=self._current_event
                )

                # 从配置文件获取图片尺寸，如果 LLM 没有指定的话
                size = params.get("size", self.config.get("size", "1024x1024"))
                logger.info(f"[工具调用] 开始执行 draw (尺寸: {size})")
                logger.info(f"[工具调用] 原始提示词: {original_prompt[:100]}...")
                logger.info(f"[工具调用] 增强提示词: {enhanced_prompt[:100]}...")

                # 调用 ModelScope API
                image_url = await self.llm._request_modelscope(
                    enhanced_prompt, size=size
                )
                if image_url:
                    logger.info(f"[工具调用] 绘图成功: {image_url}")
                    return image_url
                else:
                    logger.warning("[工具调用] ModelScope 未返回图片 URL")
                    return None
            except Exception as e:
                logger.error(f"[工具调用] 执行 draw 失败: {e}")
                return None
        else:
            logger.warning(f"[工具调用] 未知的工具: {tool_name}")
            return None

    @filter.on_llm_response()
    async def on_llm_response_handler(self, event: AstrMessageEvent, resp: LLMResponse):
        """拦截LLM响应，检测并执行工具调用，以及检测未调用的图像生成内容"""
        text = resp.completion_text or ""
        if not text:
            return resp

        # 记录AI回复到经历银行（补全之前的空bot_response）
        if self.enable_async_thinking and self.experience_bank:
            try:
                session_id = event.get_session_id()
                self.experience_bank.update_last_bot_response(session_id, text[:500])
            except Exception as e:
                logger.debug(f"[经历银行] 记录AI回复失败: {e}")

        # 检测是否包含工具调用
        tool_call = self.parse_tool_call(text)
        if tool_call:
            logger.info(f"[工具调用] 检测到工具调用: {tool_call}")

            # 执行工具
            tool_name = tool_call.pop("tool_name")
            result = await self.execute_tool_call(tool_name, tool_call)

            if result:
                # 成功执行，返回图片URL代替工具调用格式
                logger.info("[工具调用] 已将工具调用格式替换为图片URL")
                # 返回图片markdown格式
                return f"![image]({result})"
            else:
                # 执行失败，返回提示信息
                return "抱歉，图片生成失败了😥"

        # 检测LLM是否生成了图像生成的JSON格式但没有调用绘图工具
        image_gen_detected = await self._detect_and_handle_image_generation(text, event)
        if image_gen_detected:
            # 如果检测到图像生成并已处理，则返回原始文本
            return resp

        return resp

    async def _detect_and_handle_image_generation(
        self, text: str, event: AstrMessageEvent
    ) -> bool:
        """
        检测LLM响应中的图像生成内容，并在没有实际调用绘图工具时自动调用绘图工具

        Args:
            text: LLM响应文本
            event: 消息事件

        Returns:
            bool: 是否检测到并处理了图像生成内容
        """
        # 检查是否启用了图像生成检测功能
        if not self.enable_image_generation_detection:
            logger.debug("[图像生成检测] 图像生成检测功能已禁用，跳过检测")
            return False

        logger.info(f"[图像生成检测] 检测响应文本: {text[:200]}...")

        # 检查文本中是否包含图像生成的JSON格式
        # 匹配包含generate_image或类似关键词的JSON结构
        json_pattern = r"(\{[^{}]*(?:generate_image|image|draw|picture|photo|绘画|图片|照片|绘图)[^{}]*\})"
        matches = re.findall(json_pattern, text, re.IGNORECASE | re.DOTALL)

        logger.info(f"[图像生成检测] 找到 {len(matches)} 个JSON匹配项")

        for match in matches:
            try:
                # 尝试解析JSON
                json_obj = json.loads(match)

                logger.info(f"[图像生成检测] 解析JSON: {json_obj}")

                # 检查是否包含图像生成相关的action或function
                if isinstance(json_obj, dict):
                    action = json_obj.get("action", "").lower()
                    logger.info(f"[图像生成检测] 检查动作: {action}")
                    if (
                        "generate_image" in action
                        or "image" in action
                        or "draw" in action
                    ):
                        logger.info(f"[图像生成检测] 检测到图像生成JSON: {json_obj}")

                        # 提取提示词
                        action_input = json_obj.get("action_input", "")
                        if action_input:
                            # 如果action_input是字符串，尝试解析为JSON
                            if isinstance(action_input, str):
                                try:
                                    input_obj = json.loads(action_input)
                                    prompt = input_obj.get(
                                        "prompt", input_obj.get("description", "")
                                    )
                                    size = input_obj.get(
                                        "aspect_ratio",
                                        input_obj.get("size", "1024x1024"),
                                    )
                                except json.JSONDecodeError:
                                    # 如果action_input不是JSON，直接作为提示词处理
                                    prompt = action_input
                                    size = "1024x1024"
                            else:
                                prompt = action_input.get(
                                    "prompt", action_input.get("description", "")
                                )
                                size = action_input.get(
                                    "aspect_ratio",
                                    action_input.get("size", "1024x1024"),
                                )
                        else:
                            # 如果没有action_input，尝试从JSON对象中直接提取
                            prompt = json_obj.get(
                                "prompt", json_obj.get("description", "")
                            )
                            size = json_obj.get(
                                "aspect_ratio", json_obj.get("size", "1024x1024")
                            )

                        if prompt:
                            logger.info(
                                f"[图像生成检测] 提取到提示词: {prompt[:100]}..."
                            )

                            # 检查是否已经调用了绘图工具（避免重复调用）
                            # 这里我们直接调用绘图工具
                            try:
                                # 调用绘图工具
                                result = await self.draw(event, prompt, size)

                                # 如果成功，记录日志
                                if (
                                    result
                                    and "失败" not in result
                                    and "错误" not in result
                                ):
                                    logger.info("[图像生成检测] 自动调用绘图工具成功")
                                    return True
                                else:
                                    logger.warning(
                                        f"[图像生成检测] 自动调用绘图工具失败: {result}"
                                    )
                            except Exception as e:
                                logger.error(
                                    f"[图像生成检测] 自动调用绘图工具时出错: {e}",
                                    exc_info=True,
                                )

            except json.JSONDecodeError:
                # 如果不是有效的JSON，继续检查下一个匹配项
                logger.warning(f"[图像生成检测] JSON解析失败: {match[:100]}...")
                continue

        # 检查是否有非JSON格式的图像生成提示词
        # 检查是否包含提示词关键词但没有实际调用绘图工具
        image_keywords = [
            "生成图片",
            "画一张",
            "画个",
            "画一幅",
            "制作图片",
            "绘图",
            "生成图像",
            "画出来",
            "图片生成",
            "图像生成",
        ]
        for keyword in image_keywords:
            if keyword in text:
                logger.info(f"[图像生成检测] 检测到图像生成关键词: {keyword}")

                # 尝试提取提示词内容
                # 使用正则表达式提取关键词后的描述
                prompt_pattern = f"{re.escape(keyword)}[：:：:]?\\s*([^。！？\n]+)"
                prompt_match = re.search(prompt_pattern, text, re.DOTALL)
                if prompt_match:
                    prompt = prompt_match.group(1).strip()
                    if prompt:
                        logger.info(
                            f"[图像生成检测] 提取到非JSON格式提示词: {prompt[:100]}..."
                        )

                        try:
                            # 调用绘图工具
                            result = await self.draw(event, prompt, "1024x1024")

                            # 如果成功，记录日志
                            if result and "失败" not in result and "错误" not in result:
                                logger.info("[图像生成检测] 自动调用绘图工具成功")
                                return True
                            else:
                                logger.warning(
                                    f"[图像生成检测] 自动调用绘图工具失败: {result}"
                                )
                        except Exception as e:
                            logger.error(
                                f"[图像生成检测] 自动调用绘图工具时出错: {e}",
                                exc_info=True,
                            )

        # 额外检测您提到的格式：{ "action": "generate_image", "action_input": "..." }
        # 检测多行JSON格式
        multiline_json_pattern = (
            r'\{\s*\["\']action\["\']\s*:\s*\["\']generate_image\["\'].*?\}'
        )
        multiline_matches = re.findall(
            multiline_json_pattern, text, re.IGNORECASE | re.DOTALL
        )

        logger.info(f"[图像生成检测] 找到 {len(multiline_matches)} 个多行JSON匹配项")

        for match in multiline_matches:
            try:
                json_obj = json.loads(match)
                logger.info(f"[图像生成检测] 解析多行JSON: {json_obj}")

                if isinstance(json_obj, dict):
                    action = json_obj.get("action", "").lower()
                    if "generate_image" in action:
                        action_input = json_obj.get("action_input", "")
                        if isinstance(action_input, str):
                            try:
                                input_obj = json.loads(action_input)
                                prompt = input_obj.get(
                                    "prompt", input_obj.get("description", "")
                                )
                                size = input_obj.get(
                                    "aspect_ratio", input_obj.get("size", "1024x1024")
                                )
                            except json.JSONDecodeError:
                                prompt = action_input
                                size = "1024x1024"
                        else:
                            prompt = action_input.get(
                                "prompt", action_input.get("description", "")
                            )
                            size = action_input.get(
                                "aspect_ratio", action_input.get("size", "1024x1024")
                            )

                        if prompt:
                            logger.info(
                                f"[图像生成检测] 从多行JSON提取到提示词: {prompt[:100]}..."
                            )
                            try:
                                result = await self.draw(event, prompt, size)
                                if (
                                    result
                                    and "失败" not in result
                                    and "错误" not in result
                                ):
                                    logger.info("[图像生成检测] 自动调用绘图工具成功")
                                    return True
                                else:
                                    logger.warning(
                                        f"[图像生成检测] 自动调用绘图工具失败: {result}"
                                    )
                            except Exception as e:
                                logger.error(
                                    f"[图像生成检测] 自动调用绘图工具时出错: {e}",
                                    exc_info=True,
                                )
            except json.JSONDecodeError:
                logger.warning(f"[图像生成检测] 多行JSON解析失败: {match[:100]}...")
                continue

        return False

    # 原有的on_llm_response_handler方法已经存在，我们不需要重复定义
