import time

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent

from ..emotions import EMOTION_INTENSITY_MAP, EmotionAnalyzer, EmotionContext
from .base import BaseManager


class EmotionManager(BaseManager):
    """Manages emotion detection, context tracking, and favorability."""

    def get_context(self, session_id: str) -> EmotionContext:
        """Get or create emotion context for a session."""
        if session_id not in self.state.emotion_contexts:
            self.state.emotion_contexts[session_id] = EmotionContext()
        return self.state.emotion_contexts[session_id]

    async def process_emotion_and_events(self, event: AstrMessageEvent) -> dict | None:
        """Process emotion analysis and event detection."""
        message = event.message_obj.message_str
        session_id = event.get_session_id()

        result = {
            "emotion": None,
            "should_selfie": False,
            "selfie_prompt": None,
            "events": [],
        }

        if self.state.enable_emotion_detection:
            logger.debug("情绪检测已启用，开始分析...")
            emotion = EmotionAnalyzer.analyze_emotion(message)
            self.update_favorability(event, emotion=emotion)
            if emotion:
                result["emotion"] = emotion
                logger.info(f"检测到情绪: {emotion.value} 在会话 {session_id}")

                emotion_context = self.get_context(session_id)
                emotion_context.add_emotion(emotion, message, time.time())

                if self.state.enable_auto_selfie:
                    if EmotionAnalyzer.should_trigger_selfie(
                        emotion, self.state.selfie_trigger_chance
                    ):
                        result["should_selfie"] = True
                        result["selfie_prompt"] = EmotionAnalyzer.get_selfie_prompt(
                            emotion
                        )
                        logger.info(
                            f"触发自拍，情绪: {emotion.value}, 提示词: {result['selfie_prompt']}"
                        )
        else:
            logger.debug("情绪检测功能未启用")

        if EmotionAnalyzer.detect_selfie_request(message):
            result["should_selfie"] = True
            if not result["selfie_prompt"]:
                result["selfie_prompt"] = (
                    f"一个友好可爱的{self.state.persona_name}自拍照，真人自拍，自然光线，日常装扮"
                )
            logger.info(f"检测到明确的自拍请求，会话: {session_id}")

        if self.state.enable_context_events:
            events = self.state.event_trigger.detect_event(message)
            result["events"] = events

            for evt in events:
                logger.debug(f"触发事件: {evt.event_type.value}，数据: {evt.data}")
                await self.state.event_trigger.trigger_event(evt)
        else:
            logger.debug("上下文事件检测未启用")

        logger.debug(
            f"情绪分析完成，结果: {result['emotion'].value if result['emotion'] else '无'}, 自拍: {result['should_selfie']}"
        )
        return result

    def update_favorability(self, event: AstrMessageEvent, emotion=None) -> None:
        """Accumulate favorability based on session activity, bounded to [0, 100]."""
        try:
            session_id = event.get_session_id()
        except Exception:
            return
        if emotion is None:
            message = event.message_obj.message_str or ""
            emotion = EmotionAnalyzer.analyze_emotion(message)
        if emotion:
            delta = EMOTION_INTENSITY_MAP.get(emotion, 0.3) * 2.0
        else:
            delta = 0.5
        current = self.state.favorability.get(session_id, 0.0)
        self.state.favorability[session_id] = max(0.0, min(100.0, current + delta))

    def get_status(self, session_id: str) -> str:
        """Get emotion status for a session."""
        emotion_context = self.get_context(session_id)
        recent_emotion = emotion_context.get_recent_emotion()
        trend = emotion_context.get_emotion_trend()

        if recent_emotion:
            status = f"当前情绪: {recent_emotion.value}"
            if trend:
                status += f"\n情绪趋势: {trend}"
            status += f"\n情绪历史记录数: {len(emotion_context.emotion_history)}"
        else:
            status = "暂无情绪数据"

        return status
