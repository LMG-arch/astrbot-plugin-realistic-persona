import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_events import (
    ContextEvent,
    ContextState,
    EventDetector,
    EventTrigger,
    EventType,
    ProactiveMessageManager,
)


class TestEventDetector:
    def test_is_greeting_true(self):
        assert EventDetector.is_greeting("你好") is True
        assert EventDetector.is_greeting("嗨") is True
        assert EventDetector.is_greeting("早上好") is True

    def test_is_greeting_false(self):
        assert EventDetector.is_greeting("今天天气不错") is False
        assert EventDetector.is_greeting("帮我查一下") is False

    def test_is_greeting_avoids_false_match(self):
        assert EventDetector.is_greeting("你在哪里工作") is False

    def test_extract_topic_with_prefix(self):
        result = EventDetector.extract_topic("我觉得这个项目很好")
        assert result == "这个项目很好"

    def test_extract_topic_no_prefix(self):
        result = EventDetector.extract_topic("随便聊聊")
        assert result is None


class TestContextEvent:
    def test_init(self):
        event = ContextEvent(EventType.GREETING, {"msg": "你好"})
        assert event.event_type == EventType.GREETING
        assert event.data == {"msg": "你好"}

    def test_repr_truncation(self):
        long_data = {"key": "x" * 200}
        event = ContextEvent(EventType.GREETING, long_data)
        repr_str = repr(event)
        assert len(repr_str) < 200

    def test_repr_short_data(self):
        event = ContextEvent(EventType.GREETING, {"key": "short"})
        repr_str = repr(event)
        assert "问候" in repr_str or "GREETING" in repr_str


class TestProactiveMessageManager:
    @pytest.mark.asyncio
    async def test_schedule_message_returns_id(self):
        mgr = ProactiveMessageManager()
        msg_id = mgr.schedule_message("你好", 5.0, "session1")
        assert isinstance(msg_id, int)
        assert msg_id > 0

    @pytest.mark.asyncio
    async def test_schedule_message_unique_ids(self):
        mgr = ProactiveMessageManager()
        id1 = mgr.schedule_message("你好", 5.0, "session1")
        id2 = mgr.schedule_message("再见", 5.0, "session1")
        assert id1 != id2

    @pytest.mark.asyncio
    async def test_stop_scheduler_immediate(self):
        mgr = ProactiveMessageManager()
        mgr.stop_scheduler()
        assert mgr._stop_event.is_set()

    @pytest.mark.asyncio
    async def test_clear_scheduled_messages(self):
        mgr = ProactiveMessageManager()
        mgr.schedule_message("你好", 5.0, "session1")
        mgr.schedule_message("再见", 5.0, "session2")
        assert len(mgr.scheduled_messages) == 2
        mgr.clear_scheduled_messages()
        assert len(mgr.scheduled_messages) == 0
