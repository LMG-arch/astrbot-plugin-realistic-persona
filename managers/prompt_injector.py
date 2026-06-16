"""System prompt injector.

Extracted from Main._on_llm_request_handler to decompose the 9-segment
prompt injection pipeline into individually testable methods.
"""

from datetime import datetime

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.provider import ProviderRequest

from ..core.utils import stable_hash
from .base import BaseManager


class SystemPromptInjector(BaseManager):
    """Orchestrates system prompt injection segments for LLM requests."""

    def __init__(self, state, main):
        super().__init__(state)
        # Defer attribute access to runtime to avoid circular references
        self._main = main

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _append_prompt(request: ProviderRequest, text: str):
        """Append *text* to request.system_prompt (creates if missing)."""
        if not hasattr(request, "system_prompt"):
            return
        if request.system_prompt:
            request.system_prompt += text
        else:
            request.system_prompt = text

    @staticmethod
    def _prepend_prompt(request: ProviderRequest, text: str):
        """Prepend *text* to request.system_prompt (creates if missing)."""
        if not hasattr(request, "system_prompt"):
            return
        if request.system_prompt:
            request.system_prompt = text + "\n" + request.system_prompt
        else:
            request.system_prompt = text

    # ------------------------------------------------------------------
    # Segment 1: Time info
    # ------------------------------------------------------------------

    def inject_time_info(self, request: ProviderRequest):
        try:
            now = datetime.now()
            time_str = now.strftime("%Y年%m月%d日 %H:%M:%S")
            time_info = f"[当前时间：{time_str}]"
            self._prepend_prompt(request, time_info)
            logger.debug(f"[时间信息] 已注入时间: {time_str}")
        except Exception as e:
            logger.debug(f"[时间信息] 注入失败: {e}")

    # ------------------------------------------------------------------
    # Segment 2: Message timestamps
    # ------------------------------------------------------------------

    def inject_message_timestamps(self, request: ProviderRequest):
        try:
            if not (hasattr(request, "messages") and request.messages):
                return

            now = datetime.now()
            current_timestamp = now.timestamp()

            for msg in request.messages:
                if not (isinstance(msg, dict) and "content" in msg):
                    continue
                if "time_info" in msg:
                    continue

                msg_timestamp = msg.get("timestamp", current_timestamp)
                time_diff_seconds = max(0, int(current_timestamp - msg_timestamp))

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
                elif msg["role"] == "assistant" and not msg["content"].startswith(
                    "[我的回复时间:"
                ):
                    msg["content"] = (
                        f"[我的回复时间: {time_diff_str}]\n{msg['content']}"
                    )

            logger.debug(f"[历史消息] 已为 {len(request.messages)} 条消息注入时间戳")
        except Exception as e:
            logger.debug(f"[历史消息时间戳] 处理失败: {e}")

    # ------------------------------------------------------------------
    # Segment 3: Life story context
    # ------------------------------------------------------------------

    async def inject_life_story_context(self, request: ProviderRequest):
        if not (self.state.enable_async_thinking and self.state.life_story_engine):
            return
        try:
            life_manager = self._main.life_manager
            thinking_manager = self._main.thinking_manager

            current_persona = await life_manager.get_system_persona_profile()
            if current_persona:
                self.state.life_story_engine.set_base_persona(current_persona)

            if self.state.life_story_engine.should_update():
                import asyncio

                task = asyncio.create_task(thinking_manager.update_life_story_async())
                await self.state.add_background_task_safe(task)
                task.add_done_callback(self.state._background_tasks.discard)
                logger.info("[人生故事] 后台更新经历线已触发")

            story_context = self.state.life_story_engine.get_context_for_llm()
            if story_context:
                self._append_prompt(request, f"\n[背景上下文]\n{story_context}")
                logger.debug(f"[人生故事] 已注入上下文，长度: {len(story_context)}字符")
        except Exception as e:
            logger.error(f"人生故事引擎处理失败: {e}")

    # ------------------------------------------------------------------
    # Segment 4: Memory recall
    # ------------------------------------------------------------------

    async def inject_memory_recall(
        self, request: ProviderRequest, event: AstrMessageEvent
    ):
        if not (self.state.enable_async_thinking and self.state.memory_manager):
            return
        try:
            memory_text = await self._main.thinking_manager.recall_memory_for_context(
                event
            )
            if memory_text:
                self._append_prompt(request, f"\n[相关记忆]\n{memory_text}")
                logger.debug(f"[记忆召回] 已注入记忆，长度: {len(memory_text)}字符")
        except Exception as e:
            logger.debug(f"[记忆召回] 注入失败: {e}")

    # ------------------------------------------------------------------
    # Segment 5: Emotion context
    # ------------------------------------------------------------------

    async def inject_emotion_context(
        self, request: ProviderRequest, event: AstrMessageEvent
    ) -> dict | None:
        """Returns emotion analysis dict if detected, else None."""
        if not self.state.enable_emotion_detection:
            return None
        analysis: dict | None = None
        try:
            logger.debug("[情绪检测] 开始分析用户消息...")
            emotion_manager = self._main.emotion_manager
            analysis = await emotion_manager.process_emotion_and_events(event)
            if analysis and analysis.get("emotion"):
                emotion = analysis["emotion"]
                session_id = event.get_session_id()
                emotion_context = await emotion_manager.get_context(session_id)

                logger.info(f"[情绪检测] 检测到用户情绪: {emotion.value}")

                emotion_info = f"\n[当前检测到用户情绪: {emotion.value}]"

                trend = emotion_context.get_emotion_trend()
                if trend:
                    emotion_info += f"\n[情绪趋势: {trend}]"

                if analysis.get("should_selfie"):
                    emotion_info += (
                        "\n[建议: 可以考虑使用 draw 工具生成一张真人自拍图片，"
                        "表现当前情绪状态，保持真实感]"
                    )

                self._append_prompt(request, emotion_info)

                self.state.context_state.update_state(
                    session_id, "last_emotion", emotion.value
                )
                self.state.context_state.update_state(
                    session_id, "emotion_analysis", analysis
                )
        except Exception as e:
            logger.error(f"情绪分析失败: {e}")
        return analysis

    # ------------------------------------------------------------------
    # Segment 6: Life simulation
    # ------------------------------------------------------------------

    async def inject_life_simulation(
        self,
        request: ProviderRequest,
        event: AstrMessageEvent,
        analysis: dict | None,
    ):
        if not self.state.enable_life_simulation:
            return
        try:
            user_message = (
                event.message_obj.message_str if hasattr(event, "message_obj") else ""
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
                life_info = await self._main.life_manager.build_life_context(
                    event, analysis
                )
                if life_info:
                    logger.info(f"[生活模拟] 已注入背景信息：{life_info[:50]}...")
                    life_context = (
                        f"\n\n[背景信息 - 仅供参考，不影响主要回答]\n{life_info}"
                    )
                    self._append_prompt(request, life_context)
        except Exception as e:
            logger.error(f"生活模拟上下文构建失败: {e}")

    # ------------------------------------------------------------------
    # Segment 7: Personality hint
    # ------------------------------------------------------------------

    def inject_personality_hint(
        self, request: ProviderRequest, event: AstrMessageEvent
    ):
        if not (
            self.state.enable_async_thinking
            and self.state.personality_evolution
            and stable_hash(event.get_session_id()) % 10 == 0
        ):
            return
        try:
            summary = self.state.personality_evolution.get_personality_summary()
            if not summary:
                return

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

            self._append_prompt(request, personality_hint)
        except Exception as e:
            logger.debug(f"注入人格演化上下文失败: {e}")

    # ------------------------------------------------------------------
    # Segment 8: Experience & relationship
    # ------------------------------------------------------------------

    async def inject_experience(
        self, request: ProviderRequest, event: AstrMessageEvent
    ):
        if not (
            self.state.enable_async_thinking
            and self.state.experience_bank
            and self.state.async_thinking_scheduler
        ):
            return
        try:
            user_message = event.message_obj.message_str or ""
            session_id = event.get_session_id()
            unified_msg_origin = event.unified_msg_origin

            await self._main.experience_manager.record_interaction_async(
                session_id, user_message, unified_msg_origin
            )

            if self.state.personality_evolution:
                self.state.personality_evolution.daily_routine()

            # Inject relationship profile for differentiated interactions
            try:
                rel_profile = self.state.experience_bank.get_relationship_profile(
                    session_id
                )
                if rel_profile and rel_profile.get("interaction_count", 0) > 5:
                    rel_hint = (
                        f"\n[与该用户的关系] 互动{rel_profile['interaction_count']}次"
                    )
                    chars = rel_profile.get("relationship_characteristics", "")
                    if chars:
                        rel_hint += f"，特点：{chars}"
                    self._append_prompt(request, rel_hint)
            except Exception:
                pass

        except Exception as e:
            logger.error(f"记录用户交互失败: {e}")

    # ------------------------------------------------------------------
    # Orchestrator
    # ------------------------------------------------------------------

    async def inject_all(self, event: AstrMessageEvent, request: ProviderRequest):
        """Run all 8 injection segments in order."""
        self.inject_time_info(request)
        self.inject_message_timestamps(request)
        await self.inject_life_story_context(request)
        await self.inject_memory_recall(request, event)
        analysis = await self.inject_emotion_context(request, event)
        await self.inject_life_simulation(request, event, analysis)
        self.inject_personality_hint(request, event)
        await self.inject_experience(request, event)
        return None
