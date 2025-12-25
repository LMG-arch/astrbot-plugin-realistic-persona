# -*- coding: utf-8 -*-
"""
经历累积和关系网络管理
记录所有对话、事件和用户互动模式，形成持续性记忆银行
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Any
from collections import defaultdict
from astrbot.api import logger

try:
    from .timeline_verifier import TimelineVerifier
    TIMELINE_AVAILABLE = True
except ImportError:
    TIMELINE_AVAILABLE = False
    logger.warning("[经历银行] TimelineVerifier 未找到，时间线验证功能将被禁用")


class ExperienceBank:
    """经历累积银行"""
    
    def __init__(self, data_dir: Path, enable_timeline_verification: bool = True):
        """初始化经历银行
        
        Args:
            data_dir: 数据目录
            enable_timeline_verification: 是否启用时间线验证
        """
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # 对话记录文件
        self.conversations_file = self.data_dir / "conversations.jsonl"
        # 事件记录文件
        self.events_file = self.data_dir / "events.jsonl"
        # 成长轨迹文件
        self.growth_file = self.data_dir / "growth.json"
        # 关系网络文件
        self.relationships_file = self.data_dir / "relationships.json"
        
        # 初始化时间线验证器
        self.timeline_verifier = None
        if enable_timeline_verification and TIMELINE_AVAILABLE:
            try:
                self.timeline_verifier = TimelineVerifier(self.data_dir / "timeline")
                logger.info("[经历银行] 时间线验证器已启用")
            except Exception as e:
                logger.error(f"[经历银行] 启用时间线验证器失败: {e}")
        
        self._init_data_files()
    
    def _init_data_files(self):
        """初始化数据文件"""
        for file_path in [self.conversations_file, self.events_file]:
            if not file_path.exists():
                file_path.write_text("", encoding='utf-8')
        
        if not self.growth_file.exists():
            self.growth_file.write_text(json.dumps({
                "skills": {},
                "interests": [],
                "views": [],
                "updated_at": datetime.now().isoformat()
            }, ensure_ascii=False, indent=2), encoding='utf-8')
        
        if not self.relationships_file.exists():
            self.relationships_file.write_text(json.dumps({}, ensure_ascii=False, indent=2), encoding='utf-8')
    
    def record_conversation(self, user_id: str, user_message: str, bot_response: str, session_id: Optional[str] = None):
        """
        记录对话内容
        
        Args:
            user_id: 用户ID
            user_message: 用户消息
            bot_response: 机器人回复
            session_id: 会话ID
        """
        try:
            record = {
                "timestamp": datetime.now().isoformat(),
                "date": datetime.now().strftime("%Y-%m-%d"),
                "user_id": user_id,
                "session_id": session_id,
                "user_message": user_message,
                "bot_response": bot_response,
                "message_length": len(user_message),
                "response_length": len(bot_response)
            }
            
            with open(self.conversations_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            
            # 更新关系网络
            self._update_relationship(user_id, {
                "last_chat": datetime.now().isoformat(),
                "interaction_type": "conversation"
            })
            
            logger.info(f"[经历银行] 对话已记录: 用户 {user_id}")
            
        except Exception as e:
            logger.error(f"[经历银行] 记录对话失败: {e}")
    
    def record_event(self, event_type: str, description: str, related_user_id: Optional[str] = None, metadata: Optional[Dict] = None):
        """
        记录发生的事件
        
        Args:
            event_type: 事件类型（如"birthday", "anniversary", "milestone"等）
            description: 事件描述
            related_user_id: 相关用户ID
            metadata: 其他元数据
        """
        try:
            record = {
                "timestamp": datetime.now().isoformat(),
                "date": datetime.now().strftime("%Y-%m-%d"),
                "event_type": event_type,
                "description": description,
                "related_user_id": related_user_id,
                "metadata": metadata or {}
            }
            
            with open(self.events_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            
            logger.info(f"[经历银行] 事件已记录: {event_type}")
            
        except Exception as e:
            logger.error(f"[经历银行] 记录事件失败: {e}")
    
    def update_growth(self, growth_type: str, item: str, level: Optional[int] = None, validate_smoothness: bool = True):
        """
        更新成长轨迹（支持平滑性验证）
        
        Args:
            growth_type: 成长类型（"skills", "interests", "views"）
            item: 具体项目
            level: 等级/进度（可选）
            validate_smoothness: 是否验证成长平滑性
        """
        try:
            with open(self.growth_file, 'r', encoding='utf-8') as f:
                growth_data = json.load(f)
            
            if growth_type == "skills":
                # 技能升级平滑性验证
                if item in growth_data["skills"] and level and validate_smoothness:
                    old_level = growth_data["skills"][item].get("level", 1)
                    level_jump = abs(level - old_level)
                    
                    # 平滑性检查：等级变化不应超过3级
                    if level_jump > 3:
                        logger.warning(f"[经历银行] 技能等级变化过大: {item} {old_level}->{level}，调整为渐进式提升")
                        # 调整为渐进升级
                        level = old_level + min(3, level_jump if level > old_level else -3)
                
                if item not in growth_data["skills"]:
                    growth_data["skills"][item] = {
                        "level": 1,
                        "first_learned": datetime.now().isoformat(),
                        "last_used": datetime.now().isoformat(),
                        "growth_history": []  # 成长历史
                    }
                else:
                    if level:
                        # 记录成长历史
                        growth_data["skills"][item].setdefault("growth_history", []).append({
                            "from_level": growth_data["skills"][item]["level"],
                            "to_level": level,
                            "changed_at": datetime.now().isoformat()
                        })
                        growth_data["skills"][item]["level"] = level
                    growth_data["skills"][item]["last_used"] = datetime.now().isoformat()
            
            elif growth_type == "interests":
                # 检查是否已存在
                existing_interests = [i.get("item") for i in growth_data["interests"]]
                if item not in existing_interests:
                    growth_data["interests"].append({
                        "item": item,
                        "discovered_at": datetime.now().isoformat()
                    })
                    logger.info(f"[经历银行] 新兴趣已添加: {item}")
            
            elif growth_type == "views":
                # 观点平滑性检查：避免短期内添加相反观点
                if validate_smoothness and growth_data["views"]:
                    recent_views = growth_data["views"][-5:]  # 最近5个观点
                    for recent in recent_views:
                        # 简单检查时间间隔（至少间7天）
                        formed_at = datetime.fromisoformat(recent.get("formed_at", datetime.now().isoformat()))
                        if (datetime.now() - formed_at) < timedelta(days=7):
                            logger.debug(f"[经历银行] 观点添加频繁，建议间隔至少7天")
                
                growth_data["views"].append({
                    "view": item,
                    "formed_at": datetime.now().isoformat()
                })
            
            growth_data["updated_at"] = datetime.now().isoformat()
            
            with open(self.growth_file, 'w', encoding='utf-8') as f:
                json.dump(growth_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"[经历银行] 成长轨迹已更新: {growth_type} - {item}")
            
        except Exception as e:
            logger.error(f"[经历银行] 更新成长失败: {e}")
    
    def _update_relationship(self, user_id: str, interaction_data: Dict[str, Any]):
        """
        更新用户关系网络
        
        Args:
            user_id: 用户ID
            interaction_data: 互动数据
        """
        try:
            with open(self.relationships_file, 'r', encoding='utf-8') as f:
                relationships = json.load(f)
            
            if user_id not in relationships:
                relationships[user_id] = {
                    "first_met": datetime.now().isoformat(),
                    "interaction_count": 0,
                    "interaction_patterns": defaultdict(int),
                    "last_interactions": [],
                    "estimated_personality": {},
                    "notes": ""
                }
            
            user_rel = relationships[user_id]
            user_rel["interaction_count"] = user_rel.get("interaction_count", 0) + 1
            user_rel["last_interactions"].append(interaction_data)
            
            # 只保留最近10次互动
            if len(user_rel["last_interactions"]) > 10:
                user_rel["last_interactions"] = user_rel["last_interactions"][-10:]
            
            # 统计互动模式
            interaction_type = interaction_data.get("interaction_type", "unknown")
            if "interaction_patterns" not in user_rel:
                user_rel["interaction_patterns"] = {}
            if interaction_type not in user_rel["interaction_patterns"]:
                user_rel["interaction_patterns"][interaction_type] = 0
            user_rel["interaction_patterns"][interaction_type] += 1
            
            with open(self.relationships_file, 'w', encoding='utf-8') as f:
                # 转换defaultdict为普通dict以便序列化
                relationships_serializable = {}
                for uid, rel in relationships.items():
                    rel_copy = rel.copy()
                    if isinstance(rel_copy.get("interaction_patterns"), defaultdict):
                        rel_copy["interaction_patterns"] = dict(rel_copy["interaction_patterns"])
                    relationships_serializable[uid] = rel_copy
                json.dump(relationships_serializable, f, ensure_ascii=False, indent=2)
            
        except Exception as e:
            logger.error(f"[经历银行] 更新关系网络失败: {e}")
    
    def get_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        获取用户的综合资料（基于历史互动）
        
        Args:
            user_id: 用户ID
        
        Returns:
            用户资料字典
        """
        try:
            with open(self.relationships_file, 'r', encoding='utf-8') as f:
                relationships = json.load(f)
            
            if user_id not in relationships:
                return None
            
            user_rel = relationships[user_id]
            
            # 分析互动模式
            total_interactions = user_rel.get("interaction_count", 0)
            patterns = user_rel.get("interaction_patterns", {})
            
            profile = {
                "user_id": user_id,
                "first_met": user_rel.get("first_met"),
                "total_interactions": total_interactions,
                "interaction_patterns": patterns,
                "recent_interactions": user_rel.get("last_interactions", [])[-5:],
                "personality_traits": self._analyze_personality(patterns),
                "interaction_frequency": self._calculate_frequency(user_rel.get("last_interactions", []))
            }
            
            return profile
            
        except Exception as e:
            logger.error(f"[经历银行] 获取用户资料失败: {e}")
            return None
    
    def _analyze_personality(self, patterns: Dict[str, int]) -> List[str]:
        """基于互动模式分析人格特征"""
        traits = []
        
        if patterns.get("conversation", 0) > patterns.get("event", 0):
            traits.append("善于交流")
        
        total = sum(patterns.values())
        if total > 50:
            traits.append("高频互动")
        
        if patterns.get("event", 0) > 10:
            traits.append("事件驱动")
        
        return traits
    
    def _calculate_frequency(self, interactions: List[Dict]) -> str:
        """计算互动频率"""
        if not interactions:
            return "未知"
        
        # 简单的频率估算
        if len(interactions) > 20:
            return "极高频"
        elif len(interactions) > 10:
            return "高频"
        elif len(interactions) > 5:
            return "中等"
        else:
            return "低频"
    
    def _get_top_skills(self, skills: Dict[str, Dict]) -> List[str]:
        """获取排名前5的技能"""
        sorted_skills = sorted(skills.items(), key=lambda x: x[1].get("level", 0), reverse=True)
        return [skill[0] for skill in sorted_skills[:5]]
    
    def get_growth_summary(self) -> Dict[str, Any]:
        """获取成长摘要"""
        try:
            with open(self.growth_file, 'r', encoding='utf-8') as f:
                growth_data = json.load(f)
            
            return {
                "skills_count": len(growth_data.get("skills", {})),
                "interests_count": len(growth_data.get("interests", [])),
                "views_count": len(growth_data.get("views", [])),
                "top_skills": self._get_top_skills(growth_data.get("skills", {})),
                "recent_interests": growth_data.get("interests", [])[-5:],
                "updated_at": growth_data.get("updated_at")
            }
            
        except Exception as e:
            logger.error(f"[经历银行] 获取成长摘要失败: {e}")
            return {}
    
    # ========== 关系网络智能压缩 ==========
    
    def extract_relationship_milestones(self, user_id: str, max_milestones: int = 10) -> List[Dict[str, Any]]:
        """
        从大量互动中提取关系里程碑事件
        
        Args:
            user_id: 用户ID
            max_milestones: 最大里程碑事件数
        
        Returns:
            不超过max_milestones个的关键事件列表
        """
        try:
            if not self.conversations_file.exists():
                return []
            
            # 收集所有与该用户相关的对话
            with open(self.conversations_file, 'r', encoding='utf-8') as f:
                conversations = [json.loads(line) for line in f if json.loads(line).get("user_id") == user_id]
            
            if not conversations:
                return []
            
            # 显记事件的位置：相比上一次互动剧烈增加
            milestones = []
            
            # 检测第一次互动（相轘里程碑）
            if conversations:
                first_interaction = conversations[0]
                milestones.append({
                    "type": "first_meeting",
                    "timestamp": first_interaction["timestamp"],
                    "description": "第一次类诚",
                    "interaction_count_at_time": 0
                })
            
            # 検测长事作谈话（消息良久、遇最吸引人）
            for i, conv in enumerate(conversations):
                msg_len = conv.get("message_length", 0)
                resp_len = conv.get("response_length", 0)
                
                # 消息酷并较长：可能是重要事项
                if msg_len > 200 or resp_len > 300:
                    milestones.append({
                        "type": "deep_conversation",
                        "timestamp": conv["timestamp"],
                        "description": f"长事谈话（需要及时回应）",
                        "message_length": msg_len,
                        "response_length": resp_len
                    })
            
            # 検测互动频率和较大5倍声泰叨出现（可能是下了好爲气）
            if len(conversations) > 1:
                avg_interval = (datetime.fromisoformat(conversations[-1]["timestamp"]) - 
                               datetime.fromisoformat(conversations[0]["timestamp"])).total_seconds() / len(conversations)
                
                for i in range(1, len(conversations)):
                    prev_time = datetime.fromisoformat(conversations[i-1]["timestamp"])
                    curr_time = datetime.fromisoformat(conversations[i]["timestamp"])
                    interval = (curr_time - prev_time).total_seconds()
                    
                    if interval < avg_interval / 5:
                        milestones.append({
                            "type": "sudden_frequency_increase",
                            "timestamp": conversations[i]["timestamp"],
                            "description": "消息强流（很积急）",
                            "interval": interval
                        })
            
            # 按时间排序并限制数量
            milestones.sort(key=lambda x: x["timestamp"])
            
            logger.info(f"[经历银行] 已提取{len(milestones)}个关系里程碑: {user_id}")
            
            return milestones[:max_milestones]
            
        except Exception as e:
            logger.error(f"[经历银行] 提取关系里程碑失败: {e}")
            return []
    
    def generate_relationship_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        为每个用户生成个性化的关系特征描述
        
        Args:
            user_id: 用户ID
        
        Returns:
            详细的关系特征描述或None
        """
        try:
            if not self.relationships_file.exists():
                return None
            
            with open(self.relationships_file, 'r', encoding='utf-8') as f:
                relationships = json.load(f)
            
            if user_id not in relationships:
                return None
            
            user_rel = relationships[user_id]
            
            # 五维性格模弋
            profile = {
                "user_id": user_id,
                "first_met": user_rel.get("first_met"),
                "total_interactions": user_rel.get("interaction_count", 0),
                
                # 维度：互动模式
                "interaction_patterns": self._analyze_interaction_patterns(
                    user_rel.get("interaction_patterns", {})
                ),
                
                # 维度：互动锻幅
                "engagement_level": self._calculate_engagement_level(
                    user_rel.get("last_interactions", [])
                ),
                
                # 维度：互动严輣
                "interaction_intensity": self._calculate_interaction_intensity(
                    user_rel.get("last_interactions", [])
                ),
                
                # 维度：人格一致性
                "consistency_score": self._analyze_consistency(
                    user_rel.get("last_interactions", [])
                ),
                
                # 维度：互动趣吐
                "relationship_characteristics": self._generate_relationship_characteristics(
                    user_rel.get("last_interactions", []),
                    user_rel.get("interaction_patterns", {})
                ),
                
                # 每个用户的不需要破人告訹（需要最接近互动）
                "recent_interactions_summary": self._summarize_recent_interactions(
                    user_rel.get("last_interactions", [])
                )
            }
            
            logger.info(f"[经历银行] 申述已生成: {user_id}")
            return profile
            
        except Exception as e:
            logger.error(f"[经历银行] 生成关系特征失败: {e}")
            return {}
    
    def _analyze_interaction_patterns(self, patterns: Dict[str, int]) -> Dict[str, str]:
        """分析互动模式的性质"""
        analysis = {}
        
        total = sum(patterns.values())
        if total == 0:
            return analysis
        
        for pattern_type, count in patterns.items():
            percentage = (count / total) * 100
            
            if pattern_type == "conversation":
                if percentage > 70:
                    analysis["primary_type"] = "谈话龎平"
                else:
                    analysis["has_conversation"] = "主要互动形式"
            elif pattern_type == "event":
                if percentage > 50:
                    analysis["event_driven"] = "事件驱动型互动"
        
        return analysis
    
    def _calculate_engagement_level(self, interactions: List[Dict]) -> str:
        """计算互动锻幵"""
        if not interactions:
            return "低"
        
        if len(interactions) > 20:
            return "极高"
        elif len(interactions) > 10:
            return "高"
        elif len(interactions) > 5:
            return "中"
        else:
            return "低"
    
    def _calculate_interaction_intensity(self, interactions: List[Dict]) -> Dict[str, Any]:
        """计算互动晓沑（模溳程度）"""
        if not interactions:
            return {"level": "低", "score": 0}
        
        # 计算平均消息长度
        avg_message_len = sum(i.get("message_length", 0) for i in interactions) / len(interactions)
        
        # 计算互动间隔变化
        if len(interactions) > 1:
            timestamps = [datetime.fromisoformat(i.get("timestamp", "")) for i in interactions]
            intervals = [(timestamps[i+1] - timestamps[i]).total_seconds() for i in range(len(timestamps)-1)]
            consistency = 1 - (max(intervals) / max(intervals + [1])) if intervals else 0.5
        else:
            consistency = 0.5
        
        intensity_score = (avg_message_len / 200 + consistency) / 2
        
        if intensity_score > 0.7:
            level = "高"
        elif intensity_score > 0.4:
            level = "中"
        else:
            level = "低"
        
        return {"level": level, "score": round(intensity_score, 2)}
    
    def _analyze_consistency(self, interactions: List[Dict]) -> float:
        """抉断互动的一致性（里模序及互动风格是否稳定）"""
        if len(interactions) < 2:
            return 0.5
        
        # 检查最近的消息是否有显著的越动
        message_lengths = [i.get("message_length", 0) for i in interactions[-5:]]
        
        if not message_lengths:
            return 0.5
        
        avg = sum(message_lengths) / len(message_lengths)
        variance = sum((x - avg) ** 2 for x in message_lengths) / len(message_lengths)
        
        # 方差小料越音攉
        consistency = 1 - min(variance / (avg ** 2 + 1), 1)
        
        return round(consistency, 2)
    
    def _generate_relationship_characteristics(self, interactions: List[Dict], patterns: Dict[str, int]) -> List[str]:
        """生成关系特质放描"""
        characteristics = []
        
        # 基于互动模式
        if patterns.get("conversation", 0) > patterns.get("event", 0):
            characteristics.append("喜欢谈天")
        
        if patterns.get("event", 0) > 10:
            characteristics.append("事件口子")
        
        # 基于互动模式
        if len(interactions) > 10:
            characteristics.append("常客")
        
        total_interactions = sum(patterns.values())
        if total_interactions > 50:
            characteristics.append("密上")
        
        # 基于消息長度
        avg_msg_len = sum(i.get("message_length", 0) for i in interactions) / max(len(interactions), 1)
        if avg_msg_len > 150:
            characteristics.append("深度传舟")
        
        return characteristics
    
    def _summarize_recent_interactions(self, interactions: List[Dict]) -> Dict[str, Any]:
        """沂沂最近的互动（最近5次）"""
        recent = interactions[-5:] if interactions else []
        
        if not recent:
            return {"count": 0, "summary": "没有互动纪录"}
        
        return {
            "count": len(recent),
            "latest_interaction": recent[-1].get("timestamp") if recent else None,
            "total_recent_characters": sum(r.get("message_length", 0) for r in recent)
        }

    
    # ========== 长期项目追蹤 ==========
    
    def record_project(self, project_name: str, description: str, status: str = "in_progress", metadata: Optional[Dict] = None):
        """
        记录长期项目（学习课程、书籍、作品等）
        
        Args:
            project_name: 项目名称
            description: 项目描述
            status: 状态（in_progress/completed/paused）
            metadata: 其他元数据（进度、年份等）
        """
        try:
            record = {
                "timestamp": datetime.now().isoformat(),
                "date": datetime.now().strftime("%Y-%m-%d"),
                "project_name": project_name,
                "description": description,
                "status": status,
                "metadata": metadata or {}
            }
            
            if not hasattr(self, "projects_file"):
                self.projects_file = self.data_dir / "projects.jsonl"
            
            with open(self.projects_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            
            logger.info(f"[经历银行] 项目已记录: {project_name} - {status}")
            
        except Exception as e:
            logger.error(f"[经历银行] 记录项目失败: {e}")
    
    # ========== 承诺与承诺追蹤 ==========
    
    def record_promise(self, promise: str, related_user_id: Optional[str] = None, deadline: Optional[str] = None, metadata: Optional[Dict] = None):
        """
        记录承诺的事项
        
        Args:
            promise: 承诺描述
            related_user_id: 相关用户ID
            deadline: 截止日期
            metadata: 其他元数据
        """
        try:
            record = {
                "timestamp": datetime.now().isoformat(),
                "date": datetime.now().strftime("%Y-%m-%d"),
                "promise": promise,
                "related_user_id": related_user_id,
                "deadline": deadline,
                "status": "pending",
                "completed_at": None,
                "metadata": metadata or {}
            }
            
            if not hasattr(self, "promises_file"):
                self.promises_file = self.data_dir / "promises.jsonl"
            
            with open(self.promises_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            
            logger.info(f"[经历银行] 承诺已记录: {promise}")
            
        except Exception as e:
            logger.error(f"[经历银行] 记录承诺失败: {e}")
    
    def complete_promise(self, promise_keyword: str, completion_note: Optional[str] = None):
        """
        标记承诺为完成
        
        Args:
            promise_keyword: 承诺的关键词或描述
            completion_note: 完成介绍
        """
        try:
            if not hasattr(self, "promises_file"):
                return
            
            with open(self.promises_file, 'r', encoding='utf-8') as f:
                promises = [json.loads(line) for line in f]
            
            updated = False
            for promise in promises:
                if promise_keyword.lower() in promise.get("promise", "").lower():
                    promise["status"] = "completed"
                    promise["completed_at"] = datetime.now().isoformat()
                    if completion_note:
                        promise["completion_note"] = completion_note
                    updated = True
            
            if updated:
                with open(self.promises_file, 'w', encoding='utf-8') as f:
                    for promise in promises:
                        f.write(json.dumps(promise, ensure_ascii=False) + "\n")
                logger.info(f"[经历银行] 承诺已完成: {promise_keyword}")
        
        except Exception as e:
            logger.error(f"[经历银行] 更新承诺失败: {e}")
    
    # ========== 时间节律与生物钟 ==========
    
    def record_circadian_state(self, state: str, energy_level: int, creativity_level: int, mood: str):
        """
        记录当前的生物钟状态
        
        Args:
            state: 状态（清晨/上午/中厤/下午/僧晨/夜晴）
            energy_level: 精力水平 (1-10)
            creativity_level: 创意力水平 (1-10)
            mood: 情绿 (开心/中性/愢怂)
        """
        try:
            record = {
                "timestamp": datetime.now().isoformat(),
                "hour": datetime.now().hour,
                "state": state,
                "energy_level": energy_level,
                "creativity_level": creativity_level,
                "mood": mood
            }
            
            if not hasattr(self, "circadian_file"):
                self.circadian_file = self.data_dir / "circadian.jsonl"
            
            with open(self.circadian_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            
        except Exception as e:
            logger.debug(f"[经历银行] 记录生物钟失败: {e}")
    
    # ========== 不同场景的人格分化 ==========
    
    def record_context_personality(self, context_type: str, traits: List[str], tone: str, metadata: Optional[Dict] = None):
        """
        记录不同场景下的人格表现
        
        Args:
            context_type: 上下文类型 (private_chat/group_chat/public)
            traits: 人格特质列表
            tone: 语气风格 (正式/非正式/颇皮)
            metadata: 其他元数据
        """
        try:
            record = {
                "timestamp": datetime.now().isoformat(),
                "context_type": context_type,
                "traits": traits,
                "tone": tone,
                "metadata": metadata or {}
            }
            
            if not hasattr(self, "personality_file"):
                self.personality_file = self.data_dir / "personalities.jsonl"
            
            with open(self.personality_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            
            logger.info(f"[经历银行] 人格表现已记录: {context_type}")
            
        except Exception as e:
            logger.error(f"[经历银行] 记录人格失败: {e}")
    
    def get_context_personality(self, context_type: str) -> Optional[Dict[str, Any]]:
        """
        获取指定场景的人格描述
        """
        try:
            if not hasattr(self, "personality_file"):
                return None
            
            with open(self.personality_file, 'r', encoding='utf-8') as f:
                personalities = [json.loads(line) for line in f]
            
            # 返回最新的匹配上下文类型
            matching = [p for p in personalities if p.get("context_type") == context_type]
            if matching:
                return matching[-1]
            
            return None
            
        except Exception as e:
            logger.debug(f"[经历银行] 获取人格失败: {e}")
            return None
    
    # ========== 时间线验证集成 ==========
    
    def add_experience_to_timeline(self,
                                   experience_id: str,
                                   content: str,
                                   event_type: str = "general",
                                   event_date: Optional[str] = None,
                                   related_experiences: Optional[List[str]] = None) -> bool:
        """
        将经历添加到时间线并验证
        
        Args:
            experience_id: 经历ID
            content: 经历内容
            event_type: 事件类型
            event_date: 事件日期（默认为今天）
            related_experiences: 相关经历列表
        
        Returns:
            是否成功添加
        """
        if not self.timeline_verifier:
            logger.debug("[经历银行] 时间线验证器未启用")
            return False
        
        try:
            if not event_date:
                event_date = datetime.now().strftime("%Y-%m-%d")
            
            success = self.timeline_verifier.add_experience(
                experience_id=experience_id,
                content=content,
                event_date=event_date,
                event_type=event_type,
                related_experiences=related_experiences
            )
            
            if success:
                logger.info(f"[经历银行] 经历已添加到时间线: {experience_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"[经历银行] 添加经历到时间线失败: {e}")
            return False
    
    def get_timeline_coherence_report(self) -> Dict[str, Any]:
        """
        获取时间线连贯性报告
        
        Returns:
            连贯性分析报告
        """
        if not self.timeline_verifier:
            return {"error": "时间线验证器未启用"}
        
        try:
            # 获取所有经历
            with open(self.events_file, 'r', encoding='utf-8') as f:
                events = [json.loads(line) for line in f if line.strip()]
            
            # 分析连贯性
            coherence = self.timeline_verifier.analyze_experience_coherence(events)
            
            # 添加成长平滑性分析
            growth_smoothness = self._analyze_growth_smoothness()
            coherence["growth_smoothness"] = growth_smoothness
            
            return coherence
            
        except Exception as e:
            logger.error(f"[经历银行] 获取时间线报告失败: {e}")
            return {}
    
    def _analyze_growth_smoothness(self) -> Dict[str, Any]:
        """
        分析成长轨迹的平滑性
        
        Returns:
            平滑性分析结果
        """
        try:
            with open(self.growth_file, 'r', encoding='utf-8') as f:
                growth_data = json.load(f)
            
            skills = growth_data.get("skills", {})
            smoothness_issues = []
            
            # 检查每个技能的成长历史
            for skill_name, skill_data in skills.items():
                growth_history = skill_data.get("growth_history", [])
                
                for i in range(len(growth_history)):
                    history = growth_history[i]
                    level_jump = abs(history.get("to_level", 0) - history.get("from_level", 0))
                    
                    if level_jump > 3:
                        smoothness_issues.append({
                            "skill": skill_name,
                            "issue": f"等级跃迁过大: {history.get('from_level')} -> {history.get('to_level')}",
                            "timestamp": history.get("changed_at")
                        })
            
            return {
                "is_smooth": len(smoothness_issues) == 0,
                "total_skills": len(skills),
                "issue_count": len(smoothness_issues),
                "issues": smoothness_issues[:5],  # 只返回前5个问题
                "assessment": "平滑" if len(smoothness_issues) == 0 else "有跨越式成长"
            }
            
        except Exception as e:
            logger.error(f"[经历银行] 分析成长平滑性失败: {e}")
            return {}
