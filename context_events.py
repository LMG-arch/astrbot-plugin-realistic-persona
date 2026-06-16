"""
上下文事件管理模块
根据状态和行为触发事件，实现主动消息发送
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any

from astrbot.api import logger

IDLE_THRESHOLD_SECONDS = 300  # 5 minutes
CONVERSATION_RESUME_THRESHOLD = 600  # 10 minutes


class EventType(Enum):
    """事件类型"""

    EMOTION_CHANGE = "情绪变化"
    USER_IDLE = "用户空闲"
    CONVERSATION_START = "对话开始"
    CONVERSATION_END = "对话结束"
    TOPIC_CHANGE = "话题切换"
    REPEATED_QUESTION = "重复提问"
    LONG_MESSAGE = "长消息"
    GREETING = "问候"


class ContextEvent:
    """上下文事件"""

    def __init__(
        self,
        event_type: EventType,
        data: dict[str, Any] | None = None,
        timestamp: float | None = None,
    ):
        self.event_type = event_type
        self.data = data or {}
        self.timestamp = timestamp or time.time()

    def __repr__(self):
        data_str = str(self.data)
        if len(data_str) > 100:
            data_str = data_str[:100] + "..."
        return f"ContextEvent({self.event_type.value}, {data_str})"


class EventDetector:
    GREETINGS = [
        "你好",
        "嗨",
        "哈喽",
        "在吗",
        "早上好",
        "晚上好",
        "早安",
        "晚安",
        "午安",
    ]

    _PUNCTUATION = str.maketrans(
        "", "", "，。！？、；：''【】《》（）…—·,.!?;:\"'()[]{} "
    )

    @staticmethod
    def is_greeting(message: str) -> bool:
        message_clean = message.lower().strip().translate(EventDetector._PUNCTUATION)
        return any(g in message_clean for g in EventDetector.GREETINGS)

    @staticmethod
    def extract_topic(message: str) -> str | None:
        prefixes = ["我觉得", "我认为", "我想", "关于", "说到", "说起", "聊到"]
        for prefix in prefixes:
            if message.startswith(prefix):
                return message[len(prefix) :].strip()
        keywords = {
            "天气": ["天气", "下雨", "晴天", "温度"],
            "绘画": ["画", "图", "绘", "生成图片", "自拍"],
            "聊天": ["聊天", "说话", "讲", "告诉"],
            "帮助": ["帮", "怎么", "如何", "教"],
        }
        for topic, words in keywords.items():
            if any(word in message for word in words):
                return topic
        return None


class EventTrigger:
    """事件触发器"""

    def __init__(self):
        self.handlers: dict[
            EventType, list[Callable[[ContextEvent], Awaitable[Any] | Any]]
        ] = {}
        self.last_message_time: float | None = None
        self.message_count = 0
        self.last_topic = None
        self._detector = EventDetector()

    def register_handler(
        self,
        event_type: EventType,
        handler: Callable[[ContextEvent], Awaitable[Any] | Any],
    ):
        """
        注册事件处理器

        Args:
            event_type: 事件类型
            handler: 处理函数
        """
        if event_type not in self.handlers:
            self.handlers[event_type] = []
        self.handlers[event_type].append(handler)

    async def trigger_event(self, event: ContextEvent):
        """
        触发事件

        Args:
            event: 上下文事件
        """
        handlers = self.handlers.get(event.event_type, [])
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    await asyncio.to_thread(handler, event)
            except Exception as e:
                logger.error(f"事件处理器执行失败: {e}")

    def detect_event(
        self, message: str, context: dict | None = None
    ) -> list[ContextEvent]:
        """
        检测消息中的事件

        Args:
            message: 用户消息
            context: 上下文信息

        Returns:
            检测到的事件列表
        """
        events = []
        current_time = time.time()

        # 检测问候
        if self._detector.is_greeting(message):
            events.append(ContextEvent(EventType.GREETING, {"message": message}))

        # 检测长消息
        if len(message) > 200:
            events.append(
                ContextEvent(
                    EventType.LONG_MESSAGE, {"message": message, "length": len(message)}
                )
            )

        # 检测用户空闲（距离上次消息超过5分钟）
        # Note: Only detect idle if the user was idle *before* sending this message,
        # not if the current message itself is what ended the idle period.
        # We record idle as a fact about the gap, but skip if this is the trigger.
        idle_duration = (
            (current_time - self.last_message_time) if self.last_message_time else 0
        )
        if idle_duration > IDLE_THRESHOLD_SECONDS:
            events.append(
                ContextEvent(
                    EventType.USER_IDLE,
                    {"idle_duration": idle_duration},
                )
            )

        # 检测对话开始（第一条消息或长时间空闲后的消息）
        # Make CONVERSATION_START mutually exclusive with USER_IDLE:
        # if a conversation is starting/resuming, don't also fire idle.
        is_conversation_start = self.message_count == 0 or (
            self.last_message_time
            and (current_time - self.last_message_time) > CONVERSATION_RESUME_THRESHOLD
        )
        if is_conversation_start:
            events.append(
                ContextEvent(EventType.CONVERSATION_START, {"message": message})
            )
            # Remove USER_IDLE if it was just added -- conversation start supersedes it
            events = [e for e in events if e.event_type != EventType.USER_IDLE]

        # 检测话题切换
        current_topic = self._detector.extract_topic(message)
        if self.last_topic and current_topic and current_topic != self.last_topic:
            events.append(
                ContextEvent(
                    EventType.TOPIC_CHANGE,
                    {"old_topic": self.last_topic, "new_topic": current_topic},
                )
            )

        # 更新状态
        self.last_message_time = current_time
        self.message_count += 1
        if current_topic:
            self.last_topic = current_topic

        return events

    def reset(self):
        """重置触发器状态"""
        self.last_message_time = None
        self.message_count = 0
        self.last_topic = None


class ProactiveMessageManager:
    """主动消息管理器"""

    def __init__(self):
        self.scheduled_messages: list[dict] = []
        self._stop_event = asyncio.Event()
        self._id_counter = 0

    def schedule_message(
        self,
        message: str,
        delay: float,
        session_id: str,
        context_data: dict | None = None,
    ) -> int:
        """
        调度一条主动消息

        Args:
            message: 消息内容
            delay: 延迟时间（秒）
            session_id: 会话ID
            context_data: 上下文数据

        Returns:
            调度消息的ID
        """
        scheduled_time = time.time() + delay
        self._id_counter += 1
        msg_id = self._id_counter
        self.scheduled_messages.append(
            {
                "id": msg_id,
                "message": message,
                "scheduled_time": scheduled_time,
                "session_id": session_id,
                "context_data": context_data or {},
            }
        )
        return msg_id

    async def start_scheduler(
        self, send_callback: Callable[[str, str, dict[str, Any]], Awaitable[None]]
    ):
        """
        启动调度器

        Args:
            send_callback: 消息发送回调函数
        """
        self._stop_event.clear()

        while not self._stop_event.is_set():
            current_time = time.time()
            messages_to_send = []

            for msg_data in self.scheduled_messages:
                if msg_data["scheduled_time"] <= current_time:
                    messages_to_send.append(msg_data)

            for msg_data in messages_to_send:
                try:
                    await send_callback(
                        msg_data["message"],
                        msg_data["session_id"],
                        msg_data["context_data"],
                    )
                    self.scheduled_messages = [
                        m for m in self.scheduled_messages if m["id"] != msg_data["id"]
                    ]
                except Exception as e:
                    logger.error(f"发送主动消息失败: {e}")
                    msg_data["retry_count"] = msg_data.get("retry_count", 0) + 1
                    if msg_data["retry_count"] >= 3:
                        logger.error(
                            f"消息发送失败3次，放弃: {msg_data['message'][:50]}"
                        )
                        self.scheduled_messages = [
                            m
                            for m in self.scheduled_messages
                            if m["id"] != msg_data["id"]
                        ]

            # Calculate timeout based on next scheduled message to avoid busy polling
            if self.scheduled_messages:
                next_time = min(m["scheduled_time"] for m in self.scheduled_messages)
                timeout = max(0.1, next_time - time.time())
            else:
                timeout = 1.0  # No messages pending, poll every second
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=timeout)
                break
            except asyncio.TimeoutError:
                pass

    def stop_scheduler(self):
        """停止调度器"""
        self._stop_event.set()

    def clear_scheduled_messages(self, session_id: str | None = None):
        """
        清空调度的消息

        Args:
            session_id: 如果指定，只清空该会话的消息；否则清空所有
        """
        if session_id:
            self.scheduled_messages = [
                msg
                for msg in self.scheduled_messages
                if msg["session_id"] != session_id
            ]
        else:
            self.scheduled_messages.clear()


class ContextState:
    """上下文状态管理"""

    def __init__(self):
        self.states: dict[str, dict] = {}  # session_id -> state

    def update_state(self, session_id: str, key: str, value):
        """更新会话状态"""
        if session_id not in self.states:
            self.states[session_id] = {}
        self.states[session_id][key] = value

    def get_state(self, session_id: str, key: str, default: Any = None) -> Any:
        """获取会话状态"""
        return self.states.get(session_id, {}).get(key, default)

    def clear_state(self, session_id: str):
        """清空会话状态"""
        if session_id in self.states:
            del self.states[session_id]

    def get_all_sessions(self) -> list[str]:
        """获取所有会话ID"""
        return list(self.states.keys())
