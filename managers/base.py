import asyncio
from pathlib import Path

import aiohttp

from astrbot.api import logger
from astrbot.api.star import Context, StarTools

try:
    from astrbot.core.config.default import VERSION
    from astrbot.core.utils.version_comparator import VersionComparator

    _CORE_INTROSPECTION_AVAILABLE = True
except ImportError:
    _CORE_INTROSPECTION_AVAILABLE = False

from ..context_events import ContextState, EventTrigger, ProactiveMessageManager
from ..core.async_thinking_scheduler import AsyncThinkingScheduler
from ..core.auto_profile_updater import AutoProfileUpdater
from ..core.experience_bank import ExperienceBank
from ..core.life_story_engine import LifeStoryEngine
from ..core.local_data_manager import LocalDataManager
from ..core.memory_manager import MemoryManager
from ..core.news_getter import NewsGetter
from ..core.personality_evolution import PersonalityEvolutionManager
from ..core.psychology_engine import PsychologyEngine
from ..core.thought_engine import ThoughtEngine
from ..core.timeline_verifier import TimelineVerifier
from ..emotions import EmotionContext


class SharedState:
    """Shared state object passed to all managers.

    Provides access to config, context, sub-modules, and caches
    that were previously accessed via `self` on the Main class.
    """

    def __init__(self, context: Context, config: dict):
        self.context = context
        self.config = config

        # Version check (graceful degradation if core internals unavailable)
        if _CORE_INTROSPECTION_AVAILABLE:
            if not VersionComparator.compare_version(VERSION, "4.1.0") >= 0:
                raise Exception("AstrBot 版本过低, 请升级至 4.1.0 或更高版本")
        else:
            logger.warning(
                "[版本检查] 无法导入 astrbot.core 版本信息，跳过版本检查。"
                "如果遇到兼容性问题，请升级 AstrBot 至 4.1.0+"
            )

        # ========== AI drawing config ==========
        self.api_key = config.get("api_key")
        self.model = config.get("ms_model", "Qwen/Qwen-Image")
        self.size = config.get("size", "1024x1024")
        self.api_url = config.get("api_url", "https://api-inference.modelscope.cn/")
        self.provider = config.get("provider", "ms")

        # ========== Image generation detection config ==========
        self.enable_image_generation_detection = config.get(
            "enable_image_generation_detection", True
        )

        # ========== Emotion & events config ==========
        self.enable_emotion_detection = config.get("enable_emotion_detection", True)
        self.enable_auto_selfie = config.get("enable_auto_selfie", False)
        self.selfie_trigger_chance = config.get("selfie_trigger_chance", 0.3)
        self.enable_proactive_messages = config.get("enable_proactive_messages", False)
        self.idle_greeting_delay = config.get("idle_greeting_delay", 600)
        self.enable_proactive_sharing = config.get("enable_proactive_sharing", False)
        self.proactive_share_interval_minutes = config.get(
            "proactive_share_interval_minutes", 120
        )
        self.proactive_share_time_ranges = config.get(
            "proactive_share_time_ranges", "9-12,14-18,19-22"
        )
        self.enable_context_events = config.get("enable_context_events", True)
        self.llm_tool_enabled = config.get("llm_tool_enabled", True)

        # ========== Life simulation & persona config ==========
        self.enable_life_simulation = config.get("enable_life_simulation", True)
        self.persona_name = config.get("persona_name", "她")
        self.persona_profile = config.get("persona_profile", "")
        self.schedule_hour = config.get("schedule_hour", 7)
        self.news_hour = config.get("news_hour", 7)
        self.weather_location = config.get("weather_location", "")
        self.news_topics = config.get(
            "news_topics", ["科技", "生活方式", "兴趣相关话题"]
        )
        self.schedule_prompt = config.get("schedule_prompt", "")
        self.news_prompt = config.get("news_prompt", "")

        # ========== Qzone config ==========
        self.enable_qzone = config.get("enable_qzone", False)
        self.publish_times_per_day = config.get("publish_times_per_day", 3)
        self.publish_time_ranges = config.get("publish_time_ranges", [])
        self.insomnia_probability = config.get("insomnia_probability", 0.2)

        # ========== Auto profile update config ==========
        self.enable_auto_profile_update = config.get(
            "enable_auto_profile_update", False
        )
        self.enable_auto_nickname = config.get("enable_auto_nickname", False)
        self.enable_auto_signature = config.get("enable_auto_signature", True)
        self.enable_auto_avatar = config.get("enable_auto_avatar", False)
        self.enable_auto_tag = config.get("enable_auto_tag", False)
        self.profile_update_cooldown = config.get("profile_update_cooldown", 1800)
        self.emotion_change_threshold = config.get("emotion_change_threshold", 0.6)
        self.enable_profile_update_from_thinking = config.get(
            "enable_profile_update_from_thinking", False
        )
        self.profile_update_max_per_day = config.get("profile_update_max_per_day", 3)
        self.profile_update_max_per_week = config.get("profile_update_max_per_week", 10)
        self.avatar_max_per_day = config.get("avatar_max_per_day", 1)

        # ========== Life story engine config ==========
        self.enable_life_story = config.get("enable_life_story", True)
        self.life_story_update_interval = config.get("life_story_update_interval", 3)
        self.life_story_collect_days = config.get("life_story_collect_days", 7)
        self.life_story_context_max_length = config.get(
            "life_story_context_max_length", 200
        )
        self.life_story_cache_days = config.get("life_story_cache_days", 7)

        # ========== News getter config ==========
        self.enable_news_getter = config.get("enable_news_getter", True)
        self.news_online_fetch = config.get("news_online_fetch", True)

        # ========== Async thinking config ==========
        self.enable_async_thinking = config.get("enable_async_thinking", True)
        self.async_think_provider_id = config.get("async_think_provider_id", "")
        self.think_interval_minutes = config.get("think_interval_minutes", 20)
        self.activity_interval_minutes = config.get("activity_interval_minutes", 25)

        # ========== State management ==========
        # These mutable fields are shared across managers and may be
        # accessed concurrently from different async tasks.  Locks are
        # provided for safe read-modify-write operations.
        self._emotion_lock = asyncio.Lock()
        self._favorability_lock = asyncio.Lock()
        self._tasks_lock = asyncio.Lock()
        self._events_lock = asyncio.Lock()
        self._life_state_lock = asyncio.Lock()

        self.emotion_contexts: dict[str, EmotionContext] = {}
        self.event_trigger = EventTrigger()
        self.proactive_manager = ProactiveMessageManager()
        self.context_state = ContextState()
        self.life_state: dict[str, dict] = {}
        self.favorability: dict[str, float] = {}

        # Caches
        self._weather_cache = {"data": "", "timestamp": 0}
        self._news_cache = {"data": "", "date": ""}
        self._schedule_cache = {"data": "", "date": ""}
        self.today_schedule_display: str = ""

        # Current event & cached bot
        self._current_events: dict = {}  # session_id -> event, per-session
        self._qzone_initialized: bool = False
        self._cached_bot = None
        self._background_tasks: set = set()
        # Shared aiohttp session for HTTP requests (weather, news, image APIs)
        self._http_session: aiohttp.ClientSession | None = None

        # ========== Sub-module instances ==========
        self.local_data_manager: LocalDataManager | None = None
        self.thought_engine: ThoughtEngine | None = None
        self.experience_bank: ExperienceBank | None = None
        self.async_thinking_scheduler: AsyncThinkingScheduler | None = None
        self.psychology_engine: PsychologyEngine | None = None
        self.memory_manager: MemoryManager | None = None
        self.timeline_verifier: TimelineVerifier | None = None
        self.personality_evolution: PersonalityEvolutionManager | None = None
        self.auto_profile_updater: AutoProfileUpdater | None = None
        self.life_story_engine: LifeStoryEngine | None = None
        self.news_getter: NewsGetter | None = None

        # Qzone related
        self.style = None
        self.pillowmd_style_dir: Path | None = None
        self.cache: Path | None = None
        self.qzone = None
        self.llm = None
        self.operator = None
        self.post_db = None
        self.auto_publish = None
        self._proactive_share_scheduler = None
        self._comment_check_scheduler = None
        self._loneliness_scheduler = None

    def initialize_sub_modules(self):
        """Initialize all sub-modules (called from Main.__init__ after SharedState creation)."""
        # Local data manager
        data_dir = (
            StarTools.get_data_dir("astrbot_plugin_realistic_persona") / "local_data"
        )
        self.local_data_manager = LocalDataManager(data_dir)

        # Auto profile updater
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
                enable_tag=self.enable_auto_tag,
                cooldown=self.profile_update_cooldown,
                threshold=self.emotion_change_threshold,
                persona_name=self.persona_name,
                max_updates_per_day=self.profile_update_max_per_day,
                max_updates_per_week=self.profile_update_max_per_week,
                avatar_max_per_day=self.avatar_max_per_day,
            )
            logger.info("自动Profile更新器已初始化")

        # Base thinking/memory subsystems: created when async thinking OR
        # life story engine is enabled (life story depends on these modules).
        if self.enable_async_thinking or self.enable_life_story:
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

            # Personality evolution
            evolution_dir = (
                StarTools.get_data_dir("astrbot_plugin_realistic_persona")
                / "personality_evolution"
            )
            self.personality_evolution = PersonalityEvolutionManager(evolution_dir)
            logger.info("人格演化系统已初始化")

            # Life story engine
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
                    update_interval=86400 * self.life_story_update_interval,
                    collect_days=self.life_story_collect_days,
                    context_max_length=self.life_story_context_max_length,
                    cache_days=self.life_story_cache_days,
                )
                logger.info(
                    f"人生故事引擎已初始化（更新间隔: {self.life_story_update_interval}天, 收集范围: {self.life_story_collect_days}天）"
                )
            else:
                logger.info("人生故事引擎未启用")

            # News getter
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

        # Async thinking scheduler (only when async thinking is enabled)
        if self.enable_async_thinking and self.thought_engine and self.experience_bank:
            # llm_action / context_provider / on_thought_generated are bound
            # later at runtime (llm_action after Qzone init, callbacks from Main).
            self.async_thinking_scheduler = AsyncThinkingScheduler(
                thought_engine=self.thought_engine,
                experience_bank=self.experience_bank,
                llm_action=None,
                persona_profile=self.persona_profile,
                think_interval_minutes=self.think_interval_minutes,
                activity_interval_minutes=self.activity_interval_minutes,
                on_thought_generated=None,
                context_provider=None,
                timezone=self._resolve_timezone(),
                local_data_manager=self.local_data_manager,
            )
            logger.info(
                f"异步思考调度器已初始化（思考间隔: {self.think_interval_minutes}分钟, "
                f"活动间隔: {self.activity_interval_minutes}分钟）"
            )

    # ========== Thread-safe accessors for shared mutable state ==========

    async def get_or_create_emotion_context(self, session_id: str) -> EmotionContext:
        """Get or create an EmotionContext for the given session (lock-protected)."""
        async with self._emotion_lock:
            if session_id not in self.emotion_contexts:
                self.emotion_contexts[session_id] = EmotionContext()
            return self.emotion_contexts[session_id]

    async def update_favorability_safe(self, session_id: str, delta: float) -> float:
        """Add delta to favorability for session, clamped to [0, 100]. Returns new value."""
        async with self._favorability_lock:
            current = self.favorability.get(session_id, 0.0)
            new_val = max(0.0, min(100.0, current + delta))
            self.favorability[session_id] = new_val
            return new_val

    async def get_current_event_safe(self, session_id: str):
        """Get the current event for a session (lock-protected read)."""
        async with self._events_lock:
            return self._current_events.get(session_id)

    async def set_current_event_safe(self, session_id: str, event):
        """Set the current event for a session (lock-protected write)."""
        async with self._events_lock:
            self._current_events[session_id] = event

    async def clear_current_event_safe(self, session_id: str):
        """Clear the current event for a session (lock-protected delete)."""
        async with self._events_lock:
            self._current_events.pop(session_id, None)

    async def add_background_task_safe(self, task):
        """Add a task to the background tasks set (lock-protected)."""
        async with self._tasks_lock:
            self._background_tasks.add(task)

    async def discard_background_task_safe(self, task):
        """Remove a task from the background tasks set (lock-protected)."""
        async with self._tasks_lock:
            self._background_tasks.discard(task)

    async def cancel_all_background_tasks_safe(self):
        """Cancel all background tasks, wait for them, and clear the set.

        Lock-protected to avoid iteration-during-modification errors.
        """
        import asyncio as _asyncio

        async with self._tasks_lock:
            tasks = list(self._background_tasks)

        for task in tasks:
            task.cancel()

        if tasks:
            await _asyncio.gather(*tasks, return_exceptions=True)

        async with self._tasks_lock:
            self._background_tasks.clear()

    async def update_life_state_safe(self, session_id: str, data: dict):
        """Update life state for a session (lock-protected write)."""
        async with self._life_state_lock:
            self.life_state[session_id] = data

    async def get_life_state_safe(self, session_id: str) -> dict | None:
        """Get life state for a session (lock-protected read)."""
        async with self._life_state_lock:
            return self.life_state.get(session_id)

    def _resolve_timezone(self) -> str:
        """Resolve timezone from AstrBot config, falling back to Asia/Shanghai."""
        try:
            tz = self.context.get_config().get("timezone")
            return tz if tz else "Asia/Shanghai"
        except Exception:
            return "Asia/Shanghai"

    def get_provider_id(self) -> str | None:
        """Get the current LLM provider ID."""
        try:
            provider = self.context.get_using_provider()
            if provider:
                meta = provider.meta()
                return getattr(meta, "id", None)
        except Exception:
            return None
        return None

    # ========== Shared HTTP session ==========

    def get_http_session(self) -> aiohttp.ClientSession:
        """Get or create a shared aiohttp.ClientSession.

        Reuse a single session across all managers to avoid TCP connection
        leaks from creating per-request sessions.
        """
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
            )
        return self._http_session

    async def close_http_session(self):
        """Close the shared aiohttp.ClientSession if it exists."""
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
            self._http_session = None

    async def get_persona_profile(self) -> str:
        """Get persona profile, preferring plugin config over system persona."""
        if self.persona_profile and self.persona_profile.strip():
            logger.debug("使用插件配置的人设")
            return self.persona_profile.strip()
        try:
            persona_mgr = self.context.persona_manager
            default_persona = await persona_mgr.get_default_persona_v3()
            system_profile = default_persona.get("prompt", "")
            if system_profile:
                logger.debug("使用系统配置的人设")
                return system_profile
        except Exception as e:
            logger.debug(f"获取系统人设失败: {e}")
        logger.debug("未配置人设，使用空字符串")
        return ""


class BaseManager:
    """Base class for all managers.

    Managers receive a reference to SharedState which provides
    access to config, context, and sub-modules.
    """

    def __init__(self, state: SharedState):
        self.state = state

    @property
    def context(self):
        return self.state.context

    @property
    def config(self):
        return self.state.config
