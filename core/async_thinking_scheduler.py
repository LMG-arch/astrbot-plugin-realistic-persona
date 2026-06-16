"""
异步思考循环调度器
管理后台思考线程，定期生成思考和活动记录
"""

import asyncio
import zoneinfo
from collections.abc import Callable
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from astrbot.api import logger

from .experience_bank import ExperienceBank
from .thought_engine import ThoughtEngine


class AsyncThinkingScheduler:
    """异步思考循环调度器"""

    def __init__(
        self,
        thought_engine: ThoughtEngine,
        experience_bank: ExperienceBank,
        llm_action=None,
        on_weather_changed: Callable | None = None,
        persona_profile: str = "",
        context_provider: Callable | None = None,
        think_interval_minutes: int = 20,
        activity_interval_minutes: int = 25,
        on_thought_generated: Callable | None = None,
        timezone: str = "Asia/Shanghai",
        local_data_manager=None,
    ):
        """
        初始化调度器

        Args:
            thought_engine: 思考引擎实例
            experience_bank: 经历银行实例
            llm_action: LLM动作实例，用于大模型思考
            on_weather_changed: 天气变化时的回调函数
            persona_profile: 人格描述，用于指导大模型生成符合人设的思考
            context_provider: 异步回调函数，返回 dict 包含 schedule/news/recent_conversations/recent_experiences
            think_interval_minutes: 思考触发间隔(分钟)
            activity_interval_minutes: 活动记录间隔(分钟)
            timezone: Timezone string for the scheduler, e.g. "Asia/Shanghai"
            local_data_manager: 本地数据管理器，用于每日过期数据清理
        """
        # 使用传入的引擎实例
        self.thought_engine = thought_engine
        self.experience_bank = experience_bank
        self.llm_action = llm_action
        self.persona_profile = persona_profile
        self.think_interval_minutes = think_interval_minutes
        self.activity_interval_minutes = activity_interval_minutes
        self.local_data_manager = local_data_manager

        # 调度器
        self.scheduler = AsyncIOScheduler(timezone=zoneinfo.ZoneInfo(timezone))

        # 回调函数
        self.on_weather_changed = on_weather_changed
        self.context_provider = context_provider
        self.on_thought_generated = on_thought_generated

        # 缓存当前天气
        self.current_weather: str | None = None

        # 是否正在运行
        self.is_running = False

    def start(self):
        """启动异步思考循环"""
        try:
            if self.is_running:
                logger.warning("[异步思考] 调度器已在运行")
                return

            # 安排定期思考任务（使用配置的间隔）
            self.scheduler.add_job(
                func=self._scheduled_think,
                trigger=IntervalTrigger(minutes=self.think_interval_minutes),
                name="thought_generator",
                max_instances=1,
            )

            # 安排定期活动记录任务（使用配置的间隔）
            self.scheduler.add_job(
                func=self._scheduled_activity,
                trigger=IntervalTrigger(minutes=self.activity_interval_minutes),
                name="activity_recorder",
                max_instances=1,
            )

            # 安排每日复盘任务（每晚9点）
            self.scheduler.add_job(
                func=self._daily_review,
                trigger="cron",
                hour=21,
                minute=0,
                name="daily_review",
                max_instances=1,
            )

            # 安排每日数据清理任务（凌晨3点）
            if self.local_data_manager is not None:
                self.scheduler.add_job(
                    func=self._daily_cleanup,
                    trigger="cron",
                    hour=3,
                    minute=0,
                    name="daily_cleanup",
                    max_instances=1,
                )

            self.scheduler.start()
            self.is_running = True

            logger.info(
                f"[异步思考] 调度器已启动，思考间隔{self.think_interval_minutes}分钟，活动间隔{self.activity_interval_minutes}分钟"
            )

        except Exception as e:
            logger.error(f"[异步思考] 启动调度器失败: {e}")

    def stop(self):
        """停止异步思考循环"""
        try:
            if not self.is_running:
                logger.warning("[异步思考] 调度器未运行")
                return

            self.scheduler.shutdown(wait=False)
            self.is_running = False

            logger.info("[异步思考] 调度器已停止")

        except Exception as e:
            logger.error(f"[异步思考] 停止调度器失败: {e}")

    async def _scheduled_think(self):
        """定期思考任务"""
        try:
            logger.info("[异步思考] 触发定期思考")

            # 通过上下文提供者获取丰富的上下文信息
            schedule = None
            news = None
            recent_conversations = None
            recent_experiences = None

            if self.context_provider:
                try:
                    ctx = await self.context_provider()
                    if ctx and isinstance(ctx, dict):
                        schedule = ctx.get("schedule")
                        news = ctx.get("news")
                        recent_conversations = ctx.get("recent_conversations")
                        recent_experiences = ctx.get("recent_experiences")
                        # Also update weather from context if available
                        if ctx.get("weather") and not self.current_weather:
                            self.current_weather = ctx["weather"]
                except Exception as e:
                    logger.debug(f"[异步思考] 获取上下文失败: {e}")

            thought = await self.thought_engine.generate_thought(
                llm_action=self.llm_action,
                weather=self.current_weather,
                current_time=datetime.now(),
                persona_profile=self.persona_profile,
                schedule=schedule,
                news=news,
                recent_conversations=recent_conversations,
                recent_experiences=recent_experiences,
            )

            if thought:
                # 记录为事件
                self.experience_bank.record_event(
                    event_type="thought",
                    description=thought,
                    metadata={"weather": self.current_weather},
                )

                # 通知回调（用于人格更新等）
                if self.on_thought_generated:
                    try:
                        result = self.on_thought_generated(thought)
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception as cb_err:
                        logger.warning(
                            f"[异步思考] on_thought_generated 回调失败: {cb_err}"
                        )

        except Exception as e:
            logger.error(f"[异步思考] 定期思考失败: {e}")

    async def _scheduled_activity(self):
        """定期活动记录任务，使用LLM结合上下文生成活动内容"""
        try:
            logger.info("[异步思考] 触发日常活动记录")

            # 通过上下文提供者获取丰富的上下文信息
            schedule = None
            if self.context_provider:
                try:
                    ctx = await self.context_provider()
                    if ctx and isinstance(ctx, dict):
                        schedule = ctx.get("schedule")
                        if ctx.get("weather") and not self.current_weather:
                            self.current_weather = ctx["weather"]
                except Exception as e:
                    logger.debug(f"[异步思考] 获取活动上下文失败: {e}")

            activity = await self.thought_engine.generate_activity(
                llm_action=self.llm_action,
                current_time=datetime.now(),
                persona_profile=self.persona_profile,
                weather=self.current_weather,
                schedule=schedule,
            )

            if activity:
                # 记录为事件
                self.experience_bank.record_event(
                    event_type="daily_activity", description=activity
                )

        except Exception as e:
            logger.error(f"[异步思考] 活动记录失败: {e}")

    async def _daily_review(self):
        """每日复盘任务"""
        try:
            logger.info("[异步思考] 进行每日复盘")

            # 获取今天的思考和活动
            thoughts = self.thought_engine.get_today_thoughts()
            activities = self.thought_engine.get_today_activities()

            logger.info(
                f"[异步思考] 今日思考数: {len(thoughts)}, 活动数: {len(activities)}"
            )

            # 可以在这里添加复盘总结
            if len(thoughts) > 0 or len(activities) > 0:
                self.experience_bank.record_event(
                    event_type="daily_review",
                    description=f"今日思考{len(thoughts)}次，活动{len(activities)}项",
                    metadata={
                        "thoughts_count": len(thoughts),
                        "activities_count": len(activities),
                    },
                )

        except Exception as e:
            logger.error(f"[异步思考] 每日复盘失败: {e}")

    async def _daily_cleanup(self):
        """每日数据清理任务，清理过期的本地缓存数据"""
        try:
            logger.info("[异步思考] 执行每日数据清理")
            if self.local_data_manager is not None:
                self.local_data_manager.clear_expired_data(days_to_keep=7)
                logger.info("[异步思考] 每日数据清理完成")
        except Exception as e:
            logger.error(f"[异步思考] 每日数据清理失败: {e}")

    def set_weather(self, weather: str):
        """
        设置当前天气（用于影响思考内容）

        Args:
            weather: 天气描述
        """
        old_weather = self.current_weather
        self.current_weather = weather

        # 如果天气改变，触发回调
        if old_weather != weather:
            logger.info(f"[异步思考] 天气已更新: {old_weather} -> {weather}")

            if self.on_weather_changed:
                try:
                    self.on_weather_changed(weather)
                except Exception as e:
                    logger.error(f"[异步思考] 天气变化回调失败: {e}")

    def record_user_interaction(
        self,
        user_id: str,
        user_message: str,
        bot_response: str,
        session_id: str | None = None,
    ):
        """
        记录用户互动（用于经历累积）

        Args:
            user_id: 用户ID
            user_message: 用户消息
            bot_response: 机器人回复
            session_id: 会话ID
        """
        try:
            self.experience_bank.record_conversation(
                user_id=user_id,
                user_message=user_message,
                bot_response=bot_response,
                session_id=session_id,
            )
        except Exception as e:
            logger.error(f"[异步思考] 记录互动失败: {e}")
