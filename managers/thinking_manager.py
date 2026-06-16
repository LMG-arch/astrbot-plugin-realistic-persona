from astrbot.api import logger

from .base import BaseManager


class ThinkingManager(BaseManager):
    """Manages async thinking: life story updates and memory recall."""

    async def recall_memory_for_context(self, event) -> str:
        """Recall relevant memories for the current user message.

        Returns formatted memory text for system_prompt injection,
        or empty string if no relevant memories found.
        """
        if not self.state.memory_manager:
            return ""

        try:
            session_id = event.get_session_id()
            user_message = ""
            if hasattr(event, "message_obj"):
                user_message = event.message_obj.message_str or ""

            if not user_message or len(user_message) < 5:
                return ""

            memory_text = await self.state.memory_manager.recall_relevant(
                query=user_message,
                user_id=session_id,
                limit=3,
                context=self.context,
            )
            if memory_text:
                logger.debug(
                    f"[记忆召回] 为会话 {session_id} 召回记忆: {len(memory_text)} 字符"
                )
            return memory_text
        except Exception as e:
            logger.debug(f"[记忆召回] 失败: {e}")
            return ""

    async def update_life_story_async(self):
        """Async update life story (background task).

        Uses context to obtain LLM provider, falling back to llm_action.
        Works even when QQ zone is not enabled.
        """
        try:
            logger.info("[人生故事] 开始异步更新经历线...")

            success = await self.state.life_story_engine.update_life_story(
                llm_action=getattr(self.state, "llm", None),
                context=self.context,
            )

            if success:
                logger.info("[人生故事] 经历线更新成功")
            else:
                logger.warning("[人生故事] 经历线更新失败")

        except Exception as e:
            logger.error(f"[人生故事] 异步更新失败: {e}", exc_info=True)
