# -*- coding: utf-8 -*-
"""
拟人化角色行为系统插件 (Realistic Persona Plugin)
整合了情绪感知、生活模拟、QQ空间日记、AI配图等功能
"""

import asyncio
import random
import time
from pathlib import Path
from typing import Optional, Dict, List, cast
from datetime import datetime

import aiohttp
import json

from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, StarTools
from astrbot.api.message_components import Plain, Image, BaseMessageComponent
from astrbot.core import AstrBotConfig
from astrbot.core.config.default import VERSION
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_platform_adapter import AiocqhttpAdapter
from astrbot.core.utils.astrbot_path import get_astrbot_data_path
from astrbot.core.utils.version_comparator import VersionComparator

# 导入子模块
try:
    import pillowmd
    PILLOWMD_AVAILABLE = True
except ImportError:
    PILLOWMD_AVAILABLE = False
    logger.warning("pillowmd 未安装，部分渲染功能将不可用")

# 导入情绪和事件模块
from .emotions import EmotionAnalyzer, EmotionContext, EmotionType
from .context_events import (
    EventTrigger, EventType, ContextEvent,
    ProactiveMessageManager, ContextState
)

# 导入本地数据管理模块
from .core.local_data_manager import LocalDataManager
from .core.thought_engine import ThoughtEngine
from .core.experience_bank import ExperienceBank
from .core.async_thinking_scheduler import AsyncThinkingScheduler
from .core.psychology_engine import PsychologyEngine
from .core.memory_manager import MemoryManager
from .core.timeline_verifier import TimelineVerifier
from .core.profile_manager import ProfileManager
from .core.personality_evolution import PersonalityEvolutionManager

# 导入QQ空间核心模块（如果可用）
try:
    from .core.llm_action import LLMAction
    from .core.operate import PostOperator
    from .core.qzone_api import Qzone
    from .core.scheduler import AutoPublish
    from .core.utils import get_image_urls
    QZONE_AVAILABLE = True
except ImportError as e:
    QZONE_AVAILABLE = False
    logger.warning(f"QQ空间模块未完全加载: {e}")


class Main(Star):
    """拟人化角色行为系统主类"""
    
    # 数据库版本
    DB_VERSION = 4

    def __init__(self, context: Context, config: Optional[dict] = None):
        super().__init__(context)
        self.context = context
        config = config or {}
        self.config = cast(dict, config)  # 类型注释：确保 config 是 dict 类型
        
        # 检查版本
        if not VersionComparator.compare_version(VERSION, "4.1.0") >= 0:
            raise Exception("AstrBot 版本过低, 请升级至 4.1.0 或更高版本")
        
        # ========== AI绘图配置 ==========
        self.api_key = config.get("api_key")
        self.model = config.get("model", "iic/sdxl-turbo")
        self.size = config.get("size", "1080x1920")
        self.api_url = config.get("api_url", "https://api.modelscope.com/api/")
        self.provider = config.get("provider", "ms")
        
        # ========== 情绪感知与事件配置 ==========
        self.enable_emotion_detection = config.get("enable_emotion_detection", True)
        self.enable_auto_selfie = config.get("enable_auto_selfie", False)
        self.selfie_trigger_chance = config.get("selfie_trigger_chance", 0.3)
        self.enable_proactive_messages = config.get("enable_proactive_messages", False)
        self.idle_greeting_delay = config.get("idle_greeting_delay", 600)
        self.enable_context_events = config.get("enable_context_events", True)
        self.llm_tool_enabled = config.get("llm_tool_enabled", True)
        
        # ========== 生活模拟与人设配置 ==========
        self.enable_life_simulation = config.get("enable_life_simulation", True)
        # 从系统获取人设，而不是使用插件配置的人设
        self.persona_name = config.get("persona_name", "她")  # 保留配置选项，但优先使用系统人设
        self.persona_profile = ""  # 将在运行时从系统获取
        self.schedule_hour = config.get("schedule_hour", 7)
        self.news_hour = config.get("news_hour", 7)  # 默认早上7点获取新闻
        self.weather_location = config.get("weather_location", "")
        self.news_topics = config.get("news_topics", ["科技", "生活方式", "兴趣相关话题"])
        
        # ========== QQ空间配置 ==========
        self.enable_qzone = config.get("enable_qzone", False)
        self.publish_cron = config.get("publish_cron", "")
        self.publish_times_per_day = config.get("publish_times_per_day", 1)  # 每天发说说次数
        self.publish_time_ranges = config.get("publish_time_ranges", ["9-12", "14-18", "19-22"])  # 发说说时间段
        self.insomnia_probability = config.get("insomnia_probability", 0.2)  # 失眠发说说概率
        self.diary_max_msg = config.get("diary_max_msg", 200)
        self.diary_prompt = config.get("diary_prompt", "")
        self.comment_prompt = config.get("comment_prompt", "")
        
        # ========== 初始化状态管理 ==========
        self.emotion_contexts: Dict[str, EmotionContext] = {}
        self.event_trigger = EventTrigger()
        self.proactive_manager = ProactiveMessageManager()
        self.context_state = ContextState()
        self.life_state: Dict[str, Dict] = {}
        self.favorability: Dict[str, float] = {}
        
        # Token优化：缓存天气和新闻数据
        self._weather_cache = {"data": "", "timestamp": 0}  # 缓存1小时
        self._news_cache = {"data": "", "date": ""}  # 每天缓存一次
        self._schedule_cache = {"data": "", "date": ""}  # 每天缓存一次
        
        # 初始化本地数据管理器
        data_dir = StarTools.get_data_dir("astrbot_plugin_realistic_persona") / "local_data"
        self.local_data_manager = LocalDataManager(data_dir)
        
        # 初始化异步思考系统
        self.enable_async_thinking = config.get("enable_async_thinking", True)
        self.thought_engine = None
        self.experience_bank = None
        self.async_thinking_scheduler = None
        self.psychology_engine = None
        self.memory_manager = None
        self.timeline_verifier = None
        self.profile_manager = None  # 个人资料管理器
        self.personality_evolution = None  # 人格演化管理器
        
        if self.enable_async_thinking:
            thought_dir = StarTools.get_data_dir("astrbot_plugin_realistic_persona") / "thoughts"
            exp_dir = StarTools.get_data_dir("astrbot_plugin_realistic_persona") / "experience"
            psych_dir = StarTools.get_data_dir("astrbot_plugin_realistic_persona") / "psychology"
            mem_dir = StarTools.get_data_dir("astrbot_plugin_realistic_persona") / "memory"
            timeline_dir = StarTools.get_data_dir("astrbot_plugin_realistic_persona") / "timeline"
            self.thought_engine = ThoughtEngine(thought_dir)
            self.experience_bank = ExperienceBank(exp_dir)
            self.psychology_engine = PsychologyEngine(psych_dir)
            self.memory_manager = MemoryManager(mem_dir)
            self.timeline_verifier = TimelineVerifier(timeline_dir)
            self.async_thinking_scheduler = AsyncThinkingScheduler(
                self.thought_engine,
                self.experience_bank
            )
            
            # 初始化人格演化系统
            evolution_dir = StarTools.get_data_dir("astrbot_plugin_realistic_persona") / "personality_evolution"
            self.personality_evolution = PersonalityEvolutionManager(evolution_dir)
            logger.info("人格演化系统已初始化")
        
        # 注册事件处理器
        self._register_event_handlers()
        
        # QQ空间相关
        if self.enable_qzone and QZONE_AVAILABLE:
            self._init_qzone_settings(config)
        
        if not self.api_key:
            logger.warning("API密钥未配置，部分功能将不可用")
    
    def _init_qzone_settings(self, config):
        """初始化QQ空间相关设置"""
        # pillowmd样式目录
        default_style_dir = (
            Path(get_astrbot_data_path()) / "plugins/astrbot_plugin_realistic_persona/default_style"
        )
        self.pillowmd_style_dir = config.get("pillowmd_style_dir") or default_style_dir
        
        # 缓存目录
        self.cache: Path = StarTools.get_data_dir("astrbot_plugin_realistic_persona") / "cache"
        self.cache.mkdir(parents=True, exist_ok=True)

    async def initialize(self):
        """插件激活时调用"""
        logger.info("拟人化角色行为系统插件正在加载...")
        
        # 启动异步思考循环
        if self.enable_async_thinking and self.async_thinking_scheduler:
            try:
                self.async_thinking_scheduler.start()
                logger.info("异步思考循环已启动")
            except Exception as e:
                logger.error(f"启动异步思考循环失败: {e}")
        
        # 初始化QQ空间相关设置
        if self.enable_qzone and QZONE_AVAILABLE:
            # 实例化pillowmd样式
            if PILLOWMD_AVAILABLE:
                try:
                    self.style = pillowmd.LoadMarkdownStyles(self.pillowmd_style_dir)
                except Exception as e:
                    logger.error(f"无法加载pillowmd样式：{e}")
            
            asyncio.create_task(self.initialize_qzone(wait_ws_connected=False))
        
        # 打印状态
        emotion_status = "开启" if self.enable_emotion_detection else "关闭"
        selfie_status = "开启" if self.enable_auto_selfie else "关闭"
        context_status = "开启" if self.enable_context_events else "关闭"
        life_sim_status = "开启" if self.enable_life_simulation else "关闭"
        qzone_status = "开启" if self.enable_qzone else "关闭"
        
        logger.info(f"情绪检测: {emotion_status}")
        logger.info(f"自动自拍: {selfie_status}")
        logger.info(f"上下文事件: {context_status}")
        logger.info(f"生活模拟: {life_sim_status}")
        logger.info(f"QQ空间功能: {qzone_status}")
        logger.info("拟人化角色行为系统插件加载完毕！")

    async def terminate(self):
        """插件停用时调用"""
        logger.info("拟人化角色行为系统插件正在卸载...")
            
        # 停止异步思考循环
        if self.enable_async_thinking and self.async_thinking_scheduler:
            try:
                self.async_thinking_scheduler.stop()
                logger.info("异步思考循环已停止")
            except Exception as e:
                logger.error(f"停止异步思考循环失败: {e}")
            
        # 停止主动消息调度器
        if self.proactive_manager:
            self.proactive_manager.stop_scheduler()
        
        # 清空情绪上下文
        self.emotion_contexts.clear()
        
        # 清理缓存
        self._weather_cache.clear()
        self._news_cache.clear()
        self._schedule_cache.clear()
        self.favorability.clear()
        self.life_state.clear()
        
        # 清理QQ空间相关资源
        if self.enable_qzone and QZONE_AVAILABLE:
            if hasattr(self, "qzone"):
                await self.qzone.terminate()
            if hasattr(self, "auto_publish"):
                await self.auto_publish.terminate()
        
        logger.info("拟人化角色行为系统插件已卸载")
    
    @filter.on_platform_loaded()
    async def on_platform_loaded(self):
        """平台加载完成时"""
        if self.enable_qzone and QZONE_AVAILABLE:
            asyncio.create_task(self.initialize_qzone(wait_ws_connected=True))
    
    async def initialize_qzone(self, wait_ws_connected: bool = False):
        """初始化QQ空间相关模块"""
        logger.info(f"[QQ空间] 开始初始化, wait_ws_connected={wait_ws_connected}")
        
        if not QZONE_AVAILABLE:
            logger.warning("[QQ空间] QZONE_AVAILABLE=False, 模块不可用")
            return
        
        logger.info("[QQ空间] 查找 aiocqhttp 客户端...")
        client = None
        for inst in self.context.platform_manager.platform_insts:
            if isinstance(inst, AiocqhttpAdapter):
                if client := inst.get_client():
                    logger.info(f"[QQ空间] 找到 aiocqhttp 客户端: {type(inst).__name__}")
                    break
        if not client:
            logger.warning("[QQ空间] 未找到 aiocqhttp 客户端，初始化终止")
            return
            
        # 等待 ws 连接完成
        if wait_ws_connected:
            ws_connected = asyncio.Event()
                
            @client.on_websocket_connection
            def _(_):
                ws_connected.set()
                
            try:
                await asyncio.wait_for(ws_connected.wait(), timeout=10)
            except asyncio.TimeoutError:
                logger.warning("等待 aiocqhttp WebSocket 连接超时")
            
        # 加载QQ空间模块
        logger.info("[QQ空间] 创建Qzone对象...")
        self.qzone = Qzone(client)
        logger.info("[QQ空间] Qzone对象创建完成")
                
        # llm内容生成器
        logger.info("[QQ空间] 创建LLMAction对象...")
        self.llm = LLMAction(self.context, self.config, client)  # type: ignore[arg-type]
        logger.info("[QQ空间] LLMAction对象创建完成")
                
        # 输出配置信息
        enable_qzone = self.config.get("enable_qzone", False)
        publish_times = self.config.get("publish_times_per_day", 0)
        insomnia_prob = self.config.get("insomnia_probability", 0)
        logger.info(f"[QQ空间] 配置: enable_qzone={enable_qzone}, publish_times_per_day={publish_times}, insomnia_probability={insomnia_prob}")
                
        # 创建PostOperator（手动命令和自动发布都需要）
        logger.info("[QQ空间] 创建PostOperator...")
        # 注意：db 参数为 None 是临时解决方案，实际运行时不会使用数据库功能
        self.operator = PostOperator(  # type: ignore[arg-type,call-arg]
            self.context, self.config, self.qzone, None, self.llm, self.style  # type: ignore[arg-type]
        )
        logger.info("[QQ空间] PostOperator创建完成")
        
        # 加载自动发说说模块（仅在启用时）
        if self.config.get("enable_qzone") and (self.config.get("publish_times_per_day", 0) > 0 or self.config.get("insomnia_probability", 0) > 0):
            logger.info("[QQ空间] 创建AutoPublish...")
            from .core.scheduler import AutoPublish
            self.auto_publish = AutoPublish(self.context, self.config, self.operator)  # type: ignore[arg-type]
            logger.info("[QQ空间] AutoPublish创建完成")
        else:
            logger.info("[QQ空间] 未启用自动发说说（enable_qzone=False 或 publish_times_per_day=0 且 insomnia_probability=0）")
        
        # 初始化个人资料管理器
        if self.config.get("enable_auto_profile_update", False):
            logger.info("[QQ空间] 创建ProfileManager...")
            profile_dir = StarTools.get_data_dir("astrbot_plugin_realistic_persona") / "profile"
            self.profile_manager = ProfileManager(self.context, self.config, profile_dir)
            logger.info("[QQ空间] 个人资料管理器已启用")
                
        logger.info("[QQ空间] 初始化完成！")
        logger.info(f"[QQ空间] 组件状态: qzone={'OK' if hasattr(self, 'qzone') else 'MISSING'}, llm={'OK' if hasattr(self, 'llm') else 'MISSING'}, operator={'OK' if hasattr(self, 'operator') else 'MISSING'}")
    
    # ========== 事件处理器注册 ==========
    
    def _register_event_handlers(self):
        """注册事件处理器"""
        self.event_trigger.register_handler(
            EventType.GREETING,
            self._handle_greeting_event
        )
        self.event_trigger.register_handler(
            EventType.TOPIC_CHANGE,
            self._handle_topic_change_event
        )
        self.event_trigger.register_handler(
            EventType.CONVERSATION_START,
            self._handle_conversation_start_event
        )
    
    async def _handle_greeting_event(self, event: ContextEvent):
        """处理问候事件"""
        logger.debug(f"检测到问候: {event.data.get('message')}")
    
    async def _handle_topic_change_event(self, event: ContextEvent):
        """处理话题切换事件"""
        logger.debug(f"话题切换: {event.data.get('old_topic')} -> {event.data.get('new_topic')}")
    
    async def _handle_conversation_start_event(self, event: ContextEvent):
        """处理对话开始事件"""
        logger.debug(f"对话开始: {event.data.get('message')}")
    
    # ========== 情绪与上下文处理 ==========
    
    def _get_emotion_context(self, session_id: str) -> EmotionContext:
        """获取或创建情绪上下文"""
        if session_id not in self.emotion_contexts:
            self.emotion_contexts[session_id] = EmotionContext()
        return self.emotion_contexts[session_id]
    
    async def _process_emotion_and_events(self, event: AstrMessageEvent) -> Optional[Dict]:
        """处理情绪分析和事件检测"""
        message = event.message_obj.message_str
        session_id = event.get_session_id()

        
        # 更新好感度
        self._update_favorability(event)
        
        result = {
            "emotion": None,
            "should_selfie": False,
            "selfie_prompt": None,
            "events": []
        }
        
        # 情绪检测
        if self.enable_emotion_detection:
            logger.debug("情绪检测已启用，开始分析...")
            emotion = EmotionAnalyzer.analyze_emotion(message)
            if emotion:
                result["emotion"] = emotion
                logger.info(f"检测到情绪: {emotion.value} 在会话 {session_id}")
                
                # 记录情绪
                emotion_context = self._get_emotion_context(session_id)
                emotion_context.add_emotion(emotion, message, time.time())
                
                # 检查是否应该自拍
                if self.enable_auto_selfie:
                    if EmotionAnalyzer.should_trigger_selfie(emotion, self.selfie_trigger_chance):
                        result["should_selfie"] = True
                        result["selfie_prompt"] = EmotionAnalyzer.get_selfie_prompt(emotion)
                        logger.info(f"触发自拍，情绪: {emotion.value}, 提示词: {result['selfie_prompt']}")
                
                # 自动修改个人资料（基于情绪变化）
                # 注意：只有 AiocqhttpMessageEvent 才有 bot 属性
                if self.profile_manager and isinstance(event, AiocqhttpMessageEvent):
                    asyncio.create_task(self._auto_update_profile_on_emotion(
                        bot=event.bot,  # type: ignore
                        emotion=emotion
                    ))
        else:
            logger.debug("情绪检测功能未启用")  # 终端日志
        
        # 检测明确的自拍请求
        if EmotionAnalyzer.detect_selfie_request(message):
            result["should_selfie"] = True
            if not result["selfie_prompt"]:
                result["selfie_prompt"] = f"一个友好可爱的{self.persona_name}自拍照，真人自拍，自然光线，日常装扮"
            logger.info(f"检测到明确的自拍请求，会话: {session_id}")
        
        # 上下文事件检测
        if self.enable_context_events:
            events = self.event_trigger.detect_event(message)
            result["events"] = events
            
            # 触发事件处理器
            for evt in events:
                logger.debug(f"触发事件: {evt.event_type.value}，数据: {evt.data}")
                await self.event_trigger.trigger_event(evt)
        else:
            logger.debug("上下文事件检测未启用")
        
        logger.debug(f"情绪分析完成，结果: {result['emotion'].value if result['emotion'] else '无'}, 自拍: {result['should_selfie']}")  # 终端日志
        return result
    
    async def _auto_update_profile_on_emotion(self, bot, emotion: EmotionType):
        """
        根据情绪自动更新个人资料
        
        Args:
            bot: aiocqhttp bot 实例
            emotion: 当前情绪
        """
        if not self.profile_manager:
            return
        
        try:
            # 获取人设
            persona_profile = ""
            try:
                persona_mgr = self.context.persona_manager
                default_persona = await persona_mgr.get_default_persona_v3()
                persona_profile = default_persona["prompt"] or ""
            except Exception:
                pass
            
            # 计算情绪强度（基于情绪类型）
            intensity_map = {
                EmotionType.EXCITED: 0.9,
                EmotionType.HAPPY: 0.6,
                EmotionType.SAD: 0.7,
                EmotionType.ANGRY: 0.8,
                EmotionType.SURPRISED: 0.7,
                EmotionType.ANXIOUS: 0.8,
                EmotionType.BORED: 0.4,
                EmotionType.CONFUSED: 0.5,
                EmotionType.CURIOUS: 0.6,
                EmotionType.CALM: 0.2
            }
            intensity = intensity_map.get(emotion, 0.5)
            
            # 尝试自动更新
            await self.profile_manager.auto_update_on_emotion_change(
                bot=bot,
                current_emotion=emotion,
                intensity=intensity,
                persona_profile=persona_profile
            )
        except Exception as e:
            logger.error(f"自动更新个人资料失败: {e}")
    
    def _update_favorability(self, event: AstrMessageEvent) -> None:
        """根据会话活动简单累计好感度"""
        try:
            session_id = event.get_session_id()
        except Exception:
            return
        current = self.favorability.get(session_id, 0.0)
        self.favorability[session_id] = current + 1.0
    
    # ========== LLM请求钩子 ==========
    
    @filter.on_llm_request()
    async def on_llm_request_handler(self, event: AstrMessageEvent, request, *args, **kwargs):
        """LLM 请求前处理：注入情绪信息与"生活模拟"上下文"""
        analysis: Optional[Dict] = None
        
        # 情绪与上下文事件分析
        if self.enable_emotion_detection:
            try:
                analysis = await self._process_emotion_and_events(event)
                if analysis and analysis.get("emotion"):
                    emotion = analysis["emotion"]
                    session_id = event.get_session_id()
                    emotion_context = self._get_emotion_context(session_id)
                    
                    # 将情绪信息添加到系统提示中
                    emotion_info = f"\n[当前检测到用户情绪: {emotion.value}]"
                    
                    # 获取情绪趋势
                    trend = emotion_context.get_emotion_trend()
                    if trend:
                        emotion_info += f"\n[情绪趋势: {trend}]"
                    
                    # 如果情绪符合条件，提示 AI 可以考虑生成图片（注：这里的自拍指真人自拍，不是AI生成）
                    if analysis.get("should_selfie"):
                        emotion_info += "\n[建议: 可以考虑使用 draw 工具生成一张真人自拍图片，表现当前情绪状态，保持真实感]"
                    
                    if hasattr(request, "system_prompt"):
                        if request.system_prompt:
                            request.system_prompt += emotion_info
                        else:
                            request.system_prompt = emotion_info
                    
                    # 将情绪信息储存到上下文状态
                    self.context_state.update_state(session_id, "last_emotion", emotion.value)
                    self.context_state.update_state(session_id, "emotion_analysis", analysis)
            except Exception as e:
                logger.error(f"情绪分析失败: {e}")
                # 即使情绪分析失败，也要确保不影响LLM请求
                pass
        
        # 生活模拟：根据日程、天气、新闻等构造额外系统提示
        if self.enable_life_simulation:
            try:
                life_info = await self._build_life_prompt_fragment(event, analysis)
                if life_info:
                    if hasattr(request, "system_prompt"):
                        if request.system_prompt:
                            request.system_prompt += "\n" + life_info
                        else:
                            request.system_prompt = life_info
            except Exception as e:
                logger.error(f"生活模拟上下文构建失败: {e}")
                # 即使生活模拟失败，也要确保不影响LLM请求
                pass
        
        # 记录用户交互到经历银行（异步思考系统）
        if self.enable_async_thinking and self.experience_bank and self.async_thinking_scheduler:
            try:
                user_message = event.message_obj.message_str
                session_id = event.get_session_id()
                        
                # 记录用户交互到经历银行
                # 注：此时还没有AI回复，会在之后的访问中更新
                self._record_interaction_async(session_id, user_message)
                        
                # 人格演化：每日例行检查
                if self.personality_evolution:
                    self.personality_evolution.daily_routine()
                        
            except Exception as e:
                logger.error(f"记录用户交互失败: {e}")
        
        # 确保函数返回None
        return None
    
    # ========== 经历累积辅助方法 ==========
        
    def _record_interaction_async(self, session_id: str, user_message: str) -> None:
        """记录用户交互到经历银行"""
        if not self.experience_bank:
            return
            
        try:
            # 记录对话
            self.experience_bank.record_conversation(
                user_id=session_id,
                user_message=user_message,
                bot_response="",  # 此时还没有AI回复
                session_id=session_id
            )
                
            # 从用户消息中提取技能、兴趣等，自动更新成長追蹤
            self._extract_and_update_growth(user_message)
                
            # 检测并记录长期项目
            self._detect_and_record_projects(user_message, session_id)
                
            # 检测并记录承诺
            self._detect_and_record_promises(user_message, session_id)
                
            # 记录生物钟状态
            self._record_circadian_state()
            
            # 执行关系网络智能压缩（每30次交互执行一次）
            if self.experience_bank and abs(hash(session_id)) % 30 == 0:
                self._analyze_relationship_network(session_id)
                        
            # 更新心理引擎（内在驱动力、情绪、价值观）
            if self.psychology_engine:
                # 记录互动（满足连接需求）
                self.psychology_engine.record_interaction()
                            
                # 检测是否感到孤独或新增需求互动
                connection_check = self.psychology_engine.check_connection_need()
                if connection_check.get("feels_lonely"):
                    logger.debug("[PSYCHOLOGY] 新增需求互动")
                        
            # 记忆管理（优先级权量、琐碎淘汰）
            if self.memory_manager:
                # 记录此次对话，自动计算重要性
                context_clues = []
                if "记得" in user_message or "求你" in user_message:
                    context_clues.append("需要记录")
                
                self.memory_manager.record_weighted_conversation(
                    user_id=session_id,
                    user_message=user_message,
                    bot_response="",  # 此时还没有回复
                    context_clues=context_clues,
                    session_id=session_id
                )
                
                # 自动应用记忆衰减 (每30次交互执行一次)
                if abs(hash(session_id)) % 30 == 0:
                    logger.debug("[记忆管理] 执行记忆衰减")
                    self.memory_manager.apply_memory_decay(days_threshold=30)
            
            # 时间线验证 - 验证经历的时间一致性
            if self.timeline_verifier:
                # 找到用户提及的时间信息
                time_markers = ["上月", "上周", "去年", "是日", "昨天"]
                mentioned_time = None
                for marker in time_markers:
                    if marker in user_message:
                        mentioned_time = marker
                        break
                
                # 如果检测到时间信息，验证更新时间线
                if mentioned_time:
                    self.timeline_verifier.add_experience(
                        experience_id=f"{session_id}_{datetime.now().timestamp()}",
                        content=user_message[:100],
                        event_date=mentioned_time,
                        event_type="conversation"
                    )
                
            logger.debug(f"用户交互已记录: {session_id}")
                
        except Exception as e:
            logger.debug(f"记录用户交互失败: {e}")
        
    def _extract_and_update_growth(self, message: str) -> None:
        """从用户消息中提取兴趣、技能等，自动更新成長追蹤"""
        if not self.experience_bank:
            return
            
        try:
            message_lower = message.lower()
                    
            # 检测技能
            for skill in ["python", "java", "javascript", "c++", "latex"]:
                if skill.lower() in message_lower:
                    self.experience_bank.update_growth("skills", skill)
                    
            # 检测兴趣
            for interest in ["编程", "旅游", "音乐", "电影", "游戏"]:
                if interest in message:
                    self.experience_bank.update_growth("interests", interest)
                
            # 检测观点
            if "成长" in message or "加油" in message:
                self.experience_bank.update_growth("views", "乐观向上")
            if "伤心" in message or "难过" in message:
                self.experience_bank.update_growth("views", "需要陪伴")
            
        except Exception as e:
            logger.debug(f"提取成長信息失败: {e}")
        
    def _detect_and_record_projects(self, message: str, session_id: str) -> None:
        """检测并记录长期项目进展"""
        if not self.experience_bank:
            return
            
        try:
            # 检测上月、上周等的时间前缀
            if "上月" in message or "上周" in message:
                # 検测项目完成
                if "学完" in message or "学了" in message or "学习" in message:
                    project = self._extract_project_name(message)
                    if project:
                        self.experience_bank.record_project(
                            project_name=project,
                            description=f"用户提及：{message[:100]}",
                            status="in_progress",
                            metadata={"user_id": session_id}
                        )
                        logger.debug(f"项目已记录: {project}")
            
        except Exception as e:
            logger.debug(f"検测项目失败: {e}")
        
    def _detect_and_record_promises(self, message: str, session_id: str) -> None:
        """检测并记录承诺
            
        检测样式：
        - "上次答应..." → 完成承诺
        - "记得..." → 新建承诺
        """
        if not self.experience_bank:
            return
            
        try:
            # 检测承诺完成
            completion_keywords = ["完成", "完成了", "做了", "已经", "成功"]
            if any(kw in message for kw in completion_keywords):
                # 提取承诺描述
                promise_desc = self._extract_promise_description(message)
                if promise_desc:
                    self.experience_bank.complete_promise(
                        promise_keyword=promise_desc[:30],
                        completion_note=f"用户提及: {message[:80]}"
                    )
                    logger.debug(f"承诺已标记为完成: {promise_desc}")
                
            # 检测新承诺
            if "记得" in message or "答应" in message or "承诺" in message:
                promise_desc = self._extract_promise_description(message)
                if promise_desc:
                    self.experience_bank.record_promise(
                        promise=promise_desc,
                        related_user_id=session_id,
                        metadata={"mentioned_in_message": message[:100]}
                    )
                    logger.debug(f"承诺已记录: {promise_desc}")
            
        except Exception as e:
            logger.debug(f"検测承诺失败: {e}")
        
    def _extract_project_name(self, message: str) -> Optional[str]:
        """从消息中提取项目名称"""
        # 提取消息中第一个先前出现的中文词语或短语句
        keywords = ["课程", "书籍", "作品", "项目"]
        for kw in keywords:
            if kw in message:
                # 返回第一个100字以内的描述
                idx = message.find(kw)
                return message[max(0, idx-10):min(len(message), idx+30)].strip()
        return None
        
    def _extract_promise_description(self, message: str) -> Optional[str]:
        """从消息中提取承诺描述"""
        # 简单的提取逻辑，一般是消息的前100个字
        return message[:100].strip() if len(message) > 0 else None
        
    def _record_circadian_state(self) -> None:
        """根据当前时间记录生物钟状态"""
        if not self.experience_bank:
            return
            
        try:
            now = datetime.now()
            hour = now.hour
                
            # 根据时刻判断当前时段
            if 6 <= hour < 9:
                state = "清晨"
                energy = 6
                creativity = 7
            elif 9 <= hour < 12:
                state = "上午"
                energy = 8
                creativity = 8
            elif 12 <= hour < 14:
                state = "中午"
                energy = 5
                creativity = 4
            elif 14 <= hour < 18:
                state = "下午"
                energy = 7
                creativity = 7
            elif 18 <= hour < 21:
                state = "晚晨"
                energy = 6
                creativity = 6
            else:
                state = "夜晨"
                energy = 4
                creativity = 5
                
            # 随机变化一些
            energy += random.randint(-2, 2)
            creativity += random.randint(-2, 2)
            mood = random.choice(["开心", "中性", "沮丧"])
                
            self.experience_bank.record_circadian_state(state, energy, creativity, mood)
                
        except Exception as e:
            logger.debug(f"记录生物钟失败: {e}")
    
    def _analyze_relationship_network(self, user_id: str) -> None:
        """
        执行关系网络的智能压缩
        提取关系里程碑和生成个性化特征描述
        """
        if not self.experience_bank:
            return
        
        try:
            # 提取关系里程碑(最多10个)
            milestones = self.experience_bank.extract_relationship_milestones(user_id, max_milestones=10)
            
            if milestones:
                logger.debug(f"[关系网络] 提取事件: {len(milestones)}个")
            
            # 生成个性化关系特征描述
            profile = self.experience_bank.generate_relationship_profile(user_id)
            
            if profile:
                logger.debug(f"[关系网络] 特征: {profile.get('relationship_characteristics')}")
        
        except Exception as e:
            logger.debug(f"[关系网络] 分析失败: {e}")
    
    def _get_provider_id(self) -> Optional[str]:
        """获取当前使用的 LLM 提供者 ID"""
        try:
            provider = self.context.get_using_provider()
            if provider:
                meta = provider.meta()
                return getattr(meta, "id", None)
        except Exception:
            return None
        return None
    
    async def _maybe_generate_schedule(self, now: datetime) -> str:
        """在需要时生成当天的日程（使用本地数据管理器优化）"""
        today_str = now.strftime("%Y-%m-%d")
        
        # 首先尝试从本地数据管理器获取
        cached_schedule = self.local_data_manager.get_schedule_data(today_str)
        if cached_schedule:
            logger.info(f"从本地数据获取 {today_str} 的日程信息")
            # 更新缓存
            self._schedule_cache = {"data": cached_schedule, "date": today_str}
            return cached_schedule
        
        # 检查缓存
        if self._schedule_cache["date"] == today_str and self._schedule_cache["data"]:
            logger.debug(f"使用缓存的日程: {today_str}")
            return self._schedule_cache["data"]
            
        if now.hour < self.schedule_hour:
            logger.debug(f"当前时间 {now.hour} 小于日程生成时间 {self.schedule_hour}，跳过生成")
            return ""
            
        # 从系统获取人设
        persona_profile = await self._get_system_persona_profile()
        logger.debug(f"获取系统人设成功，长度: {len(persona_profile)} 字符")
            
        provider_id = self._get_provider_id()
        if not provider_id:
            logger.warning("未找到可用的LLM提供者，无法生成日程")
            return self._build_fallback_schedule(today_str)
            
        schedule_text = ""
        # 生成详细的日程和穿着，特别强调天气对穿搭的影响
        weather_desc = await self._get_weather_desc()
        weather_hint = ""
        if weather_desc:
            weather_hint = f"当地天气：{weather_desc}。请根据天气选择合适的穿着（例如：下雨带伞、寒冷穿厚衣、热天穿薄衣）。\n"
        else:
            weather_hint = "请根据当剋季节和常规天气选择合适的穿着。\n"
            
        prompt = (
            f"你是{self.persona_name}，{persona_profile}。\n"
            f"今天是{today_str}。\n"
            f"{weather_hint}\n"
            "请详细规划今天的生活：\n\n"
            "1. 今日穿搭：根据人设、当地天气和今天的活动，描述具体穿着（上衣、下装、鞋子、外套/配饰等），必须符合天气情况、角色性格和身份\n"
            "2. 早上（6:00-9:00）：起床时间、洗漱、早餐、出门准备等具体活动\n"
            "3. 上午（9:00-12:00）：主要活动（工作/上课/其他），具体在做什么\n"
            "4. 中午（12:00-14:00）：午餐地点和内容、午休安排\n"
            "5. 下午（14:00-18:00）：下午的具体安排和活动\n"
            "6. 前晚（18:00-20:00）：晚餐、休闲活动\n"
            "7. 晚上（20:00-23:00）：娱乐、学习、社交等活动\n"
            "8. 睡前（23:00-24:00）：洗漱、放松、睡觉准备\n\n"
            "要求：口语化表达，贴近真实人类生活，不要提到AI。每个时段1-2句话即可。"
        )
            
        logger.info(f"开始生成 {today_str} 的日程")
        try:
            resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
            )
            schedule_text = (resp.completion_text or "").strip()
            logger.info(f"日程生成成功，长度: {len(schedule_text)} 字符")
        except Exception as e:
            logger.error(f"生成日程失败: {e}")
            # 尝试使用更简化的提示词再次生成
            try:
                simple_prompt = f"为{self.persona_name}规划{today_str}的简单日程，包含穿搭和主要活动。"
                resp = await self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=simple_prompt,
                )
                schedule_text = (resp.completion_text or "").strip()
                if schedule_text:
                    logger.info(f"使用简化提示词生成日程成功，长度: {len(schedule_text)} 字符")
                else:
                    logger.warning("简化提示词也无法生成日程")
                    schedule_text = self._build_fallback_schedule(today_str)
            except Exception as e2:
                logger.error(f"简化提示词生成日程也失败: {e2}")
                schedule_text = self._build_fallback_schedule(today_str)
                
        if not schedule_text:
            schedule_text = self._build_fallback_schedule(today_str)
            
        # 更新缓存
        self._schedule_cache = {"data": schedule_text, "date": today_str}
        
        # 保存到本地数据管理器
        self.local_data_manager.save_schedule_data(today_str, schedule_text)
        
        return schedule_text
    
    async def _maybe_fetch_news(self, now: datetime) -> str:
        """在需要时获取角色关注的早间新闻（使用本地数据管理器优化）"""
        today_str = now.strftime("%Y-%m-%d")
        
        # 首先尝试从本地数据管理器获取
        cached_news = self.local_data_manager.get_news_data(today_str)
        if cached_news:
            logger.info(f"从本地数据获取 {today_str} 的新闻信息")
            # 更新缓存
            self._news_cache = {"data": cached_news, "date": today_str}
            return cached_news
        
        # 检查缓存
        if self._news_cache["date"] == today_str and self._news_cache["data"]:
            logger.debug(f"使用缓存的新闻: {today_str}")
            return self._news_cache["data"]
        
        if now.hour < self.news_hour:
            logger.debug(f"当前时间 {now.hour} 小于新闻获取时间 {self.news_hour}，跳过获取")
            return ""
        
        provider_id = self._get_provider_id()
        if not provider_id:
            logger.warning("未找到可用的LLM提供者，无法获取新闻")
            return ""
        
        news_text = ""
        topics = ", ".join(self.news_topics)
        # Token优化：精简提示词
        prompt = (
            f"联网搜索{today_str}早间新闻，关注{topics}，"
            f"列出3条标题+简述。"
        )
        
        logger.info(f"开始获取 {today_str} 的早间新闻")
        try:
            resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
            )
            news_text = (resp.completion_text or "").strip()
            
            if not news_text or len(news_text) < 20:
                logger.warning("LLM未能成功获取新闻，可能是联网工具未启用")
                news_text = ""
            else:
                logger.info(f"新闻获取成功，长度: {len(news_text)} 字符")
        except Exception as e:
            logger.error(f"获取新闻失败: {e}")
            news_text = ""
        
        # 更新缓存
        self._news_cache = {"data": news_text, "date": today_str}
        
        # 保存到本地数据管理器
        if news_text:
            self.local_data_manager.save_news_data(today_str, news_text)
        
        return news_text
    
    async def _get_weather_desc(self) -> str:
        """获取简单的本地天气描述（使用本地数据管理器优化）"""
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        
        if not self.weather_location:
            logger.debug("未配置天气位置，跳过天气查询")
            return ""
        
        # 首先尝试从本地数据管理器获取
        cached_weather = self.local_data_manager.get_weather_data(today_str)
        if cached_weather:
            logger.info(f"从本地数据获取 {today_str} 的天气信息")
            # 更新内存缓存
            current_time = time.time()
            self._weather_cache = {"data": cached_weather, "timestamp": current_time}
            return cached_weather
        
        # 检查内存缓存（1小时内有效）
        current_time = time.time()
        if self._weather_cache["data"] and (current_time - self._weather_cache["timestamp"]) < 3600:
            logger.debug(f"使用内存缓存的天气数据: {self._weather_cache['data']}")
            return self._weather_cache["data"]
        
        weather_text = ""
        
        # 优先使用wttr.in获取实时天气
        try:
            async with aiohttp.ClientSession() as session:
                url = f"https://wttr.in/{self.weather_location}?format=3&lang=zh-cn"
                async with session.get(url, timeout=5) as resp:
                    if resp.status == 200:
                        weather_text = (await resp.text()).strip()
                        # 检查返回的是否是有效的天气信息
                        if weather_text and "抱歉" not in weather_text and "无法" not in weather_text and "未知" not in weather_text:
                            logger.info(f"通过wttr.in获取天气成功: {weather_text}")
                        else:
                            weather_text = ""
        except Exception as e:
            logger.debug(f"通过wttr.in获取天气失败: {e}")
        
        # 如果wttr.in失败，尝试使用LLM的天气工具
        if not weather_text:
            provider_id = self._get_provider_id()
            if provider_id:
                try:
                    # Token优化：精简提示词
                    prompt = f"查询{self.weather_location}天气，仅返回简要描述。"
                    logger.info(f"开始查询 {self.weather_location} 的天气")
                    resp = await self.context.llm_generate(
                        chat_provider_id=provider_id,
                        prompt=prompt,
                    )
                    weather_text = (resp.completion_text or "").strip()
                    # 检查返回的是否是有效的天气信息
                    if weather_text and "抱歉" not in weather_text and "无法" not in weather_text and "未知" not in weather_text:
                        logger.info(f"天气查询成功: {weather_text}")
                    else:
                        weather_text = ""
                except Exception as e:
                    logger.debug(f"使用天气工具获取天气失败: {e}")
        
        # 更新缓存和本地数据
        if weather_text:
            self._weather_cache = {"data": weather_text, "timestamp": current_time}
            # 保存到本地数据管理器
            self.local_data_manager.save_weather_data(today_str, weather_text)
            
            # 更新异步思考调度器的天气信息
            if self.enable_async_thinking and self.async_thinking_scheduler:
                try:
                    self.async_thinking_scheduler.set_weather(weather_text)
                    logger.debug(f"天气信息已更新到调度器: {weather_text}")
                except Exception as e:
                    logger.debug(f"更新天气信息到调度器失败: {e}")
        
        return weather_text or ""
    
    def _get_current_activity(self, now: datetime) -> str:
        """根据时间段粗略推断当前生活活动"""
        h = now.hour
        if h < 6 or h >= 23:
            return "已经睡觉或准备睡觉，不太方便频繁看手机"
        if 6 <= h < 9:
            return "刚起床不久，在洗漱、吃早饭或者路上通勤"
        if 9 <= h < 12:
            return "在认真上班/上课/学习，处理中午前需要完成的任务"
        if 12 <= h < 14:
            return "吃午饭、午休或刷手机放松一会儿"
        if 14 <= h < 18:
            return "继续忙工作/学习，中间会偶尔看看消息但回复不一定及时"
        if 18 <= h < 21:
            return "吃晚饭、和朋友聊天、追剧或做一些轻松的娱乐活动"
        return "准备洗漱和收尾今天的事情，一边刷手机一边慢慢放松"
    
    def _build_fallback_schedule(self, today_str: str) -> str:
        """在 LLM 不可用时的兜底日程模板"""
        return (
            f"{today_str} 的日程：\n\n"
            "今日穿搭：休闲舒适的日常装扮。\n"
            "早上：7:00起床洗漱，简单吃点早餐，整理一下今天要用的东西。\n"
            "上午：处理一些需要专注的任务，中途喝杯水休息一下。\n"
            "中午：吃个简单的午餐，午休放松半小时。\n"
            "下午：继续工作/学习，适当活动活动身体。\n"
            "傍晚：吃晚饭，出去散散步或者做点轻松的事情。\n"
            "晚上：追剧、玩游戏或者和朋友聊天，放松一下。\n"
            "睡前：洗漱，看看明天的计划，23:00左右睡觉。\n"
        )
    
    async def _get_system_persona_profile(self) -> str:
        """从系统获取人设描述"""
        try:
            # 使用系统的人设管理器获取默认人设
            default_persona = await self.context.persona_manager.get_default_persona_v3()
            return default_persona["prompt"] or f"一个普通的年轻人，有自己的日程、情绪和兴趣，会像真人一样安排每天的生活。"
        except Exception as e:
            logger.warning(f"获取系统人设失败: {e}，使用默认人设")
            return "一个普通的年轻人，有自己的日程、情绪和兴趣，会像真人一样安排每天的生活。"
    
    async def _build_life_prompt_fragment(
        self,
        event: AstrMessageEvent,
        analysis: Optional[Dict],
    ) -> str:
        """构造注入到 system_prompt 中的"生活模拟"信息片段（优化版）"""
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        
        # 检查是否已缓存当天的生活数据
        if not hasattr(self, '_cached_life_data') or self._cached_life_data.get('date') != today_str:
            # 缓存当天的数据
            self._cached_life_data = {
                'date': today_str,
                'schedule': await self._maybe_generate_schedule(now),
                'news': await self._maybe_fetch_news(now),
                'weather': await self._get_weather_desc(),
                'persona': await self._get_system_persona_profile(),
            }
        
        # 使用缓存的数据
        schedule_text = self._cached_life_data['schedule']
        news_text = self._cached_life_data['news']
        weather_desc = self._cached_life_data['weather']
        persona_profile = self._cached_life_data['persona']
        current_activity = self._get_current_activity(now)
        
        last_emotion = None
        if analysis and analysis.get("emotion"):
            last_emotion = analysis["emotion"].value
        
        # 提取今日穿搭信息（用于图片生成一致性）
        outfit = ""
        if schedule_text and "今日穿搭" in schedule_text:
            # 提取穿搭描述
            lines = schedule_text.split("\n")
            for line in lines:
                if "今日穿搭" in line or "穿搭" in line or "穿着" in line:
                    outfit = line.replace("今日穿搭：", "").replace("穿搭：", "").strip()
                    break
        
        # 构建系统提示
        parts: List[str] = []
        parts.append(f"[人设]{persona_profile}")
        parts.append(f"[时间]{today_str} {now.strftime('%H:%M')}")
        
        if weather_desc:
            parts.append(f"[天气]{weather_desc}")
        
        if schedule_text:
            parts.append(f"[日程]\n{schedule_text}")
        
        parts.append(f"[状态]{current_activity}")
        
        if last_emotion:
            parts.append(f"[心情]{last_emotion}")
        
        # 只在有新闻时添加
        if news_text:
            parts.append(f"[新闻]{news_text}")
        
        # 添加穿搭信息用于保持一致性
        if outfit:
            parts.append(f"[今日穿搭]{outfit}")
        
        # 精简指导语
        parts.append("以真人视角回复，体现当前状态。")
        
        # 图片生成一致性指导
        if outfit:
            parts.append(
                f"[重要]如果调用draw工具生成图片，人物必须穿着：{outfit}，"
                "并且场景要符合当前日程活动，保持角色形象一致性。"
            )
        
        return "\n".join(parts)
    
    # ========== AI绘图功能 ==========
    
    async def _request_modelscope(self, prompt: str, size: str, session: aiohttp.ClientSession) -> str:
        """向ModelScope API发送请求"""
        common_headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        current_seed = random.randint(1, 2147483647)
        payload = {
            "model": f"{self.model}",
            "prompt": prompt,
            "seed": current_seed,
            "size": size,
            "num_inference_steps": "30",
        }
        
        async with session.post(
            f"{self.api_url}v1/images/generations",
            headers={**common_headers, "X-ModelScope-Async-Mode": "true"},
            data=json.dumps(payload, ensure_ascii=False).encode('utf-8')
        ) as response:
            response.raise_for_status()
            task_response = await response.json()
            task_id = task_response.get("task_id")
            
            if not task_id:
                raise Exception("未能获取任务ID，生成图片失败。")
        
        # 使用指数退避策略轮询结果
        delay = 1
        max_delay = 10
        while True:
            async with session.get(
                f"{self.api_url}v1/tasks/{task_id}",
                headers={**common_headers, "X-ModelScope-Task-Type": "image_generation"},
            ) as result_response:
                result_response.raise_for_status()
                data = await result_response.json()
                
                task_status = data.get("task_status")
                if task_status == "SUCCEED":
                    output_images = data.get("output_images", [])
                    if output_images:
                        return output_images[0]
                    else:
                        raise Exception("图片生成成功但未返回图片URL。")
                elif task_status == "FAILED":
                    raise Exception("图片生成失败。")
                
                # 指数退避策略
                await asyncio.sleep(delay)
                delay = min(delay * 2, max_delay)
    
    async def _request_image(self, prompt: str, size: str) -> str:
        """根据配置的提供商发起请求，返回图片URL"""
        try:
            if not prompt:
                raise ValueError("请提供提示词！")
            
            async with aiohttp.ClientSession() as session:
                if self.provider.lower() in ["ms", "modelscope"]:
                    return await self._request_modelscope(prompt, size, session)
                else:
                    raise ValueError(f"不支持的提供商: {self.provider}")
        
        except aiohttp.ClientError as e:
            raise Exception(f"网络请求失败: {str(e)}")
        except json.JSONDecodeError as e:
            raise Exception(f"解析API响应失败: {str(e)}")
        except Exception as e:
            raise e
    
    @filter.llm_tool(name="draw")
    async def draw(self, event: AstrMessageEvent, prompt: str, size: str = "1080x1920"):
        '''根据提示词生成图片，支持AI自拍和情绪表达
        
        Args:
            prompt(string): 图片提示词，应包含主体、场景、风格等必要信息。例如："一个开心微笑的中国女孩，真实风格，明亮色彩"
            size(string): 图片尺寸，默认为1080x1920。可选项：1920x1024（横屏）、1024x1024（方形）等
        '''
        
        logger.info(f"[绘图工具] 被调用 - prompt: {prompt[:50]}..., size: {size}")
        logger.info(f"[绘图工具] 配置状态 - llm_tool_enabled: {self.llm_tool_enabled}, api_key存在: {bool(self.api_key)}")
        
        if not self.llm_tool_enabled:
            logger.warning("[绘图工具] 被禁用，无法生成图片")
            return "绘图工具已被禁用"
        
        if not self.api_key:
            logger.warning("[绘图工具] API密钥未配置，无法生成图片")
            return "API密钥未配置，无法生成图片"
        
        try:
            # 获取当前会话的情绪上下文
            session_id = event.get_session_id()
            emotion_analysis = self.context_state.get_state(session_id, "emotion_analysis")
            
            # 如果有情绪信息，优化提示词
            if emotion_analysis and emotion_analysis.get("emotion"):
                emotion = emotion_analysis["emotion"]
                logger.debug(f"检测到情绪: {emotion.value}, 生成图片: {prompt}")
            
            logger.info(f"[绘图工具] 开始请求图片生成...")
            # 发送图片生成请求
            image_url = await self._request_image(prompt, size)
            logger.info(f"[绘图工具] 图片生成成功: {image_url}")
            
            # 构造并发送图片消息给用户（只发送图片，不加任何文字）
            chain: List[BaseMessageComponent] = [
                Image.fromURL(image_url)
            ]
            
            logger.info(f"[绘图工具] 发送图片给用户...")
            # 发送消息给用户（在后台发送，不返回给LLM）
            await event.send(event.chain_result(chain))
            logger.info(f"[绘图工具] 图片已发送")
            
            # 返回给 LLM 的指示：让它生成自然的文字回复
            # 根据用户偏好：多模态响应必须附带文字说明
            return (
                f"图片已发送给用户。\n"
                f"图片内容：{prompt}\n\n"
                f"请不要重复描述图片内容，而是根据当前场景和情境，"
                f"用第一人称自然地表达你此刻的感受、心情或想法。\n"
                f'例如：“发你了，江边风景真的很好，风也舒服。”'
            )
        
        except Exception as e:
            error_msg = f"生成图片时遇到问题: {str(e)}"
            logger.error(f"[绘图工具] 失败: {error_msg}")
            # 发送错误信息给用户
            await event.send(event.plain_result(error_msg))
            return f"图片生成失败：{str(e)}"
    
    # ========== 命令处理器 ==========
    
    @filter.command("aiimg")
    async def generate_image_command(self, event: AstrMessageEvent):
        """命令方式生成图片"""
        full_message = event.message_obj.message_str
        parts = full_message.split(" ", 1)
        prompt = parts[1].strip() if len(parts) > 1 else ""
        
        if not prompt:
            yield event.plain_result("请提供提示词！使用方法：/aiimg <提示词>")
            return
        
        if not self.api_key:
            yield event.plain_result("API密钥未配置，无法生成图片")
            return
        
        try:
            image_url = await self._request_image(prompt, self.size)
            chain: List[BaseMessageComponent] = [
                Plain(f"提示词：{prompt}\n"),
                Image.fromURL(image_url)
            ]
            yield event.chain_result(chain)
        except Exception as e:
            yield event.plain_result(f"生成图片失败: {str(e)}")
    
    @filter.command("emotion_status")
    async def check_emotion_status(self, event: AstrMessageEvent):
        """查看当前情绪状态"""
        if not self.enable_emotion_detection:
            yield event.plain_result("情绪检测功能未启用")
            return
        
        session_id = event.get_session_id()
        emotion_context = self._get_emotion_context(session_id)
        
        recent_emotion = emotion_context.get_recent_emotion()
        trend = emotion_context.get_emotion_trend()
        
        if recent_emotion:
            status = f"当前情绪: {recent_emotion.value}"
            if trend:
                status += f"\n情绪趋势: {trend}"
            status += f"\n情绪历史记录数: {len(emotion_context.emotion_history)}"
        else:
            status = "暂无情绪数据"
        
        yield event.plain_result(status)
    
    @filter.command("personality_status")
    async def check_personality_status(self, event: AstrMessageEvent):
        """查看人格演化状态"""
        if not self.enable_async_thinking or not self.personality_evolution:
            yield event.plain_result("人格演化系统未启用")
            return
        
        try:
            summary = self.personality_evolution.get_personality_summary()
            
            # 将阶段名称移出 f-string 表达式
            phase_name = '稳定期' if summary['current_phase'] == 'stable' else '变化期'
            
            status = f"""🌱 人格演化状态

💬 表达能力：
- 词汇水平: {summary['expression_levels']['vocabulary']}/10
- 幽默成熟度: {summary['expression_levels']['humor']}/10
- 句式复杂度: {summary['expression_levels']['complexity']}/10

🔄 当前阶段: {summary['current_phase']}
({phase_name})

❤️ 核心习惯：
{chr(10).join('- ' + h for h in summary['core_habits'][:3])}

🌟 临时习惯：
{chr(10).join('- ' + h for h in summary['temporary_habits'])}
            """
            
            yield event.plain_result(status)
        except Exception as e:
            yield event.plain_result(f"获取人格状态失败: {str(e)}")
    
    # ========== QQ空间相关命令（仅在启用时可用）==========
    
    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("发说说")
    async def publish_feed(self, event: AiocqhttpMessageEvent):
        """发说说 <内容> <图片>, 由用户指定内容"""
        if not self.enable_qzone or not QZONE_AVAILABLE:
            await event.send(event.plain_result("QQ空间功能未启用"))
            return
        
        # 检查模块是否初始化完成
        if not hasattr(self, 'operator'):
            await event.send(event.plain_result("QQ空间模块初始化中，请稍后重试"))
            logger.warning(f"[发说说] 命令被调用，但QQ空间模块尚未初始化完成 - operator={'MISSING' if not hasattr(self, 'operator') else 'OK'}, llm={'MISSING' if not hasattr(self, 'llm') else 'OK'}")
            return
        
        from .core.utils import get_image_urls
        text = event.message_str.partition(" ")[2]
        images = await get_image_urls(event)
        
        # 直接发布说说，不保存草稿
        await self.operator.publish_feed(event=event, text=text, images=images)
    
    @filter.command("写说说", alias={"写稿", "写草稿"})
    async def write_draft(self, event: AiocqhttpMessageEvent, topic: str | None = None):
        """写说说 <主题> <图片>, 由AI生成说说内容并自动配图"""
        if not self.enable_qzone or not QZONE_AVAILABLE:
            await event.send(event.plain_result("QQ空间功能未启用"))
            return
        
        # 检查模块是否初始化完成
        if not hasattr(self, 'llm') or not hasattr(self, 'operator'):
            await event.send(event.plain_result("QQ空间模块初始化中，请稍后重试"))
            logger.warning(f"[写说说] 命令被调用，但QQ空间模块尚未初始化完成 - operator={'MISSING' if not hasattr(self, 'operator') else 'OK'}, llm={'MISSING' if not hasattr(self, 'llm') else 'OK'}")
            return
        
        from .core.utils import get_image_urls
        
        # 使用LLM生成说说内容
        text = await self.llm.generate_diary(group_id=event.get_group_id(), topic=topic)
        
        # 获取用户上传的图片
        images = await get_image_urls(event)
        
        # 如果没有图片，自动生成配图
        if not images:
            logger.info(f"[写说说] 没有上传图片，开始自动生成配图...")
            try:
                # 生成图片提示词
                image_prompt = await self.llm.generate_image_prompt_from_diary(text)
                if image_prompt:
                    logger.info(f"[写说说] 生成的配图提示词: {image_prompt}")
                    # 调用ModelScope生图
                    image_url = await self.llm._request_modelscope(image_prompt)
                    if image_url:
                        images = [image_url]
                        logger.info(f"[写说说] 配图生成成功: {image_url}")
                    else:
                        logger.warning("[写说说] 配图生成失败，ModelScope未返回图片URL")
                else:
                    logger.warning("[写说说] 无法生成图片提示词")
            except Exception as e:
                logger.error(f"[写说说] 自动配图失败: {e}")
        else:
            logger.info(f"[写说说] 使用用户上传的图片: {len(images)}张")
        
        # 直接发布，不保存草稿
        await self.operator.publish_feed(event, text, images, publish=True)
