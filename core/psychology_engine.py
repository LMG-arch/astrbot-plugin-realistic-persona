"""
心理引擎：管理内在驱动力、情绪生命周期、价值观与原则
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Any
from astrbot.api import logger


class PsychologyEngine:
    """心理与内在驱动力管理"""
    
    def __init__(self, data_dir: Path):
        """初始化心理引擎"""
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # 内在驱动力文件
        self.drives_file = self.data_dir / "drives.json"
        # 情绪生命周期文件
        self.emotion_lifecycle_file = self.data_dir / "emotion_lifecycle.jsonl"
        # 价值观与原则文件
        self.values_file = self.data_dir / "values.json"
        
        self._init_data_files()
    
    def _init_data_files(self):
        """初始化数据文件"""
        if not self.drives_file.exists():
            self.drives_file.write_text(json.dumps({
                "curiosity": {
                    "level": 7,  # 1-10 好奇心等级
                    "topics_explored": [],  # 已探索的话题
                    "last_exploration": None
                },
                "expression": {
                    "level": 6,  # 1-10 表达欲等级
                    "expression_count": 0,  # 表达次数
                    "last_expression": None,
                    "expression_types": ["creative", "emotional", "reflective"]
                },
                "connection": {
                    "level": 8,  # 1-10 连接需求等级
                    "interaction_count": 0,
                    "last_interaction": None,
                    "loneliness_threshold": 3600  # 超过1小时无互动会感到孤独（秒）
                }
            }, ensure_ascii=False, indent=2), encoding='utf-8')
        
        if not self.values_file.exists():
            self.values_file.write_text(json.dumps({
                "beliefs": [],  # 坚守的信念列表
                "moral_principles": [],  # 道德原则
                "aesthetic_preferences": {
                    "beauty": [],
                    "humor": [],
                    "wisdom": []
                },
                "updated_at": datetime.now().isoformat()
            }, ensure_ascii=False, indent=2), encoding='utf-8')
    
    # ========== 内在驱动力管理 ==========
    
    def update_curiosity(self, topic: str, exploration_depth: str = "medium"):
        """
        记录好奇心驱动的探索
        
        Args:
            topic: 探索的话题
            exploration_depth: 深度 (light/medium/deep)
        """
        try:
            with open(self.drives_file, 'r', encoding='utf-8') as f:
                drives = json.load(f)
            
            # 记录新的探索话题
            drives["curiosity"]["topics_explored"].append({
                "topic": topic,
                "timestamp": datetime.now().isoformat(),
                "depth": exploration_depth
            })
            
            drives["curiosity"]["last_exploration"] = datetime.now().isoformat()
            
            # 好奇心稍微提升
            drives["curiosity"]["level"] = min(10, drives["curiosity"]["level"] + 0.5)
            
            with open(self.drives_file, 'w', encoding='utf-8') as f:
                json.dump(drives, f, ensure_ascii=False, indent=2)
            
            logger.debug(f"[心理引擎] 好奇心已更新: {topic}")
            
        except Exception as e:
            logger.error(f"[心理引擎] 更新好奇心失败: {e}")
    
    def record_expression_need(self, expression_type: str, content: str, intensity: int = 5):
        """
        记录表达欲驱动的创作或倾诉
        
        Args:
            expression_type: 表达类型 (creative/emotional/reflective)
            content: 表达内容简述
            intensity: 表达强度 (1-10)
        """
        try:
            record = {
                "timestamp": datetime.now().isoformat(),
                "type": expression_type,
                "content": content,
                "intensity": intensity
            }
            
            with open(self.emotion_lifecycle_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            
            # 更新驱动力数据
            with open(self.drives_file, 'r', encoding='utf-8') as f:
                drives = json.load(f)
            
            drives["expression"]["expression_count"] += 1
            drives["expression"]["last_expression"] = datetime.now().isoformat()
            
            # 成功表达后表达欲会降低（满足了）
            drives["expression"]["level"] = max(1, drives["expression"]["level"] - 0.5)
            
            with open(self.drives_file, 'w', encoding='utf-8') as f:
                json.dump(drives, f, ensure_ascii=False, indent=2)
            
            logger.info(f"[心理引擎] 表达欲已记录: {expression_type}")
            
        except Exception as e:
            logger.error(f"[心理引擎] 记录表达欲失败: {e}")
    
    def check_connection_need(self) -> Dict[str, Any]:
        """
        检查连接需求（是否感到孤独）
        
        Returns:
            连接需求分析结果
        """
        try:
            with open(self.drives_file, 'r', encoding='utf-8') as f:
                drives = json.load(f)
            
            last_interaction = drives["connection"]["last_interaction"]
            if not last_interaction:
                time_since_interaction = float('inf')
            else:
                last_time = datetime.fromisoformat(last_interaction)
                time_since_interaction = (datetime.now() - last_time).total_seconds()
            
            loneliness_threshold = drives["connection"]["loneliness_threshold"]
            feels_lonely = time_since_interaction > loneliness_threshold
            
            return {
                "feels_lonely": feels_lonely,
                "time_since_interaction": time_since_interaction,
                "connection_level": drives["connection"]["level"],
                "interaction_count": drives["connection"]["interaction_count"]
            }
            
        except Exception as e:
            logger.debug(f"[心理引擎] 检查连接需求失败: {e}")
            return {"feels_lonely": False}
    
    def record_interaction(self):
        """记录一次互动（满足连接需求）"""
        try:
            with open(self.drives_file, 'r', encoding='utf-8') as f:
                drives = json.load(f)
            
            drives["connection"]["last_interaction"] = datetime.now().isoformat()
            drives["connection"]["interaction_count"] += 1
            
            # 互动满足连接需求，连接驱力降低
            drives["connection"]["level"] = max(1, drives["connection"]["level"] - 0.3)
            
            with open(self.drives_file, 'w', encoding='utf-8') as f:
                json.dump(drives, f, ensure_ascii=False, indent=2)
            
        except Exception as e:
            logger.debug(f"[心理引擎] 记录互动失败: {e}")
    
    # ========== 情绪生命周期管理 ==========
    
    def record_emotion_event(self, trigger_event: str, initial_feeling: str, intensity: int = 5):
        """
        记录触发情绪的事件和初始感受
        
        Args:
            trigger_event: 触发事件描述
            initial_feeling: 初始感受 (喜悦/悲伤/愤怒/失望等)
            intensity: 强度 (1-10)
        """
        try:
            record = {
                "timestamp": datetime.now().isoformat(),
                "phase": "trigger",
                "event": trigger_event,
                "feeling": initial_feeling,
                "intensity": intensity,
                "lifecycle": {
                    "trigger_time": datetime.now().isoformat(),
                    "feeling_phase_start": None,
                    "expression_phase_start": None,
                    "digestion_phase_start": None,
                    "reflection_phase_start": None
                }
            }
            
            with open(self.emotion_lifecycle_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            
            logger.info(f"[心理引擎] 情绪事件已记录: {trigger_event} ({initial_feeling})")
            
        except Exception as e:
            logger.error(f"[心理引擎] 记录情绪事件失败: {e}")
    
    def update_emotion_phase(self, emotion_id: str, phase: str, note: Optional[str] = None):
        """
        更新情绪生命周期的当前阶段
        
        Args:
            emotion_id: 情绪事件ID或关键词
            phase: 阶段 (feeling/expression/digestion/reflection)
            note: 阶段备注
        """
        try:
            if not self.emotion_lifecycle_file.exists():
                return
            
            with open(self.emotion_lifecycle_file, 'r', encoding='utf-8') as f:
                records = [json.loads(line) for line in f]
            
            # 查找最近的匹配情绪事件
            matching = [r for r in records if emotion_id.lower() in r.get("event", "").lower()]
            if matching:
                record = matching[-1]
                record["phase"] = phase
                if note:
                    record["note"] = note
                
                # 更新时间戳
                phase_key = f"{phase}_phase_start"
                if "lifecycle" in record and phase_key in record["lifecycle"]:
                    record["lifecycle"][phase_key] = datetime.now().isoformat()
                
                # 重写文件
                with open(self.emotion_lifecycle_file, 'w', encoding='utf-8') as f:
                    for r in records:
                        f.write(json.dumps(r, ensure_ascii=False) + "\n")
                
                logger.debug(f"[心理引擎] 情绪阶段已更新: {phase}")
            
        except Exception as e:
            logger.error(f"[心理引擎] 更新情绪阶段失败: {e}")
    
    # ========== 价值观与原则管理 ==========
    
    def add_belief(self, belief: str, conviction_level: int = 7):
        """
        添加坚守的信念
        
        Args:
            belief: 信念内容
            conviction_level: 坚守程度 (1-10)
        """
        try:
            with open(self.values_file, 'r', encoding='utf-8') as f:
                values = json.load(f)
            
            values["beliefs"].append({
                "belief": belief,
                "conviction_level": conviction_level,
                "added_at": datetime.now().isoformat()
            })
            
            with open(self.values_file, 'w', encoding='utf-8') as f:
                json.dump(values, f, ensure_ascii=False, indent=2)
            
            logger.info(f"[心理引擎] 信念已添加: {belief}")
            
        except Exception as e:
            logger.error(f"[心理引擎] 添加信念失败: {e}")
    
    def add_moral_principle(self, principle: str, context: Optional[str] = None):
        """
        添加道德原则
        
        Args:
            principle: 道德原则描述
            context: 应用场景
        """
        try:
            with open(self.values_file, 'r', encoding='utf-8') as f:
                values = json.load(f)
            
            values["moral_principles"].append({
                "principle": principle,
                "context": context,
                "added_at": datetime.now().isoformat()
            })
            
            with open(self.values_file, 'w', encoding='utf-8') as f:
                json.dump(values, f, ensure_ascii=False, indent=2)
            
            logger.info(f"[心理引擎] 道德原则已添加: {principle}")
            
        except Exception as e:
            logger.error(f"[心理引擎] 添加道德原则失败: {e}")
    
    def record_aesthetic_preference(self, category: str, item: str):
        """
        记录审美偏好
        
        Args:
            category: 类别 (beauty/humor/wisdom)
            item: 偏好项目
        """
        try:
            with open(self.values_file, 'r', encoding='utf-8') as f:
                values = json.load(f)
            
            if category in values["aesthetic_preferences"]:
                preferences = values["aesthetic_preferences"][category]
                if item not in preferences:
                    preferences.append(item)
                    
                    with open(self.values_file, 'w', encoding='utf-8') as f:
                        json.dump(values, f, ensure_ascii=False, indent=2)
                    
                    logger.debug(f"[心理引擎] 审美偏好已记录: {category} - {item}")
            
        except Exception as e:
            logger.error(f"[心理引擎] 记录审美偏好失败: {e}")
    
    def get_values_summary(self) -> Dict[str, Any]:
        """获取价值观系统摘要"""
        try:
            with open(self.values_file, 'r', encoding='utf-8') as f:
                values = json.load(f)
            
            return {
                "beliefs_count": len(values.get("beliefs", [])),
                "moral_principles_count": len(values.get("moral_principles", [])),
                "aesthetic_preferences": values.get("aesthetic_preferences", {}),
                "updated_at": values.get("updated_at")
            }
            
        except Exception as e:
            logger.error(f"[心理引擎] 获取价值观摘要失败: {e}")
            return {}
    
    def get_drives_summary(self) -> Dict[str, Any]:
        """获取内在驱动力摘要"""
        try:
            with open(self.drives_file, 'r', encoding='utf-8') as f:
                drives = json.load(f)
            
            return {
                "curiosity_level": drives["curiosity"]["level"],
                "expression_level": drives["expression"]["level"],
                "connection_level": drives["connection"]["level"],
                "total_explorations": len(drives["curiosity"]["topics_explored"]),
                "total_expressions": drives["expression"]["expression_count"],
                "total_interactions": drives["connection"]["interaction_count"]
            }
            
        except Exception as e:
            logger.error(f"[心理引擎] 获取驱动力摘要失败: {e}")
            return {}
