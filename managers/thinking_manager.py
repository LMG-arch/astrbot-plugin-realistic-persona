from astrbot.api import logger

from .base import BaseManager


class ThinkingManager(BaseManager):
    """Manages async thinking: life story updates."""

    async def update_life_story_async(self):
        """Async update life story (background task)."""
        try:
            logger.info("[人生故事] 开始异步更新经历线...")

            if not hasattr(self.state, "llm") or not self.state.llm:
                logger.warning("[人生故事] LLM未初始化，跳过更新")
                return

            success = await self.state.life_story_engine.update_life_story(
                self.state.llm
            )

            if success:
                logger.info("[人生故事] 经历线更新成功")
            else:
                logger.warning("[人生故事] 经历线更新失败")

        except Exception as e:
            logger.error(f"[人生故事] 异步更新失败: {e}", exc_info=True)
