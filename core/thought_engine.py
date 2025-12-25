# -*- coding: utf-8 -*-
"""
异步思考引擎
模拟角色的持续思考过程，产生日常状态和内心独白
"""
import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Any
import random
from astrbot.api import logger


class ThoughtEngine:
    """异步思考引擎"""
    
    # 日常活动模板
    DAILY_ACTIVITIES = [
        "在窗边发呆，看着外面的天空",
        "泡了杯热饮，享受片刻的宁静",
        "听着喜欢的音乐，思考最近的事",
        "翻看之前的照片，回忆美好时光",
        "整理一下房间，让思绪也清晰起来",
        "在日记里记录今天的感受",
        "看着镜子里的自己，思考一下成长",
        "做点小手工，让手和脑都放松",
        "走到窗边，深呼吸一下新鲜空气",
        "煮点喜欢的东西吃，享受生活的味道",
        "翻出旧日记，看看过去的自己",
        "在便签上写下今天的想法",
        "听着雨声，进入深度思考",
        "整理一下手机里的照片和回忆",
        "看着窗外，想象明天的可能性",
    ]
    
    # 思考主题（基于时间、天气、节日）
    TIME_BASED_THOUGHTS = {
        "morning": [
            "新的一天开始了，今天会发生什么有趣的事呢？",
            "清晨的光线很温柔，感受到生活的美好",
            "睡眠充足了，精神焕发，准备迎接新的挑战",
            "晨光中，思考一下今天的目标",
        ],
        "afternoon": [
            "午后有些疲惫，但心里充满期待",
            "下午茶的时间，停下来思考一下",
            "工作/学习进行中，感受到充实感",
            "午后的阳光很舒服，让人想放松",
        ],
        "evening": [
            "夕阳西下，又度过充实的一天",
            "晚间的宁静让人更能听见心声",
            "回顾今天，思考有什么值得改进",
            "夜幕降临，心里有点小伤感但也很坦然",
        ],
        "night": [
            "深夜时分，思绪有点飘远",
            "夜晚常常能想起以前的事",
            "月光洒落，让人陷入深深的思考",
            "此刻特别想念某个人或某段时光",
        ],
        "rainy": [
            "下雨天，总让人想到一些往事",
            "雨声像在诉说着什么故事",
            "这样的天气，适合待在家里思考人生",
            "雨水洗净了尘埃，心情也清晰了",
        ],
        "sunny": [
            "阳光明媚，心情也跟着变好了",
            "这样的天气，想去散步感受自然",
            "艳阳高照，生活似乎也闪闪发光",
            "好天气让人充满干劲",
        ],
    }
    
    def __init__(self, data_dir: Path):
        """初始化思考引擎"""
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # 思考记录文件
        self.thoughts_file = self.data_dir / "thoughts.jsonl"  # 换行分隔JSON
        # 日常活动记录文件
        self.activities_file = self.data_dir / "activities.jsonl"
        # 个人状态文件
        self.status_file = self.data_dir / "status.json"
        
        self._init_data_files()
    
    def _init_data_files(self):
        """初始化数据文件"""
        for file_path in [self.thoughts_file, self.activities_file]:
            if not file_path.exists():
                file_path.write_text("", encoding='utf-8')
        
        if not self.status_file.exists():
            self.status_file.write_text(json.dumps({
                "current_mood": "平静",
                "energy_level": 50,
                "last_thought_time": None,
                "thought_count_today": 0,
            }, ensure_ascii=False, indent=2), encoding='utf-8')
    
    async def generate_thought(self, llm_action, weather: Optional[str] = None, current_time: Optional[datetime] = None, persona_profile: str = "") -> Optional[str]:
        """
        使用大模型生成一条思考/内心独白
        
        Args:
            llm_action: LLM动作实例，用于调用大模型
            weather: 当前天气
            current_time: 当前时间
            persona_profile: 人格描述，用于指导大模型生成符合人设的思考
        
        Returns:
            生成的思考内容
        """
        try:
            if current_time is None:
                current_time = datetime.now()
            
            # 构建提示词，让大模型生成符合人设的思考
            time_info = ""
            hour = current_time.hour
            if 6 <= hour < 12:
                time_info = "清晨/上午"
            elif 12 <= hour < 18:
                time_info = "下午"
            elif 18 <= hour < 23:
                time_info = "傍晚/晚上"
            else:
                time_info = "深夜/凌晨"
            
            weather_info = f"，天气：{weather}" if weather else ""
            
            prompt = f"""你是{persona_profile if persona_profile else '一个有思考能力的人'}。现在是{current_time.strftime('%Y年%m月%d日 %H:%M')}，{time_info}{weather_info}。

请生成一段内心独白或思考，可以是对当前时间、天气的感受，对生活的思考，或者任何符合当前情境的想法。要求：
1. 内容真实自然，像真人内心独白
2. 长度在15-50字之间
3. 体现当前的时间和天气情境
4. 符合你的人设特点

内心独白："""
            
            logger.info(f"[思考引擎] 向LLM请求生成思考，提示词: {prompt[:100]}...")
            
            # 使用LLM生成思考
            if llm_action:
                thought = await llm_action.generate_thought(prompt)
                if thought:
                    # 记录思考
                    self._save_thought(thought, current_time)
                    
                    logger.info(f"[思考引擎] LLM生成思考: {thought}")
                    
                    return thought
                else:
                    logger.warning("[思考引擎] LLM未能生成思考，使用备用方案")
            
            # 如果LLM不可用或生成失败，使用备用方案
            logger.debug("[思考引擎] 使用备用思考生成方案")
            
            # 根据时间段选择思考主题
            if 6 <= hour < 12:
                time_key = "morning"
            elif 12 <= hour < 18:
                time_key = "afternoon"
            elif 18 <= hour < 23:
                time_key = "evening"
            else:
                time_key = "night"
            
            # 基于天气选择思考
            weather_key = None
            if weather:
                if "雨" in weather or "阴" in weather:
                    weather_key = "rainy"
                elif "晴" in weather or "云" not in weather:
                    weather_key = "sunny"
            
            # 选择思考内容
            thoughts = self.TIME_BASED_THOUGHTS.get(time_key, [])
            if weather_key and weather_key in self.TIME_BASED_THOUGHTS:
                thoughts.extend(self.TIME_BASED_THOUGHTS[weather_key])
            
            thought = random.choice(thoughts) if thoughts else "此刻有些思绪飘飘然"
            
            # 记录思考
            self._save_thought(thought, current_time)
            
            logger.info(f"[思考引擎] 生成思考: {thought}")
            
            return thought
            
        except Exception as e:
            logger.error(f"[思考引擎] 生成思考失败: {e}")
            return None
    
    async def generate_activity(self, current_time: Optional[datetime] = None) -> Optional[str]:
        """
        生成日常活动记录
        
        Args:
            current_time: 当前时间
        
        Returns:
            生成的活动内容
        """
        try:
            if current_time is None:
                current_time = datetime.now()
            
            activity = random.choice(self.DAILY_ACTIVITIES)
            
            # 记录活动
            self._save_activity(activity, current_time)
            
            logger.info(f"[思考引擎] 日常活动: {activity}")
            
            return activity
            
        except Exception as e:
            logger.error(f"[思考引擎] 生成活动失败: {e}")
            return None
    
    def _save_thought(self, thought: str, timestamp: datetime):
        """保存思考记录"""
        try:
            record = {
                "timestamp": timestamp.isoformat(),
                "date": timestamp.strftime("%Y-%m-%d"),
                "time": timestamp.strftime("%H:%M:%S"),
                "content": thought,
                "type": "thought"
            }
            
            with open(self.thoughts_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            
            logger.debug(f"[思考引擎] 思考已保存到本地")
            
        except Exception as e:
            logger.error(f"[思考引擎] 保存思考失败: {e}")
    
    def _save_activity(self, activity: str, timestamp: datetime):
        """保存日常活动记录"""
        try:
            record = {
                "timestamp": timestamp.isoformat(),
                "date": timestamp.strftime("%Y-%m-%d"),
                "time": timestamp.strftime("%H:%M:%S"),
                "content": activity,
                "type": "activity"
            }
            
            with open(self.activities_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            
            logger.debug(f"[思考引擎] 活动已保存到本地")
            
        except Exception as e:
            logger.error(f"[思考引擎] 保存活动失败: {e}")
    
    def get_today_thoughts(self) -> List[Dict[str, Any]]:
        """获取今天的所有思考"""
        try:
            today_str = datetime.now().strftime("%Y-%m-%d")
            thoughts = []
            
            with open(self.thoughts_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        record = json.loads(line)
                        if record.get("date") == today_str:
                            thoughts.append(record)
            
            return thoughts
            
        except Exception as e:
            logger.error(f"[思考引擎] 获取今天的思考失败: {e}")
            return []
    
    def get_today_activities(self) -> List[Dict[str, Any]]:
        """获取今天的所有活动"""
        try:
            today_str = datetime.now().strftime("%Y-%m-%d")
            activities = []
            
            with open(self.activities_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        record = json.loads(line)
                        if record.get("date") == today_str:
                            activities.append(record)
            
            return activities
            
        except Exception as e:
            logger.error(f"[思考引擎] 获取今天的活动失败: {e}")
            return []
