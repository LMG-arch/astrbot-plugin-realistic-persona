"""
Lightweight LLM assistant for async thinking and activity generation.
Does not depend on QQ platform — works with any configured AstrBot LLM provider.
"""

from astrbot.api import logger


class ThinkingLLM:
    """Lightweight LLM helper for async thinking and activity generation."""

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
