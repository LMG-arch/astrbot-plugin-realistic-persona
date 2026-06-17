from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent

try:
    from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
        AiocqhttpMessageEvent,
    )

    _AIOCQHTTP_AVAILABLE = True
except ImportError:
    _AIOCQHTTP_AVAILABLE = False
    AiocqhttpMessageEvent = None  # type: ignore[assignment, misc]

from ..emotions import EMOTION_INTENSITY_MAP, EmotionAnalyzer, EmotionType
from .base import BaseManager


class ProfileManager(BaseManager):
    """Manages auto profile updates based on emotion changes."""

    async def auto_update_profile_on_emotion(
        self, event: AstrMessageEvent, emotion: EmotionType, intensity: float
    ):
        """Auto update profile based on emotion."""
        if not _AIOCQHTTP_AVAILABLE:
            return
        if not isinstance(event, AiocqhttpMessageEvent):
            return
        if not self.state.auto_profile_updater:
            return

        try:
            llm_action = None
            if self.state.enable_auto_avatar and hasattr(self.state, "llm"):
                llm_action = self.state.llm

            result = await self.state.auto_profile_updater.check_and_update(
                event=event,
                emotion=emotion.value,
                intensity=intensity,
                llm_action=llm_action,
            )

            if any(result.values()):
                updates = [k for k, v in result.items() if v]
                logger.info(f"[Profile更新] 已更新: {', '.join(updates)}")
        except Exception as e:
            logger.error(f"[自动更新Profile] 失败: {e}", exc_info=True)

    async def on_thought_for_profile_update(self, thought: str):
        """Trigger profile update from async thinking."""
        if not self.state.enable_profile_update_from_thinking:
            return
        if not self.state.auto_profile_updater:
            return
        if (
            not self.state.enable_auto_avatar
            and not self.state.enable_auto_nickname
            and not self.state.enable_auto_signature
        ):
            return

        try:
            emotion = EmotionAnalyzer.analyze_emotion(thought)
            if not emotion:
                return

            intensity = EMOTION_INTENSITY_MAP.get(emotion, 0.3)

            bot = self.state._cached_bot
            if not bot:
                logger.debug("[Profile更新] 无缓存bot对象，跳过QQ API调用")
                return

            context_data = f"情绪: {emotion.value}, 强度: {intensity}, 人设: {self.state.persona_name}"

            llm_action = self.state.llm if self.state.enable_auto_avatar else None

            result = await self.state.auto_profile_updater.update_from_thinking(
                bot=bot,
                emotion=emotion.value,
                intensity=intensity,
                llm_action=llm_action,
                enable_auto_avatar=self.state.enable_auto_avatar,
                context_data=context_data,
            )

            if any(result.values()):
                updates = [k for k, v in result.items() if v]
                logger.info(f"[Profile更新] 异步思考触发更新: {', '.join(updates)}")

        except Exception as e:
            logger.debug(f"[Profile更新] 异步思考触发失败: {e}")

    def check_frequency_limit(self) -> bool:
        """Check update frequency limit."""
        if not self.state.auto_profile_updater:
            return False
        return self.state.auto_profile_updater.can_update("nickname")
