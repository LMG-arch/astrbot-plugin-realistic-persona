# -*- coding: utf-8 -*-
"""
异步思考循环调度器
管理后台思考线程，定期生成思考和活动记录
"""
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Callable
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from astrbot.api import logger

from .thought_engine import ThoughtEngine
from .experience_bank import ExperienceBank


class AsyncThinkingScheduler:
    """异步思考循环调度器"""
    
    def __init__(self, thought_engine: ThoughtEngine, experience_bank: ExperienceBank, llm_action=None, on_weather_changed: Optional[Callable] = None, persona_profile: str = ""):
        """
        初始化调度器
        
        Args:
            thought_engine: 思考引擎实例
            experience_bank: 经历银行实例
            llm_action: LLM动作实例，用于大模型思考
            on_weather_changed: 天气变化时的回调函数
            persona_profile: 人格描述，用于指导大模型生成符合人设的思考
        """
        # 使用传入的引擎实例
        self.thought_engine = thought_engine
        self.experience_bank = experience_bank
        self.llm_action = llm_action
        self.persona_profile = persona_profile
        
        # 调度器
        self.scheduler = AsyncIOScheduler()
        
        # 回调函数
        self.on_weather_changed = on_weather_changed
        
        # 缓存当前天气
        self.current_weather: Optional[str] = None
        
        # 是否正在运行
        self.is_running = False
    
    def start(self):
        """启动异步思考循环"""
        try:
            if self.is_running:
                logger.warning("[异步思考] 调度器已在运行")
                return
            
            # 安排定期思考任务（每15-30分钟）
            self.scheduler.add_job(
                func=self._scheduled_think,
                trigger=IntervalTrigger(minutes=20),  # 每20分钟思考一次
                name="thought_generator",
                max_instances=1,
            )
            
            # 安排定期活动记录任务（每25-35分钟）
            self.scheduler.add_job(
                func=self._scheduled_activity,
                trigger=IntervalTrigger(minutes=25),  # 每25分钟记录一个活动
                name="activity_recorder",
                max_instances=1,
            )
            
            # 安排每日复盘任务（每晚9点）
            self.scheduler.add_job(
                func=self._daily_review,
                trigger="cron",
                hour=21,
                minute=0,
                name="daily_review",
                max_instances=1,
            )
            
            self.scheduler.start()
            self.is_running = True
            
            logger.info("[异步思考] 调度器已启动")
            
        except Exception as e:
            logger.error(f"[异步思考] 启动调度器失败: {e}")
    
    def stop(self):
        """停止异步思考循环"""
        try:
            if not self.is_running:
                logger.warning("[异步思考] 调度器未运行")
                return
            
            self.scheduler.shutdown()
            self.is_running = False
            
            logger.info("[异步思考] 调度器已停止")
            
        except Exception as e:
            logger.error(f"[异步思考] 停止调度器失败: {e}")
    
    async def _scheduled_think(self):
        """定期思考任务"""
        try:
            logger.info("[异步思考] 触发定期思考")
            thought = await self.thought_engine.generate_thought(
                llm_action=self.llm_action,
                weather=self.current_weather,
                current_time=datetime.now(),
                persona_profile=self.persona_profile
            )
            
            if thought:
                # 记录为事件
                self.experience_bank.record_event(
                    event_type="thought",
                    description=thought,
                    metadata={"weather": self.current_weather}
                )
            
        except Exception as e:
            logger.error(f"[异步思考] 定期思考失败: {e}")
    
    async def _scheduled_activity(self):
        """定期活动记录任务"""
        try:
            logger.info("[异步思考] 触发日常活动记录")
            activity = await self.thought_engine.generate_activity(
                current_time=datetime.now()
            )
            
            if activity:
                # 记录为事件
                self.experience_bank.record_event(
                    event_type="daily_activity",
                    description=activity
                )
            
        except Exception as e:
            logger.error(f"[异步思考] 活动记录失败: {e}")
    
    async def _daily_review(self):
        """每日复盘任务"""
        try:
            logger.info("[异步思考] 进行每日复盘")
            
            # 获取今天的思考和活动
            thoughts = self.thought_engine.get_today_thoughts()
            activities = self.thought_engine.get_today_activities()
            
            logger.info(f"[异步思考] 今日思考数: {len(thoughts)}, 活动数: {len(activities)}")
            
            # 可以在这里添加复盘总结
            if len(thoughts) > 0 or len(activities) > 0:
                self.experience_bank.record_event(
                    event_type="daily_review",
                    description=f"今日思考{len(thoughts)}次，活动{len(activities)}项",
                    metadata={
                        "thoughts_count": len(thoughts),
                        "activities_count": len(activities)
                    }
                )
            
        except Exception as e:
            logger.error(f"[异步思考] 每日复盘失败: {e}")
    
    def set_weather(self, weather: str):
        """
        设置当前天气（用于影响思考内容）
        
        Args:
            weather: 天气描述
        """
        old_weather = self.current_weather
        self.current_weather = weather
        
        # 如果天气改变，触发回调
        if old_weather != weather:
            logger.info(f"[异步思考] 天气已更新: {old_weather} -> {weather}")
            
            if self.on_weather_changed:
                try:
                    self.on_weather_changed(weather)
                except Exception as e:
                    logger.error(f"[异步思考] 天气变化回调失败: {e}")
    
    def record_user_interaction(self, user_id: str, user_message: str, bot_response: str, session_id: Optional[str] = None):
        """
        记录用户互动（用于经历累积）
        
        Args:
            user_id: 用户ID
            user_message: 用户消息
            bot_response: 机器人回复
            session_id: 会话ID
        """
        try:
            self.experience_bank.record_conversation(
                user_id=user_id,
                user_message=user_message,
                bot_response=bot_response,
                session_id=session_id
            )
        except Exception as e:
            logger.error(f"[异步思考] 记录互动失败: {e}")
    
    def update_skill(self, skill_name: str, level: int = 1):
        """更新技能"""
        try:
            self.experience_bank.update_growth("skills", skill_name, level)
        except Exception as e:
            logger.error(f"[异步思考] 更新技能失败: {e}")
    
    def add_interest(self, interest_name: str):
        """添加兴趣"""
        try:
            self.experience_bank.update_growth("interests", interest_name)
        except Exception as e:
            logger.error(f"[异步思考] 添加兴趣失败: {e}")
    
    def add_view(self, view_description: str):
        """添加观点"""
        try:
            self.experience_bank.update_growth("views", view_description)
        except Exception as e:
            logger.error(f"[异步思考] 添加观点失败: {e}")
    
    def get_user_profile(self, user_id: str):
        """获取用户资料"""
        return self.experience_bank.get_user_profile(user_id)
    
    def get_growth_summary(self):
        """获取成长摘要"""
        return self.experience_bank.get_growth_summary()
