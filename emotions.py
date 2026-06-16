"""
情绪感知模块
根据用户消息和上下文分析情绪，并触发相应的AI行为
"""

import random
from collections import deque
from enum import Enum

from astrbot.api import logger


class EmotionType(Enum):
    """情绪类型枚举"""

    HAPPY = "开心"
    SAD = "悲伤"
    ANGRY = "生气"
    EXCITED = "兴奋"
    CALM = "平静"
    CONFUSED = "困惑"
    BORED = "无聊"
    CURIOUS = "好奇"
    SURPRISED = "惊讶"
    ANXIOUS = "焦虑"


# Shared emotion-to-intensity mapping for profile updates and thinking triggers.
# Used by both main.py (bot emotion path) and profile_manager.py (thinking path).
EMOTION_INTENSITY_MAP = {
    EmotionType.EXCITED: 0.8,
    EmotionType.HAPPY: 0.65,
    EmotionType.SAD: 0.65,
    EmotionType.ANGRY: 0.65,
    EmotionType.SURPRISED: 0.5,
    EmotionType.ANXIOUS: 0.6,
    EmotionType.BORED: 0.4,
    EmotionType.CONFUSED: 0.35,
    EmotionType.CURIOUS: 0.45,
    EmotionType.CALM: 0.15,
}


class EmotionAnalyzer:
    """情绪分析器"""

    # 情绪关键词映射
    EMOTION_KEYWORDS = {
        EmotionType.HAPPY: [
            "开心",
            "高兴",
            "快乐",
            "哈哈",
            "😊",
            "😄",
            "🥰",
            "真棒",
            "太棒",
            "好棒",
            "好耶",
            "太好了",
        ],
        EmotionType.SAD: [
            "难过",
            "伤心",
            "悲伤",
            "😢",
            "😭",
            "呜呜",
            "痛苦",
            "失望",
            "沮丧",
        ],
        EmotionType.ANGRY: ["生气", "愤怒", "讨厌", "😠", "😡", "烦", "气死", "可恶"],
        EmotionType.EXCITED: [
            "激动",
            "兴奋",
            "哇",
            "太棒了",
            "🎉",
            "耶",
            "牛逼",
            "牛啊",
            "太牛",
            "厉害",
            "amazing",
        ],
        EmotionType.CALM: ["平静", "安静", "淡定", "冷静", "还好", "一般"],
        EmotionType.CONFUSED: [
            "困惑",
            "迷惑",
            "不懂",
            "❓",
            "？？？",
            "啊？",
            "懵",
        ],
        EmotionType.BORED: ["无聊", "无趣", "没意思", "😴", "枯燥", "烦闷"],
        EmotionType.CURIOUS: ["好奇", "想知道", "为什么", "怎么样", "🤔", "有趣"],
        EmotionType.SURPRISED: [
            "惊讶",
            "震惊",
            "卧槽",
            "😲",
            "😮",
            "天哪",
            "不会吧",
            "真的假的",
        ],
        EmotionType.ANXIOUS: ["焦虑", "担心", "紧张", "😰", "害怕", "不安", "忐忑"],
    }

    _EMOTION_KEYWORDS_LOWER: dict[EmotionType, list[str]] = {}

    @classmethod
    def _get_lower_keywords(cls) -> dict[EmotionType, list[str]]:
        if not cls._EMOTION_KEYWORDS_LOWER:
            cls._EMOTION_KEYWORDS_LOWER = {
                emotion: [kw.lower() for kw in keywords]
                for emotion, keywords in cls.EMOTION_KEYWORDS.items()
            }
        return cls._EMOTION_KEYWORDS_LOWER

    # 情绪对应的AI行为触发
    EMOTION_TRIGGERS = {
        EmotionType.HAPPY: {
            "should_selfie": True,
            "selfie_prompt": "真人自拍，开心地对着手机镜头微笑，自然光线，日常装扮，生活场景",
            "response_style": "愉快、积极",
        },
        EmotionType.SAD: {
            "should_selfie": True,
            "selfie_prompt": "真人自拍，温柔表情，柔和光线，日常装扮，生活场景，传递安慰感",
            "response_style": "温柔、安慰",
        },
        EmotionType.EXCITED: {
            "should_selfie": True,
            "selfie_prompt": "真人自拍，兴奋地对着手机镜头，表情生动，自然光线，日常装扮，生活场景",
            "response_style": "充满活力、热情",
        },
        EmotionType.BORED: {
            "should_selfie": True,
            "selfie_prompt": "真人自拍，俏皮表情或搞怪姿势，自然光线，日常装扮，生活场景",
            "response_style": "俏皮、有趣",
        },
        EmotionType.CURIOUS: {
            "should_selfie": False,
            "response_style": "好奇、探索",
        },
        EmotionType.SURPRISED: {
            "should_selfie": True,
            "selfie_prompt": "真人自拍，惊讶表情，自然光线，日常装扮，生活场景",
            "response_style": "惊讶、活泼",
        },
    }

    @classmethod
    def analyze_emotion(cls, message: str) -> EmotionType | None:
        """
        分析消息中的情绪

        Args:
            message: 用户消息

        Returns:
            检测到的情绪类型，如果没有检测到则返回None
        """
        message_lower = message.lower()

        emotion_scores = {}

        for emotion, keywords_lower in cls._get_lower_keywords().items():
            score = 0
            for keyword in keywords_lower:
                if keyword in message_lower:
                    score += 1

            if score > 0:
                emotion_scores[emotion] = score

        # 返回得分最高的情绪
        if emotion_scores:
            detected_emotion = max(emotion_scores.items(), key=lambda x: x[1])[0]
            logger.debug(
                f"[EMOTION DETECT] 检测到情绪: {detected_emotion.value}, 消息: {message[:50]}..."
            )
            return detected_emotion

        logger.debug(f"[EMOTION DETECT] 未检测到情绪, 消息: {message[:50]}...")
        return None

    @classmethod
    def get_emotion_trigger(cls, emotion: EmotionType) -> dict | None:
        """
        获取情绪对应的触发行为

        Args:
            emotion: 情绪类型

        Returns:
            触发行为配置字典
        """
        return cls.EMOTION_TRIGGERS.get(emotion)

    @classmethod
    def should_trigger_selfie(
        cls, emotion: EmotionType, random_chance: float = 0.3
    ) -> bool:
        """
        判断是否应该触发自拍

        Args:
            emotion: 情绪类型
            random_chance: 随机触发概率（0-1）

        Returns:
            是否应该触发自拍
        """
        trigger = cls.get_emotion_trigger(emotion)
        if not trigger:
            return False

        # 如果配置了should_selfie，且满足随机概率
        if trigger.get("should_selfie", False):
            result = random.random() < random_chance
            logger.debug(
                f"[SELFIE TRIGGER] 情绪 {emotion.value} 触发自拍检查: {result} (概率 {random_chance})"
            )
            return result

        logger.debug(f"[SELFIE TRIGGER] 情绪 {emotion.value} 不支持自拍")
        return False

    @classmethod
    def get_selfie_prompt(cls, emotion: EmotionType, custom_context: str = "") -> str:
        """
        获取自拍提示词

        Args:
            emotion: 情绪类型
            custom_context: 自定义上下文

        Returns:
            生成的提示词
        """
        trigger = cls.get_emotion_trigger(emotion)
        if not trigger:
            return "一个友好的AI助手，卡通风格"

        base_prompt = trigger.get("selfie_prompt", "一个友好的AI助手")

        if custom_context:
            return f"{base_prompt}，{custom_context}"

        return base_prompt

    @classmethod
    def detect_selfie_request(cls, message: str) -> bool:
        """
        检测用户是否明确请求自拍

        Args:
            message: 用户消息

        Returns:
            是否是自拍请求
        """
        selfie_keywords = [
            "自拍",
            "发张照片",
            "拍张照",
            "看看你",
            "你长什么样",
            "发个照片",
            "来张图",
            "自我介绍",
            "露个脸",
        ]

        message_lower = message.lower()
        result = any(keyword in message_lower for keyword in selfie_keywords)
        if result:
            logger.debug(f"[SELFIE REQUEST] 检测到明确自拍请求: {message[:50]}...")
        return result


class EmotionContext:
    """情绪上下文管理"""

    def __init__(self):
        self.max_history: int = 10
        self.emotion_history: deque[dict] = deque(maxlen=self.max_history)

    def add_emotion(self, emotion: EmotionType, message: str, timestamp: float):
        """添加情绪记录"""
        self.emotion_history.append(
            {"emotion": emotion, "message": message, "timestamp": timestamp}
        )

    def get_recent_emotion(self) -> EmotionType | None:
        """获取最近的情绪"""
        if self.emotion_history:
            return self.emotion_history[-1]["emotion"]
        return None

    def get_emotion_trend(self) -> str | None:
        """分析情绪趋势"""
        if len(self.emotion_history) < 2:
            return None

        recent_emotions = [item["emotion"] for item in self.emotion_history[-3:]]

        # 判断情绪是否趋向积极
        positive_emotions = [EmotionType.HAPPY, EmotionType.EXCITED, EmotionType.CALM]
        negative_emotions = [EmotionType.SAD, EmotionType.ANGRY, EmotionType.ANXIOUS]

        positive_count = sum(1 for e in recent_emotions if e in positive_emotions)
        negative_count = sum(1 for e in recent_emotions if e in negative_emotions)

        if positive_count > negative_count:
            return "positive"
        elif negative_count > positive_count:
            return "negative"
        else:
            return "neutral"

    def clear_history(self):
        """清空情绪历史"""
        self.emotion_history.clear()
