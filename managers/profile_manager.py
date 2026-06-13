from astrbot.api import logger
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

from ..emotions import EMOTION_INTENSITY_MAP, EmotionAnalyzer, EmotionType
from .base import BaseManager


class ProfileManager(BaseManager):
    """Manages auto profile updates based on emotion changes."""

    async def auto_update_profile_on_emotion(
        self, event: AiocqhttpMessageEvent, emotion: EmotionType, intensity: float
    ):
        """Auto update profile based on emotion."""
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

            if intensity < self.state.auto_profile_updater.threshold:
                return

            if not self.check_frequency_limit():
                return

            logger.info(
                f"[Profile更新] 异步思考触发 - 情绪: {emotion.value} (强度: {intensity:.2f})"
            )

            bot = self.state._cached_bot
            if not bot:
                logger.debug("[Profile更新] 无缓存bot对象，跳过QQ API调用")
                return

            context_data = f"情绪: {emotion.value}, 强度: {intensity}, 人设: {self.state.persona_name}"

            if (
                self.state.auto_profile_updater.enable_nickname
                and self.state.auto_profile_updater.can_update("nickname")
            ):
                try:
                    new_nickname = (
                        await self.state.auto_profile_updater.generate_nickname(
                            emotion.value,
                            intensity,
                            llm_action=self.state.llm
                            if self.state.enable_auto_avatar
                            else None,
                            context_data=context_data,
                        )
                    )
                    if new_nickname != self.state.auto_profile_updater.state.get(
                        "current_nickname"
                    ):
                        await bot.set_qq_profile(nickname=new_nickname)
                        self.state.auto_profile_updater.state["current_nickname"] = (
                            new_nickname
                        )
                        self.state.auto_profile_updater._record_update("nickname")
                        logger.info(f"[Profile更新] 异步思考更新昵称: {new_nickname}")
                except Exception as e:
                    logger.debug(f"[Profile更新] 异步思考更新昵称失败: {e}")

            if (
                self.state.auto_profile_updater.enable_signature
                and self.state.auto_profile_updater.can_update("signature")
            ):
                try:
                    new_signature = (
                        await self.state.auto_profile_updater.generate_signature(
                            emotion.value,
                            intensity,
                            context=context_data,
                            llm_action=self.state.llm
                            if self.state.enable_auto_avatar
                            else None,
                        )
                    )
                    if new_signature != self.state.auto_profile_updater.state.get(
                        "current_signature"
                    ):
                        await bot.set_self_longnick(longNick=new_signature)
                        self.state.auto_profile_updater.state["current_signature"] = (
                            new_signature
                        )
                        self.state.auto_profile_updater._record_update("signature")
                        logger.info(f"[Profile更新] 异步思考更新签名: {new_signature}")
                except Exception as e:
                    logger.debug(f"[Profile更新] 异步思考更新签名失败: {e}")

            if (
                self.state.enable_auto_avatar
                and self.state.auto_profile_updater.enable_avatar
                and self.state.auto_profile_updater.can_update("avatar")
                and self.state.auto_profile_updater._check_avatar_daily_limit()
                and self.state.llm
            ):
                try:
                    avatar_prompt = self.state.auto_profile_updater.generate_avatar(
                        emotion.value, intensity
                    )
                    logger.info(
                        f"[Profile更新] 异步思考生成头像，提示词: {avatar_prompt}"
                    )
                    image_url = await self.state.llm._request_image_with_fallback(
                        avatar_prompt, "1024x1024"
                    )
                    if image_url:
                        await bot.set_qq_avatar(file=image_url)
                        self.state.auto_profile_updater.state["last_avatar_url"] = (
                            image_url
                        )
                        self.state.auto_profile_updater._record_update("avatar")
                        logger.info("[Profile更新] 异步思考更新头像成功")
                except Exception as e:
                    logger.debug(f"[Profile更新] 异步思考更新头像失败: {e}")

            if (
                self.state.auto_profile_updater.enable_tag
                and self.state.auto_profile_updater.can_update("tag")
            ):
                try:
                    tag_suggestion = await self.state.auto_profile_updater.generate_tag(
                        emotion.value,
                        intensity,
                        llm_action=self.state.llm
                        if self.state.enable_auto_avatar
                        else None,
                    )
                    if tag_suggestion:
                        self.state.auto_profile_updater.state[
                            "current_tag_suggestion"
                        ] = tag_suggestion
                        self.state.auto_profile_updater._record_update("tag")
                        logger.info(f"[Profile更新] 异步思考标签建议: {tag_suggestion}")
                except Exception as e:
                    logger.debug(f"[Profile更新] 异步思考生成标签失败: {e}")

            self.state.auto_profile_updater._save_state()

        except Exception as e:
            logger.debug(f"[Profile更新] 异步思考触发失败: {e}")

    def check_frequency_limit(self) -> bool:
        """Check update frequency limit."""
        if not self.state.auto_profile_updater:
            return False
        return self.state.auto_profile_updater._check_frequency_limit()
