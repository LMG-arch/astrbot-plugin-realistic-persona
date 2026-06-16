"""
经历累积和关系网络管理
记录所有对话、事件和用户互动模式，形成持续性记忆银行
"""

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from astrbot.api import logger

from .utils import atomic_write_json

try:
    from .timeline_verifier import TimelineVerifier

    TIMELINE_AVAILABLE = True
except ImportError:
    TIMELINE_AVAILABLE = False
    logger.debug("[经历银行] TimelineVerifier 未找到，时间线验证功能将被禁用")


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
        # 长期项目文件
        self.projects_file = self.data_dir / "projects.jsonl"
        # 承诺文件
        self.promises_file = self.data_dir / "promises.jsonl"
        # 生物钟文件
        self.circadian_file = self.data_dir / "circadian.jsonl"
        # 人格分化文件
        self.personality_file = self.data_dir / "personalities.jsonl"

        # File lock for concurrent read-modify-write operations
        self._file_lock = asyncio.Lock()

        # JSONL rotation: max lines before truncation (0 = unlimited)
        self._max_conversation_lines: int = 5000
        self._max_event_lines: int = 5000
        # Check rotation every N records (avoid checking on every single append)
        self._rotation_check_counter: int = 0
        self._rotation_check_interval: int = 100

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
                file_path.write_text("", encoding="utf-8")

        if not self.growth_file.exists():
            self.growth_file.write_text(
                json.dumps(
                    {
                        "skills": {},
                        "interests": [],
                        "views": [],
                        "updated_at": datetime.now().isoformat(),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

        if not self.relationships_file.exists():
            self.relationships_file.write_text(
                json.dumps({}, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    def record_conversation(
        self,
        user_id: str,
        user_message: str,
        bot_response: str,
        session_id: str | None = None,
    ):
        """
        记录对话内容

        Args:
            user_id: 用户ID
            user_message: 用户消息
            bot_response: 机器人回复
            session_id: 会话ID
        """
        try:
            now = datetime.now()
            record = {
                "timestamp": now.isoformat(),
                "date": now.strftime("%Y-%m-%d"),
                "user_id": user_id,
                "session_id": session_id,
                "user_message": user_message,
                "bot_response": bot_response,
                "message_length": len(user_message),
                "response_length": len(bot_response),
            }

            with open(self.conversations_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

            # 更新关系网络
            self._update_relationship_sync(
                user_id,
                {
                    "last_chat": now.isoformat(),
                    "interaction_type": "conversation",
                },
            )

            logger.info(f"[经历银行] 对话已记录: 用户 {user_id}")

            # Periodic rotation check
            self._maybe_rotate_jsonl(
                self.conversations_file, self._max_conversation_lines
            )

        except Exception as e:
            logger.error(f"[经历银行] 记录对话失败: {e}")

    def record_event(
        self,
        event_type: str,
        description: str,
        related_user_id: str | None = None,
        metadata: dict | None = None,
    ):
        """
        记录发生的事件

        Args:
            event_type: 事件类型（如"birthday", "anniversary", "milestone"等）
            description: 事件描述
            related_user_id: 相关用户ID
            metadata: 其他元数据
        """
        try:
            now = datetime.now()
            record = {
                "timestamp": now.isoformat(),
                "date": now.strftime("%Y-%m-%d"),
                "event_type": event_type,
                "description": description,
                "related_user_id": related_user_id,
                "metadata": metadata or {},
            }

            with open(self.events_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

            logger.info(f"[经历银行] 事件已记录: {event_type}")

            # Periodic rotation check
            self._maybe_rotate_jsonl(self.events_file, self._max_event_lines)

        except Exception as e:
            logger.error(f"[经历银行] 记录事件失败: {e}")

    def get_recent_conversations(
        self, session_id: str | None = None, limit: int = 5
    ) -> list[dict]:
        """Get recent conversation records (tail-optimized).

        Reads from the end of the file using a deque with maxlen to cap
        memory usage, avoiding loading the entire file into RAM.

        Args:
            session_id: Filter by session ID, or None for all sessions.
            limit: Maximum number of records to return.

        Returns:
            List of conversation dicts, most recent first.
        """
        try:
            if not self.conversations_file.exists():
                return []
            from collections import deque

            results: deque = deque(maxlen=limit * 3 if session_id else limit)
            with open(self.conversations_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        if session_id and record.get("session_id") != session_id:
                            continue
                        results.append(record)
                    except json.JSONDecodeError:
                        continue
            # Return most recent first
            items = list(results)
            items.reverse()
            return items[:limit]
        except Exception as e:
            logger.error(f"[经历银行] 获取最近对话失败: {e}")
            return []

    def get_recent_events(
        self, event_type: str | None = None, limit: int = 5
    ) -> list[dict]:
        """Get recent event records (tail-optimized with deque).

        Args:
            event_type: Filter by event type, or None for all types.
            limit: Maximum number of records to return.

        Returns:
            List of event dicts, most recent first.
        """
        try:
            if not self.events_file.exists():
                return []
            from collections import deque

            results: deque = deque(maxlen=limit * 3 if event_type else limit)
            with open(self.events_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        if event_type and record.get("event_type") != event_type:
                            continue
                        results.append(record)
                    except json.JSONDecodeError:
                        continue
            items = list(results)
            items.reverse()
            return items[:limit]
        except Exception as e:
            logger.error(f"[经历银行] 获取最近事件失败: {e}")
            return []

    async def update_growth(
        self,
        growth_type: str,
        item: str,
        level: int | None = None,
        validate_smoothness: bool = True,
    ):
        """
        更新成长轨迹（支持平滑性验证）

        Args:
            growth_type: 成长类型（"skills", "interests", "views"）
            item: 具体项目
            level: 等级/进度（可选）
            validate_smoothness: 是否验证成长平滑性
        """
        async with self._file_lock:
            self._update_growth_sync(growth_type, item, level, validate_smoothness)

    def _update_growth_sync(
        self,
        growth_type: str,
        item: str,
        level: int | None = None,
        validate_smoothness: bool = True,
    ):
        try:
            now = datetime.now()
            with open(self.growth_file, encoding="utf-8") as f:
                growth_data = json.load(f)

            if growth_type == "skills":
                # 技能升级平滑性验证
                if item in growth_data["skills"] and level and validate_smoothness:
                    old_level = growth_data["skills"][item].get("level", 1)
                    level_jump = abs(level - old_level)

                    # 平滑性检查：等级变化不应超过3级
                    if level_jump > 3:
                        logger.warning(
                            f"[经历银行] 技能等级变化过大: {item} {old_level}->{level}，调整为渐进式提升"
                        )
                        # 调整为渐进升级
                        level = old_level + min(
                            3, level_jump if level > old_level else -3
                        )

                if item not in growth_data["skills"]:
                    growth_data["skills"][item] = {
                        "level": 1,
                        "first_learned": now.isoformat(),
                        "last_used": now.isoformat(),
                        "growth_history": [],  # 成长历史
                    }
                else:
                    if level:
                        # 记录成长历史
                        growth_data["skills"][item].setdefault(
                            "growth_history", []
                        ).append(
                            {
                                "from_level": growth_data["skills"][item]["level"],
                                "to_level": level,
                                "changed_at": now.isoformat(),
                            }
                        )
                        growth_data["skills"][item]["level"] = level
                    growth_data["skills"][item]["last_used"] = now.isoformat()

            elif growth_type == "interests":
                # 检查是否已存在
                existing_interests = [i.get("item") for i in growth_data["interests"]]
                if item not in existing_interests:
                    growth_data["interests"].append(
                        {"item": item, "discovered_at": now.isoformat()}
                    )
                    logger.info(f"[经历银行] 新兴趣已添加: {item}")

            elif growth_type == "views":
                # 观点平滑性检查：避免短期内添加相反观点
                if validate_smoothness and growth_data["views"]:
                    recent_views = growth_data["views"][-5:]  # 最近5个观点
                    for recent in recent_views:
                        # 简单检查时间间隔（至少间7天）
                        formed_at = datetime.fromisoformat(
                            recent.get("formed_at", datetime.now().isoformat())
                        )
                        if (datetime.now() - formed_at) < timedelta(days=7):
                            logger.debug("[经历银行] 观点添加频繁，建议间隔至少7天")
                            return

                growth_data["views"].append(
                    {"view": item, "formed_at": now.isoformat()}
                )

            growth_data["updated_at"] = now.isoformat()

            atomic_write_json(self.growth_file, growth_data)

            logger.info(f"[经历银行] 成长轨迹已更新: {growth_type} - {item}")

        except Exception as e:
            logger.error(f"[经历银行] 更新成长失败: {e}")

    async def _update_relationship(
        self, user_id: str, interaction_data: dict[str, Any]
    ):
        """
        更新用户关系网络

        Args:
            user_id: 用户ID
            interaction_data: 互动数据
        """
        async with self._file_lock:
            self._update_relationship_sync(user_id, interaction_data)

    def _update_relationship_sync(self, user_id: str, interaction_data: dict[str, Any]):
        try:
            now = datetime.now()
            with open(self.relationships_file, encoding="utf-8") as f:
                relationships = json.load(f)

            if user_id not in relationships:
                relationships[user_id] = {
                    "first_met": now.isoformat(),
                    "interaction_count": 0,
                    "interaction_patterns": {},
                    "last_interactions": [],
                    "estimated_personality": {},
                    "notes": "",
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

            atomic_write_json(self.relationships_file, relationships)

        except Exception as e:
            logger.error(f"[经历银行] 更新关系网络失败: {e}")

    def get_user_profile(self, user_id: str) -> dict[str, Any] | None:
        """
        获取用户的综合资料（基于历史互动）

        Args:
            user_id: 用户ID

        Returns:
            用户资料字典
        """
        try:
            with open(self.relationships_file, encoding="utf-8") as f:
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
                "interaction_frequency": self._calculate_frequency(
                    user_rel.get("last_interactions", [])
                ),
            }

            return profile

        except Exception as e:
            logger.error(f"[经历银行] 获取用户资料失败: {e}")
            return None

    def _analyze_personality(self, patterns: dict[str, int]) -> list[str]:
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

    def _calculate_frequency(self, interactions: list[dict]) -> str:
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

    def _get_top_skills(self, skills: dict[str, dict]) -> list[str]:
        """获取排名前5的技能"""
        sorted_skills = sorted(
            skills.items(), key=lambda x: x[1].get("level", 0), reverse=True
        )
        return [skill[0] for skill in sorted_skills[:5]]

    def get_growth_summary(self) -> dict[str, Any]:
        """获取成长摘要

        Returns both raw collections (skills/interests/views) for direct
        consumption and aggregate counts (skills_count/etc.) for status views.
        """
        try:
            with open(self.growth_file, encoding="utf-8") as f:
                growth_data = json.load(f)

            skills = growth_data.get("skills", {})
            interests = growth_data.get("interests", [])
            views = growth_data.get("views", [])

            return {
                # Raw collections for direct consumption (skills/interests/views)
                "skills": skills,
                "interests": interests,
                "views": views,
                # Aggregate stats for status/summary views
                "skills_count": len(skills),
                "interests_count": len(interests),
                "views_count": len(views),
                "top_skills": self._get_top_skills(skills),
                "recent_interests": interests[-5:],
                "updated_at": growth_data.get("updated_at"),
            }

        except Exception as e:
            logger.error(f"[经历银行] 获取成长摘要失败: {e}")
            return {}

    # ========== 关系网络智能压缩 ==========

    def extract_relationship_milestones(
        self, user_id: str, max_milestones: int = 10
    ) -> list[dict[str, Any]]:
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
            with open(self.conversations_file, encoding="utf-8") as f:
                conversations = []
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        if record.get("user_id") == user_id:
                            conversations.append(record)
                    except json.JSONDecodeError:
                        continue

            if not conversations:
                return []

            # 显记事件的位置：相比上一次互动剧烈增加
            milestones = []

            # 检测第一次互动（相遇里程碑）
            if conversations:
                first_interaction = conversations[0]
                milestones.append(
                    {
                        "type": "first_meeting",
                        "timestamp": first_interaction["timestamp"],
                        "description": "第一次互动",
                        "interaction_count_at_time": 0,
                    }
                )

            # 检测长对话（消息量大、最吸引人的话题）
            for i, conv in enumerate(conversations):
                msg_len = conv.get("message_length", 0)
                resp_len = conv.get("response_length", 0)

                # 消息较长：可能是重要事项
                if msg_len > 200 or resp_len > 300:
                    milestones.append(
                        {
                            "type": "deep_conversation",
                            "timestamp": conv["timestamp"],
                            "description": "长对话（消息量较大）",
                            "message_length": msg_len,
                            "response_length": resp_len,
                        }
                    )

            # 检测互动频率突然增加（可能是突发情况）
            if len(conversations) > 1:
                avg_interval = (
                    datetime.fromisoformat(conversations[-1]["timestamp"])
                    - datetime.fromisoformat(conversations[0]["timestamp"])
                ).total_seconds() / len(conversations)

                for i in range(1, len(conversations)):
                    prev_time = datetime.fromisoformat(
                        conversations[i - 1]["timestamp"]
                    )
                    curr_time = datetime.fromisoformat(conversations[i]["timestamp"])
                    interval = (curr_time - prev_time).total_seconds()

                    if interval < avg_interval / 5:
                        milestones.append(
                            {
                                "type": "sudden_frequency_increase",
                                "timestamp": conversations[i]["timestamp"],
                                "description": "消息频率突增（很紧急）",
                                "interval": interval,
                            }
                        )

            # 按时间排序并限制数量
            milestones.sort(key=lambda x: x["timestamp"])

            logger.info(f"[经历银行] 已提取{len(milestones)}个关系里程碑: {user_id}")

            return milestones[:max_milestones]

        except Exception as e:
            logger.error(f"[经历银行] 提取关系里程碑失败: {e}")
            return []

    def generate_relationship_profile(self, user_id: str) -> dict[str, Any] | None:
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

            with open(self.relationships_file, encoding="utf-8") as f:
                relationships = json.load(f)

            if user_id not in relationships:
                return None

            user_rel = relationships[user_id]

            # 五维性格模型
            profile = {
                "user_id": user_id,
                "first_met": user_rel.get("first_met"),
                "total_interactions": user_rel.get("interaction_count", 0),
                # 维度：互动模式
                "interaction_patterns": self._analyze_interaction_patterns(
                    user_rel.get("interaction_patterns", {})
                ),
                # 维度：互动频率
                "engagement_level": self._calculate_engagement_level(
                    user_rel.get("last_interactions", [])
                ),
                # 维度：互动强度
                "interaction_intensity": self._calculate_interaction_intensity(
                    user_rel.get("last_interactions", [])
                ),
                # 维度：人格一致性
                "consistency_score": self._analyze_consistency(
                    user_rel.get("last_interactions", [])
                ),
                # 维度：互动特征
                "relationship_characteristics": self._generate_relationship_characteristics(
                    user_rel.get("last_interactions", []),
                    user_rel.get("interaction_patterns", {}),
                ),
                # 每个用户的最近互动摘要
                "recent_interactions_summary": self._summarize_recent_interactions(
                    user_rel.get("last_interactions", [])
                ),
            }

            logger.info(f"[经历银行] 关系已生成: {user_id}")
            return profile

        except Exception as e:
            logger.error(f"[经历银行] 生成关系特征失败: {e}")
            return None

    def _analyze_interaction_patterns(self, patterns: dict[str, int]) -> dict[str, str]:
        """分析互动模式的性质"""
        analysis = {}

        total = sum(patterns.values())
        if total == 0:
            return analysis

        for pattern_type, count in patterns.items():
            percentage = (count / total) * 100

            if pattern_type == "conversation":
                if percentage > 70:
                    analysis["primary_type"] = "以对话为主"
                else:
                    analysis["has_conversation"] = "主要互动形式"
            elif pattern_type == "event":
                if percentage > 50:
                    analysis["event_driven"] = "事件驱动型互动"

        return analysis

    def _calculate_engagement_level(self, interactions: list[dict]) -> str:
        """计算互动频率"""
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

    def _calculate_interaction_intensity(
        self, interactions: list[dict]
    ) -> dict[str, Any]:
        """计算互动强度（亲密程度）"""
        if not interactions:
            return {"level": "低", "score": 0}

        # 计算平均消息长度
        avg_message_len = sum(i.get("message_length", 0) for i in interactions) / len(
            interactions
        )

        # 计算互动间隔变化
        if len(interactions) > 1:
            timestamps = [
                datetime.fromisoformat(i["timestamp"])
                for i in interactions
                if i.get("timestamp")
            ]
            intervals = [
                (timestamps[i + 1] - timestamps[i]).total_seconds()
                for i in range(len(timestamps) - 1)
            ]
            consistency = (
                1 - (max(intervals) / max(intervals + [1])) if intervals else 0.5
            )
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

    def _analyze_consistency(self, interactions: list[dict]) -> float:
        """判断互动的一致性（互动频率及互动风格是否稳定）"""
        if len(interactions) < 2:
            return 0.5

        # 检查最近的消息是否有显著的波动
        message_lengths = [i.get("message_length", 0) for i in interactions[-5:]]

        if not message_lengths:
            return 0.5

        avg = sum(message_lengths) / len(message_lengths)
        variance = sum((x - avg) ** 2 for x in message_lengths) / len(message_lengths)

        # 方差小则一致性高
        consistency = 1 - min(variance / (avg**2 + 1), 1)

        return round(consistency, 2)

    def _generate_relationship_characteristics(
        self, interactions: list[dict], patterns: dict[str, int]
    ) -> list[str]:
        """生成关系特征描述"""
        characteristics = []

        # 基于互动模式
        if patterns.get("conversation", 0) > patterns.get("event", 0):
            characteristics.append("喜欢谈天")

        if patterns.get("event", 0) > 10:
            characteristics.append("事件驱动")

        # 基于互动模式
        if len(interactions) > 10:
            characteristics.append("常客")

        total_interactions = sum(patterns.values())
        if total_interactions > 50:
            characteristics.append("亲密好友")

        # 基于消息长度
        avg_msg_len = sum(i.get("message_length", 0) for i in interactions) / max(
            len(interactions), 1
        )
        if avg_msg_len > 150:
            characteristics.append("深度交流者")

        return characteristics

    def _summarize_recent_interactions(
        self, interactions: list[dict]
    ) -> dict[str, Any]:
        """汇总最近的互动（最近5次）"""
        recent = interactions[-5:] if interactions else []

        if not recent:
            return {"count": 0, "summary": "没有互动纪录"}

        return {
            "count": len(recent),
            "latest_interaction": recent[-1].get("timestamp") if recent else None,
            "total_recent_characters": sum(r.get("message_length", 0) for r in recent),
        }

    # ========== 长期项目追踪 ==========

    def record_project(
        self,
        project_name: str,
        description: str,
        status: str = "in_progress",
        metadata: dict | None = None,
    ):
        """
        记录长期项目（学习课程、书籍、作品等）

        Args:
            project_name: 项目名称
            description: 项目描述
            status: 状态（in_progress/completed/paused）
            metadata: 其他元数据（进度、年份等）
        """
        try:
            now = datetime.now()
            record = {
                "timestamp": now.isoformat(),
                "date": now.strftime("%Y-%m-%d"),
                "project_name": project_name,
                "description": description,
                "status": status,
                "metadata": metadata or {},
            }

            with open(self.projects_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

            logger.info(f"[经历银行] 项目已记录: {project_name} - {status}")

        except Exception as e:
            logger.error(f"[经历银行] 记录项目失败: {e}")

    # ========== 承诺追踪 ==========

    def record_promise(
        self,
        promise: str,
        related_user_id: str | None = None,
        deadline: str | None = None,
        metadata: dict | None = None,
    ):
        """
        记录承诺的事项

        Args:
            promise: 承诺描述
            related_user_id: 相关用户ID
            deadline: 截止日期
            metadata: 其他元数据
        """
        try:
            now = datetime.now()
            record = {
                "timestamp": now.isoformat(),
                "date": now.strftime("%Y-%m-%d"),
                "promise": promise,
                "related_user_id": related_user_id,
                "deadline": deadline,
                "status": "pending",
                "completed_at": None,
                "metadata": metadata or {},
            }

            with open(self.promises_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

            logger.info(f"[经历银行] 承诺已记录: {promise}")

        except Exception as e:
            logger.error(f"[经历银行] 记录承诺失败: {e}")

    async def complete_promise(
        self, promise_keyword: str, completion_note: str | None = None
    ):
        """
        标记承诺为完成

        Args:
            promise_keyword: 承诺的关键词或描述
            completion_note: 完成介绍
        """
        async with self._file_lock:
            self._complete_promise_sync(promise_keyword, completion_note)

    def _complete_promise_sync(
        self, promise_keyword: str, completion_note: str | None = None
    ):
        try:
            if not self.promises_file.exists():
                return

            with open(self.promises_file, encoding="utf-8") as f:
                promises = []
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        promises.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

            updated = False
            for promise in promises:
                if promise_keyword.lower() in promise.get("promise", "").lower():
                    promise["status"] = "completed"
                    promise["completed_at"] = datetime.now().isoformat()
                    if completion_note:
                        promise["completion_note"] = completion_note
                    updated = True

            if updated:
                atomic_write_json(self.promises_file, promises)
                logger.info(f"[经历银行] 承诺已完成: {promise_keyword}")

        except Exception as e:
            logger.error(f"[经历银行] 更新承诺失败: {e}")

    # ========== 时间节律与生物钟 ==========

    def record_circadian_state(
        self, state: str, energy_level: int, creativity_level: int, mood: str
    ):
        """
        记录当前的生物钟状态

        Args:
            state: 状态（清晨/上午/中午/下午/傍晚/深夜）
            energy_level: 精力水平 (1-10)
            creativity_level: 创造力水平 (1-10)
            mood: 情绪 (开心/中性/沮丧)
        """
        try:
            now = datetime.now()
            record = {
                "timestamp": now.isoformat(),
                "hour": now.hour,
                "state": state,
                "energy_level": energy_level,
                "creativity_level": creativity_level,
                "mood": mood,
            }

            with open(self.circadian_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

        except Exception as e:
            logger.debug(f"[经历银行] 记录生物钟失败: {e}")

    # ========== 不同场景的人格分化 ==========

    def record_context_personality(
        self,
        context_type: str,
        traits: list[str],
        tone: str,
        metadata: dict | None = None,
    ):
        """
        记录不同场景下的人格表现

        Args:
            context_type: 上下文类型 (private_chat/group_chat/public)
            traits: 人格特质列表
            tone: 语气风格 (正式/非正式/调皮)
            metadata: 其他元数据
        """
        try:
            now = datetime.now()
            record = {
                "timestamp": now.isoformat(),
                "context_type": context_type,
                "traits": traits,
                "tone": tone,
                "metadata": metadata or {},
            }

            with open(self.personality_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

            logger.info(f"[经历银行] 人格表现已记录: {context_type}")

        except Exception as e:
            logger.error(f"[经历银行] 记录人格失败: {e}")

    def get_context_personality(self, context_type: str) -> dict[str, Any] | None:
        """
        获取指定场景的人格描述
        """
        try:
            if not self.personality_file.exists():
                return None

            with open(self.personality_file, encoding="utf-8") as f:
                personalities = []
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        personalities.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

            # 返回最新的匹配上下文类型
            matching = [
                p for p in personalities if p.get("context_type") == context_type
            ]
            if matching:
                return matching[-1]

            return None

        except Exception as e:
            logger.debug(f"[经历银行] 获取人格失败: {e}")
            return None

    # ========== 时间线验证集成 ==========

    def add_experience_to_timeline(
        self,
        experience_id: str,
        content: str,
        event_type: str = "general",
        event_date: str | None = None,
        related_experiences: list[str] | None = None,
    ) -> bool:
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
                related_experiences=related_experiences,
            )

            if success:
                logger.info(f"[经历银行] 经历已添加到时间线: {experience_id}")

            return success

        except Exception as e:
            logger.error(f"[经历银行] 添加经历到时间线失败: {e}")
            return False

    def get_timeline_coherence_report(self) -> dict[str, Any]:
        """
        获取时间线连贯性报告

        Returns:
            连贯性分析报告
        """
        if not self.timeline_verifier:
            return {"error": "时间线验证器未启用"}

        try:
            # 获取所有经历
            with open(self.events_file, encoding="utf-8") as f:
                events = []
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

            # 分析连贯性
            coherence = self.timeline_verifier.analyze_experience_coherence(events)

            # 添加成长平滑性分析
            growth_smoothness = self._analyze_growth_smoothness()
            coherence["growth_smoothness"] = growth_smoothness

            return coherence

        except Exception as e:
            logger.error(f"[经历银行] 获取时间线报告失败: {e}")
            return {}

    def _analyze_growth_smoothness(self) -> dict[str, Any]:
        """
        分析成长轨迹的平滑性

        Returns:
            平滑性分析结果
        """
        try:
            with open(self.growth_file, encoding="utf-8") as f:
                growth_data = json.load(f)

            skills = growth_data.get("skills", {})
            smoothness_issues = []

            # 检查每个技能的成长历史
            for skill_name, skill_data in skills.items():
                growth_history = skill_data.get("growth_history", [])

                for i in range(len(growth_history)):
                    history = growth_history[i]
                    level_jump = abs(
                        history.get("to_level", 0) - history.get("from_level", 0)
                    )

                    if level_jump > 3:
                        smoothness_issues.append(
                            {
                                "skill": skill_name,
                                "issue": f"等级跃迁过大: {history.get('from_level')} -> {history.get('to_level')}",
                                "timestamp": history.get("changed_at"),
                            }
                        )

            return {
                "is_smooth": len(smoothness_issues) == 0,
                "total_skills": len(skills),
                "issue_count": len(smoothness_issues),
                "issues": smoothness_issues[:5],  # 只返回前5个问题
                "assessment": "平滑" if len(smoothness_issues) == 0 else "有跨越式成长",
            }

        except Exception as e:
            logger.error(f"[经历银行] 分析成长平滑性失败: {e}")
            return {}

    # ========== 沉睡数据读取方法 ==========

    def get_recent_projects(
        self, status: str | None = None, limit: int = 5
    ) -> list[dict[str, Any]]:
        """Read recent project records, optionally filtered by status.

        Args:
            status: Filter by status (in_progress/completed/paused). None = all.
            limit: Max number of records to return.

        Returns:
            List of project dicts, most recent first.
        """
        try:
            if not self.projects_file.exists():
                return []

            projects = []
            with open(self.projects_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        projects.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

            if status:
                projects = [p for p in projects if p.get("status") == status]

            projects.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            return projects[:limit]

        except Exception as e:
            logger.debug(f"[经历银行] 读取项目失败: {e}")
            return []

    def get_pending_promises(self, limit: int = 5) -> list[dict[str, Any]]:
        """Read unfulfilled promises.

        Args:
            limit: Max number of promises to return.

        Returns:
            List of pending promise dicts, most recent first.
        """
        try:
            if not self.promises_file.exists():
                return []

            promises = []
            with open(self.promises_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        promises.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

            pending = [p for p in promises if p.get("status") == "pending"]
            pending.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            return pending[:limit]

        except Exception as e:
            logger.debug(f"[经历银行] 读取承诺失败: {e}")
            return []

    def get_recent_circadian(self, days: int = 1) -> dict[str, Any] | None:
        """Get the most recent circadian state record.

        Args:
            days: Look back this many days for the latest record.

        Returns:
            Latest circadian state dict, or None if no records.
        """
        try:
            if not self.circadian_file.exists():
                return None

            records = []
            with open(self.circadian_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

            if not records:
                return None

            records.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            return records[0] if records else None

        except Exception as e:
            logger.debug(f"[经历银行] 读取生物钟失败: {e}")
            return None

    def get_relationship_profile(self, user_id: str) -> dict[str, Any] | None:
        """Get relationship profile for a specific user.

        Args:
            user_id: The user identifier to look up.

        Returns:
            Dict with interaction_count, last_interaction, milestones_count,
            and relationship_characteristics, or None if no data.
        """
        try:
            if not self.relationships_file.exists():
                return None

            with open(self.relationships_file, encoding="utf-8") as f:
                relationships = json.load(f)

            rel = relationships.get(user_id)
            if not rel:
                return None

            interaction_count = rel.get("interaction_count", 0)
            last_interaction = rel.get("last_interaction", "")

            # Extract milestone count
            milestones = rel.get("milestones", [])
            milestone_count = len(milestones) if isinstance(milestones, list) else 0

            # Determine relationship characteristics from interaction patterns
            characteristics = []
            if interaction_count > 50:
                characteristics.append("互动频繁")
            elif interaction_count > 20:
                characteristics.append("较为熟悉")
            elif interaction_count > 5:
                characteristics.append("初步了解")
            else:
                characteristics.append("刚认识")

            # Check for deep conversations in milestones
            if isinstance(milestones, list):
                deep_count = sum(
                    1 for m in milestones if m.get("type") == "deep_conversation"
                )
                if deep_count > 2:
                    characteristics.append("有过深入交流")

            return {
                "interaction_count": interaction_count,
                "last_interaction": last_interaction,
                "milestones_count": milestone_count,
                "relationship_characteristics": "、".join(characteristics),
            }

        except Exception as e:
            logger.debug(f"[经历银行] 读取关系画像失败: {e}")
            return None

    # ========== JSONL rotation ==========

    def _maybe_rotate_jsonl(self, file_path: Path, max_lines: int) -> None:
        """Check if a JSONL file needs rotation and rotate if so.

        Rotation is only checked every ``_rotation_check_interval`` records
        to avoid stat-ing the file on every single append.  When the line
        count exceeds *max_lines*, the file is truncated to keep only the
        most recent half of the allowed lines.

        Args:
            file_path: Path to the JSONL file.
            max_lines: Maximum number of lines before rotation triggers.
        """
        if max_lines <= 0:
            return

        self._rotation_check_counter += 1
        if self._rotation_check_counter % self._rotation_check_interval != 0:
            return

        try:
            if not file_path.exists():
                return

            line_count = 0
            with open(file_path, encoding="utf-8") as f:
                for _ in f:
                    line_count += 1

            if line_count <= max_lines:
                return

            # Read all valid lines, keep the most recent half
            keep_count = max_lines // 2
            lines: list[str] = []
            with open(file_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        json.loads(line)  # validate
                        lines.append(line)
                    except json.JSONDecodeError:
                        continue

            kept = lines[-keep_count:]
            with open(file_path, "w", encoding="utf-8") as f:
                for line in kept:
                    f.write(line + "\n")

            removed = line_count - len(kept)
            logger.info(
                f"[经历银行] JSONL轮转: {file_path.name} "
                f"{line_count} -> {len(kept)} 行 (移除 {removed} 条旧记录)"
            )

        except Exception as e:
            logger.debug(f"[经历银行] JSONL轮转检查失败: {e}")
