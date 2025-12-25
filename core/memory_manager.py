# -*- coding: utf-8 -*-
"""
记忆管理引擎：根据重要性和时间衰减实现记忆强化与遗忘
支持动态权重调整、记忆衰减、优先级排序等功能
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Any
from astrbot.api import logger


class MemoryManager:
    """记忆管理系统 - 实现类似人脑的遗忘和强化机制"""
    
    def __init__(self, data_dir: Path):
        """初始化记忆管理器"""
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # 对话记录文件（带权重）
        self.weighted_conversations_file = self.data_dir / "weighted_conversations.jsonl"
        # 记忆强化档案（频繁回顾的记忆）
        self.memory_reinforcement_file = self.data_dir / "memory_reinforcement.json"
        # 记忆遗忘队列（待淘汰的低价值记忆）
        self.memory_decay_log_file = self.data_dir / "memory_decay.jsonl"
        
        self._init_data_files()
    
    def _init_data_files(self):
        """初始化数据文件"""
        for file_path in [self.weighted_conversations_file, self.memory_decay_log_file]:
            if not file_path.exists():
                file_path.write_text("", encoding='utf-8')
        
        if not self.memory_reinforcement_file.exists():
            self.memory_reinforcement_file.write_text(json.dumps({
                "core_memories": [],  # 核心关键记忆
                "important_memories": [],  # 重要记忆
                "reinforcement_log": [],  # 强化历史
                "last_review": datetime.now().isoformat()
            }, ensure_ascii=False, indent=2), encoding='utf-8')
    
    # ========== 记忆权重与评分 ==========
    
    def calculate_memory_importance(self, 
                                    conversation: Dict[str, Any],
                                    context_clues: Optional[List[str]] = None) -> float:
        """
        计算对话的重要性评分 (0-1)
        
        Args:
            conversation: 对话记录
            context_clues: 重要线索列表（如特定关键词）
        
        Returns:
            重要性评分（0-1）
        """
        importance = 0.5  # 基础分
        
        user_message = conversation.get("user_message", "")
        bot_response = conversation.get("bot_response", "")
        full_text = user_message + " " + bot_response
        
        # 1. 消息长度权重
        message_len = len(user_message)
        if message_len > 300:
            importance += 0.2  # 长消息通常更重要
        elif message_len > 100:
            importance += 0.1
        
        # 2. 内容关键词权重
        important_keywords = [
            "记得", "记住", "重要", "承诺", "决定",  # 主观重要性
            "成功", "完成", "突破", "改变", "学到",  # 成就性事件
            "感谢", "爱", "开心", "感动", "珍惜",  # 情感事件
            "生日", "纪念", "节日", "里程碑", "转折",  # 时间标记
        ]
        
        for keyword in important_keywords:
            if keyword in full_text:
                importance += 0.15
                break  # 避免重复加分
        
        # 3. 用户上下文线索权重
        if context_clues:
            for clue in context_clues:
                if clue.lower() in full_text.lower():
                    importance += 0.1
        
        # 4. 情绪表达权重
        emotional_indicators = [
            "!", "！", "?", "？", "...", "…",  # 标点符号
            "很", "非常", "特别", "真的", "一定"  # 强调词
        ]
        emotional_count = sum(1 for indicator in emotional_indicators if indicator in full_text)
        importance += min(emotional_count * 0.05, 0.15)  # 最多+0.15
        
        # 5. 回复长度权重（较长的回复=更重要的话题）
        response_len = len(bot_response)
        if response_len > 200:
            importance += 0.1
        
        # 标准化到0-1范围
        return min(max(importance, 0.0), 1.0)
    
    def record_weighted_conversation(self,
                                     user_id: str,
                                     user_message: str,
                                     bot_response: str,
                                     importance_score: Optional[float] = None,
                                     context_clues: Optional[List[str]] = None,
                                     session_id: Optional[str] = None):
        """
        记录带权重的对话
        
        Args:
            user_id: 用户ID
            user_message: 用户消息
            bot_response: 机器人回复
            importance_score: 手动设置的重要性评分（如果None则自动计算）
            context_clues: 重要线索列表
            session_id: 会话ID
        """
        try:
            # 创建对话记录
            conversation = {
                "timestamp": datetime.now().isoformat(),
                "date": datetime.now().strftime("%Y-%m-%d"),
                "user_id": user_id,
                "session_id": session_id,
                "user_message": user_message,
                "bot_response": bot_response,
                "message_length": len(user_message),
                "response_length": len(bot_response)
            }
            
            # 计算或使用给定的重要性评分
            if importance_score is None:
                importance_score = self.calculate_memory_importance(conversation, context_clues)
            else:
                importance_score = min(max(importance_score, 0.0), 1.0)
            
            conversation["importance_score"] = importance_score
            conversation["review_count"] = 0  # 被回顾的次数
            conversation["last_reviewed"] = None  # 最后被回顾的时间
            conversation["decay_factor"] = 1.0  # 衰减因子（0-1）
            
            # 存储到文件
            with open(self.weighted_conversations_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(conversation, ensure_ascii=False) + "\n")
            
            logger.info(f"[记忆管理] 对话已记录，重要性: {importance_score:.2f}")
            
            # 如果重要性很高，直接加入核心记忆
            if importance_score >= 0.8:
                self._promote_to_core_memory(conversation)
            
        except Exception as e:
            logger.error(f"[记忆管理] 记录对话失败: {e}")
    
    # ========== 记忆强化机制 ==========
    
    def reinforce_memory(self, 
                        memory_id: str,
                        reinforcement_type: str = "manual_recall") -> None:
        """
        强化一条记忆（每次回顾都会增加其持久性）
        
        Args:
            memory_id: 记忆标识（使用timestamp或自定义ID）
            reinforcement_type: 强化类型
                - manual_recall: 手动回忆
                - context_trigger: 上下文触发
                - anniversary: 周年纪念
                - milestone: 里程碑复述
        """
        try:
            with open(self.memory_reinforcement_file, 'r', encoding='utf-8') as f:
                reinforcement_data = json.load(f)
            
            # 记录强化事件
            reinforcement_event = {
                "timestamp": datetime.now().isoformat(),
                "memory_id": memory_id,
                "type": reinforcement_type,
                "effectiveness": self._get_reinforcement_effectiveness(reinforcement_type)
            }
            
            reinforcement_data["reinforcement_log"].append(reinforcement_event)
            reinforcement_data["last_review"] = datetime.now().isoformat()
            
            # 更新文件
            with open(self.memory_reinforcement_file, 'w', encoding='utf-8') as f:
                json.dump(reinforcement_data, f, ensure_ascii=False, indent=2)
            
            logger.debug(f"[记忆管理] 记忆已强化: {memory_id} ({reinforcement_type})")
            
        except Exception as e:
            logger.error(f"[记忆管理] 强化记忆失败: {e}")
    
    def _get_reinforcement_effectiveness(self, reinforcement_type: str) -> float:
        """获取不同强化类型的有效性系数"""
        effectiveness_map = {
            "manual_recall": 0.9,        # 手动回忆最有效
            "context_trigger": 0.7,      # 上下文触发
            "anniversary": 0.8,          # 周年纪念
            "milestone": 0.85,           # 里程碑复述
            "passive_recall": 0.5        # 被动提及
        }
        return effectiveness_map.get(reinforcement_type, 0.5)
    
    def _promote_to_core_memory(self, conversation: Dict[str, Any]) -> None:
        """将高重要性对话提升为核心记忆"""
        try:
            with open(self.memory_reinforcement_file, 'r', encoding='utf-8') as f:
                reinforcement_data = json.load(f)
            
            core_memory = {
                "timestamp": conversation["timestamp"],
                "user_id": conversation["user_id"],
                "summary": (conversation["user_message"][:50] + 
                           "..." if len(conversation["user_message"]) > 50 
                           else conversation["user_message"]),
                "importance": conversation["importance_score"],
                "category": self._categorize_memory(conversation),
                "promoted_at": datetime.now().isoformat()
            }
            
            reinforcement_data["core_memories"].append(core_memory)
            
            with open(self.memory_reinforcement_file, 'w', encoding='utf-8') as f:
                json.dump(reinforcement_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"[记忆管理] 核心记忆已保存")
            
        except Exception as e:
            logger.error(f"[记忆管理] 提升核心记忆失败: {e}")
    
    def _categorize_memory(self, conversation: Dict[str, Any]) -> str:
        """根据内容自动分类记忆"""
        full_text = (conversation.get("user_message", "") + 
                    " " + conversation.get("bot_response", "")).lower()
        
        if any(kw in full_text for kw in ["生日", "纪念", "节日", "周年"]):
            return "important_date"
        elif any(kw in full_text for kw in ["成功", "完成", "突破", "成就"]):
            return "achievement"
        elif any(kw in full_text for kw in ["承诺", "决定", "目标", "计划"]):
            return "commitment"
        elif any(kw in full_text for kw in ["爱", "感谢", "珍惜", "感动"]):
            return "emotional"
        else:
            return "general"
    
    # ========== 记忆遗忘机制 ==========
    
    def apply_memory_decay(self, days_threshold: int = 30) -> Dict[str, Any]:
        """
        应用记忆衰减 - 根据时间和重要性自动淡出低价值记忆
        
        Args:
            days_threshold: 超过此天数的低重要性记忆开始衰减
        
        Returns:
            统计信息（淘汰数、保留数等）
        """
        try:
            if not self.weighted_conversations_file.exists():
                return {"decayed": 0, "kept": 0, "archived": 0}
            
            with open(self.weighted_conversations_file, 'r', encoding='utf-8') as f:
                conversations = [json.loads(line) for line in f if line.strip()]
            
            now = datetime.now()
            decayed_count = 0
            kept_count = 0
            archived_count = 0
            decay_records = []
            
            kept_conversations = []
            
            for conv in conversations:
                conv_time = datetime.fromisoformat(conv["timestamp"])
                age_days = (now - conv_time).days
                
                importance = conv.get("importance_score", 0.5)
                
                # 计算衰减因子
                if age_days > days_threshold and importance < 0.4:
                    # 低重要性 + 时间久 = 应该淘汰
                    decay_factor = max(0, 1 - (age_days - days_threshold) / 90)  # 90天完全遗忘
                    
                    if decay_factor < 0.1:
                        # 记录到衰减日志（存档）
                        decay_record = {
                            "timestamp": conv["timestamp"],
                            "user_id": conv["user_id"],
                            "archived_at": datetime.now().isoformat(),
                            "reason": "low_importance_timeout",
                            "summary": conv["user_message"][:100]
                        }
                        decay_records.append(decay_record)
                        archived_count += 1
                        decayed_count += 1
                        continue  # 不保存这条记录
                    else:
                        # 衰减但保留
                        conv["decay_factor"] = decay_factor
                        decayed_count += 1
                
                kept_conversations.append(conv)
                kept_count += 1
            
            # 重写文件（保留未遗忘的记忆）
            with open(self.weighted_conversations_file, 'w', encoding='utf-8') as f:
                for conv in kept_conversations:
                    f.write(json.dumps(conv, ensure_ascii=False) + "\n")
            
            # 记录衰减历史
            if decay_records:
                with open(self.memory_decay_log_file, 'a', encoding='utf-8') as f:
                    for record in decay_records:
                        f.write(json.dumps(record, ensure_ascii=False) + "\n")
            
            result = {
                "decayed": decayed_count,
                "kept": kept_count,
                "archived": archived_count
            }
            
            logger.info(f"[记忆管理] 记忆衰减完成: {result}")
            
            return result
            
        except Exception as e:
            logger.error(f"[记忆管理] 记忆衰减失败: {e}")
            return {"decayed": 0, "kept": 0, "archived": 0, "error": str(e)}
    
    def mark_trivial_memory(self, memory_id: str, reason: str = "trivial") -> None:
        """
        标记琐碎记忆，加速其衰减
        
        Args:
            memory_id: 记忆ID（timestamp）
            reason: 标记原因
        """
        try:
            if not self.weighted_conversations_file.exists():
                return
            
            with open(self.weighted_conversations_file, 'r', encoding='utf-8') as f:
                conversations = [json.loads(line) for line in f if line.strip()]
            
            # 查找并标记
            for conv in conversations:
                if conv["timestamp"] == memory_id:
                    conv["is_trivial"] = True
                    conv["trivial_reason"] = reason
                    conv["importance_score"] = max(0, conv.get("importance_score", 0.5) - 0.3)
                    break
            
            # 重写文件
            with open(self.weighted_conversations_file, 'w', encoding='utf-8') as f:
                for conv in conversations:
                    f.write(json.dumps(conv, ensure_ascii=False) + "\n")
            
            logger.debug(f"[记忆管理] 琐碎标记已添加: {memory_id}")
            
        except Exception as e:
            logger.error(f"[记忆管理] 标记琐碎记忆失败: {e}")
    
    # ========== 记忆检索与分析 ==========
    
    def get_important_memories(self, user_id: Optional[str] = None, 
                               threshold: float = 0.7,
                               limit: int = 10) -> List[Dict[str, Any]]:
        """
        检索高重要性记忆
        
        Args:
            user_id: 用户ID（可选）
            threshold: 重要性阈值
            limit: 最大返回数
        
        Returns:
            重要记忆列表
        """
        try:
            if not self.weighted_conversations_file.exists():
                return []
            
            with open(self.weighted_conversations_file, 'r', encoding='utf-8') as f:
                conversations = [json.loads(line) for line in f if line.strip()]
            
            # 过滤和排序
            filtered = [
                c for c in conversations 
                if c.get("importance_score", 0) >= threshold
                and (user_id is None or c.get("user_id") == user_id)
                and not c.get("is_trivial", False)
            ]
            
            # 按重要性和衰减因子排序
            sorted_memories = sorted(
                filtered,
                key=lambda x: (
                    x.get("importance_score", 0) * x.get("decay_factor", 1.0),
                    x.get("timestamp", "")
                ),
                reverse=True
            )
            
            return sorted_memories[:limit]
            
        except Exception as e:
            logger.error(f"[记忆管理] 检索重要记忆失败: {e}")
            return []
    
    def get_memory_statistics(self) -> Dict[str, Any]:
        """获取记忆系统统计信息"""
        try:
            if not self.weighted_conversations_file.exists():
                return {"total": 0, "important": 0, "trivial": 0}
            
            with open(self.weighted_conversations_file, 'r', encoding='utf-8') as f:
                conversations = [json.loads(line) for line in f if line.strip()]
            
            total = len(conversations)
            important = sum(1 for c in conversations if c.get("importance_score", 0) >= 0.7)
            trivial = sum(1 for c in conversations if c.get("is_trivial", False))
            average_importance = sum(c.get("importance_score", 0) for c in conversations) / max(total, 1)
            
            return {
                "total_memories": total,
                "important_memories": important,
                "trivial_memories": trivial,
                "average_importance": round(average_importance, 2),
                "memory_retention_rate": f"{(1 - trivial/max(total, 1))*100:.1f}%"
            }
            
        except Exception as e:
            logger.error(f"[记忆管理] 统计失败: {e}")
            return {}
    
    def get_memory_reinforcement_summary(self) -> Dict[str, Any]:
        """获取记忆强化摘要"""
        try:
            with open(self.memory_reinforcement_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            return {
                "core_memories_count": len(data.get("core_memories", [])),
                "important_memories_count": len(data.get("important_memories", [])),
                "total_reinforcements": len(data.get("reinforcement_log", [])),
                "last_review": data.get("last_review"),
                "core_categories": self._analyze_core_memory_categories(data.get("core_memories", []))
            }
            
        except Exception as e:
            logger.error(f"[记忆管理] 获取强化摘要失败: {e}")
            return {}
    
    def _analyze_core_memory_categories(self, core_memories: List[Dict]) -> Dict[str, int]:
        """分析核心记忆的分类"""
        categories = {}
        for memory in core_memories:
            category = memory.get("category", "general")
            categories[category] = categories.get(category, 0) + 1
        return categories
