import asyncio
import json
from collections import deque
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from emotions import EmotionAnalyzer, EmotionContext, EmotionType


class TestEmotionAnalyzer:
    def test_analyze_happy(self):
        result = EmotionAnalyzer.analyze_emotion("今天好开心啊！")
        assert result == EmotionType.HAPPY

    def test_analyze_sad(self):
        result = EmotionAnalyzer.analyze_emotion("我好难过...")
        assert result == EmotionType.SAD

    def test_analyze_angry(self):
        result = EmotionAnalyzer.analyze_emotion("太生气了！")
        assert result == EmotionType.ANGRY

    def test_analyze_neutral(self):
        result = EmotionAnalyzer.analyze_emotion("今天天气不错")
        assert result is None

    def test_analyze_empty_string(self):
        result = EmotionAnalyzer.analyze_emotion("")
        assert result is None

    def test_analyze_mixed_emotions_returns_highest_score(self):
        result = EmotionAnalyzer.analyze_emotion("开心但是也有点无聊")
        assert result is not None

    def test_detect_selfie_request_explicit(self):
        assert EmotionAnalyzer.detect_selfie_request("发一张自拍") is True
        assert EmotionAnalyzer.detect_selfie_request("来张自拍") is True

    def test_detect_selfie_request_negative(self):
        assert EmotionAnalyzer.detect_selfie_request("你好") is False
        assert EmotionAnalyzer.detect_selfie_request("今天天气怎么样") is False

    def test_lower_keywords_cached(self):
        cache1 = EmotionAnalyzer._get_lower_keywords()
        cache2 = EmotionAnalyzer._get_lower_keywords()
        assert cache1 is cache2

    def test_no_context_parameter(self):
        result = EmotionAnalyzer.analyze_emotion("开心")
        assert result is not None


class TestEmotionContext:
    def test_init(self):
        ctx = EmotionContext()
        assert isinstance(ctx.emotion_history, deque)
        assert len(ctx.emotion_history) == 0

    def test_add_emotion(self):
        ctx = EmotionContext()
        ctx.add_emotion(EmotionType.HAPPY, "开心消息", 1000.0)
        assert len(ctx.emotion_history) == 1
        assert ctx.emotion_history[0]["emotion"] == EmotionType.HAPPY

    def test_add_emotion_max_history(self):
        ctx = EmotionContext()
        for i in range(15):
            ctx.add_emotion(EmotionType.HAPPY, f"消息{i}", 1000.0 + i)
        assert len(ctx.emotion_history) == 10

    def test_add_emotion_deque_auto_evict(self):
        ctx = EmotionContext()
        for i in range(12):
            ctx.add_emotion(EmotionType.HAPPY, f"消息{i}", float(i))
        assert len(ctx.emotion_history) == 10
        first = ctx.emotion_history[0]
        assert first["message"] == "消息2"
