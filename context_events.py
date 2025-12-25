# -*- coding: utf-8 -*-
"""
上下文事件管理模块
根据状态和行为触发事件，实现主动消息发送
"""
from typing import Optional, Dict, List, Callable
import asyncio
import time
from datetime import datetime
from enum import Enum
from astrbot.api import logger


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
    
    def __init__(self, event_type: EventType, data: Dict, timestamp: Optional[float] = None):
        self.event_type = event_type
        self.data = data
        self.timestamp = timestamp or time.time()
    
    def __repr__(self):
        return f"ContextEvent({self.event_type.value}, {self.data})"


class EventTrigger:
    """事件触发器"""
    
    def __init__(self):
        self.handlers: Dict[EventType, List[Callable]] = {}
        self.last_message_time: Optional[float] = None
        self.message_count = 0
        self.last_topic = None
    
    def register_handler(self, event_type: EventType, handler: Callable):
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
                    handler(event)
            except Exception as e:
                logger.error(f"事件处理器执行失败: {e}")
    
    def detect_event(self, message: str, context: Optional[Dict] = None) -> List[ContextEvent]:
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
        if self._is_greeting(message):
            events.append(ContextEvent(
                EventType.GREETING,
                {"message": message}
            ))
        
        # 检测长消息
        if len(message) > 200:
            events.append(ContextEvent(
                EventType.LONG_MESSAGE,
                {"message": message, "length": len(message)}
            ))
        
        # 检测用户空闲（距离上次消息超过5分钟）
        if self.last_message_time and (current_time - self.last_message_time) > 300:
            events.append(ContextEvent(
                EventType.USER_IDLE,
                {"idle_duration": current_time - self.last_message_time}
            ))
        
        # 检测对话开始（第一条消息或长时间空闲后的消息）
        if self.message_count == 0 or (self.last_message_time and (current_time - self.last_message_time) > 600):
            events.append(ContextEvent(
                EventType.CONVERSATION_START,
                {"message": message}
            ))
        
        # 检测话题切换
        current_topic = self._extract_topic(message)
        if self.last_topic and current_topic and current_topic != self.last_topic:
            events.append(ContextEvent(
                EventType.TOPIC_CHANGE,
                {"old_topic": self.last_topic, "new_topic": current_topic}
            ))
        
        # 更新状态
        self.last_message_time = current_time
        self.message_count += 1
        if current_topic:
            self.last_topic = current_topic
        
        return events
    
    def _is_greeting(self, message: str) -> bool:
        """检测是否是问候语"""
        greetings = [
            "你好", "您好", "hi", "hello", "嗨", "hey",
            "早上好", "晚上好", "下午好", "早安", "晚安",
            "在吗", "在不在"
        ]
        message_lower = message.lower().strip()
        return any(greeting in message_lower for greeting in greetings)
    
    def _extract_topic(self, message: str) -> Optional[str]:
        """提取消息主题（简化实现）"""
        # 这里可以使用更复杂的NLP方法，目前使用关键词提取
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
    
    def reset(self):
        """重置触发器状态"""
        self.last_message_time = None
        self.message_count = 0
        self.last_topic = None


class ProactiveMessageManager:
    """主动消息管理器"""
    
    def __init__(self):
        self.scheduled_messages: List[Dict] = []
        self.running = False
    
    def schedule_message(
        self,
        message: str,
        delay: float,
        session_id: str,
        context_data: Optional[Dict] = None
    ):
        """
        调度一条主动消息
        
        Args:
            message: 消息内容
            delay: 延迟时间（秒）
            session_id: 会话ID
            context_data: 上下文数据
        """
        scheduled_time = time.time() + delay
        self.scheduled_messages.append({
            "message": message,
            "scheduled_time": scheduled_time,
            "session_id": session_id,
            "context_data": context_data or {}
        })
    
    async def start_scheduler(self, send_callback: Callable):
        """
        启动调度器
        
        Args:
            send_callback: 消息发送回调函数
        """
        self.running = True
        
        while self.running:
            current_time = time.time()
            messages_to_send = []
            
            # 找出所有应该发送的消息
            for msg_data in self.scheduled_messages:
                if msg_data["scheduled_time"] <= current_time:
                    messages_to_send.append(msg_data)
            
            # 发送消息并从队列中移除
            for msg_data in messages_to_send:
                try:
                    await send_callback(
                        msg_data["message"],
                        msg_data["session_id"],
                        msg_data["context_data"]
                    )
                except Exception as e:
                    logger.error(f"发送主动消息失败: {e}")
                
                self.scheduled_messages.remove(msg_data)
            
            # 等待一段时间再检查
            await asyncio.sleep(1)
    
    def stop_scheduler(self):
        """停止调度器"""
        self.running = False
    
    def clear_scheduled_messages(self, session_id: Optional[str] = None):
        """
        清空调度的消息
        
        Args:
            session_id: 如果指定，只清空该会话的消息；否则清空所有
        """
        if session_id:
            self.scheduled_messages = [
                msg for msg in self.scheduled_messages
                if msg["session_id"] != session_id
            ]
        else:
            self.scheduled_messages.clear()


class ContextState:
    """上下文状态管理"""
    
    def __init__(self):
        self.states: Dict[str, Dict] = {}  # session_id -> state
    
    def update_state(self, session_id: str, key: str, value):
        """更新会话状态"""
        if session_id not in self.states:
            self.states[session_id] = {}
        self.states[session_id][key] = value
    
    def get_state(self, session_id: str, key: str, default=None):
        """获取会话状态"""
        return self.states.get(session_id, {}).get(key, default)
    
    def clear_state(self, session_id: str):
        """清空会话状态"""
        if session_id in self.states:
            del self.states[session_id]
    
    def get_all_sessions(self) -> List[str]:
        """获取所有会话ID"""
        return list(self.states.keys())
