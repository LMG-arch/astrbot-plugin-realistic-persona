import random
from datetime import datetime

from astrbot.api import logger

from .base import BaseManager


class ExperienceManager(BaseManager):
    """Manages experience recording: interactions, growth, projects, promises, circadian states."""

    async def record_interaction_async(
        self, session_id: str, user_message: str, unified_msg_origin: str = ""
    ) -> None:
        """Record user interaction to experience bank."""
        if not self.state.experience_bank:
            return

        try:
            self.state.experience_bank.record_conversation(
                user_id=session_id,
                user_message=user_message,
                bot_response="",
                session_id=session_id,
            )

            if self.state.enable_proactive_messages:
                import time

                current_time = time.time()

                self.state.context_state.update_state(
                    session_id, "last_interaction_time", current_time
                )

                self.state.proactive_manager.clear_scheduled_messages(
                    unified_msg_origin or session_id
                )

                target_sessions = self.config.get("proactive_target_sessions", "")
                if not target_sessions:
                    logger.debug("[主动消息] 未配置目标会话白名单，跳过调度")
                    return

                allowed = [s.strip() for s in target_sessions.split(",") if s.strip()]
                if not allowed or (
                    unified_msg_origin and unified_msg_origin not in allowed
                ):
                    logger.debug(
                        f"[主动消息] 会话 {unified_msg_origin} 不在白名单中，跳过调度"
                    )
                    return

                send_session_id = (
                    unified_msg_origin if unified_msg_origin else session_id
                )

                self.state.proactive_manager.schedule_message(
                    message="",
                    delay=self.state.idle_greeting_delay,
                    session_id=send_session_id,
                    context_data={
                        "triggered_by": "idle_detection",
                        "user_id": session_id,
                        "platform": unified_msg_origin.split(":")[0]
                        if ":" in unified_msg_origin
                        else "unknown",
                    },
                )
                logger.debug(
                    f"[主动消息] 已调度空闲问候，{self.state.idle_greeting_delay}秒后发送"
                )

            self.extract_and_update_growth(user_message)
            self.detect_and_record_projects(user_message, session_id)
            self.detect_and_record_promises(user_message, session_id)
            self.record_circadian_state()

            if self.state.experience_bank and abs(hash(session_id)) % 30 == 0:
                self.analyze_relationship_network(session_id)

            if self.state.psychology_engine:
                self.state.psychology_engine.record_interaction()
                connection_check = self.state.psychology_engine.check_connection_need()
                if connection_check.get("feels_lonely"):
                    logger.debug("[PSYCHOLOGY] 新增需求互动")

            if self.state.memory_manager:
                context_clues = []
                if "记得" in user_message or "求你" in user_message:
                    context_clues.append("需要记录")

                self.state.memory_manager.record_weighted_conversation(
                    user_id=session_id,
                    user_message=user_message,
                    bot_response="",
                    context_clues=context_clues,
                    session_id=session_id,
                )

                if abs(hash(session_id)) % 30 == 0:
                    logger.debug("[记忆管理] 执行记忆衰减")
                    self.state.memory_manager.apply_memory_decay(days_threshold=30)

            if self.state.timeline_verifier:
                time_markers = ["上月", "上周", "去年", "是日", "昨天"]
                mentioned_time = None
                for marker in time_markers:
                    if marker in user_message:
                        mentioned_time = marker
                        break

                if mentioned_time:
                    self.state.timeline_verifier.add_experience(
                        experience_id=f"{session_id}_{datetime.now().timestamp()}",
                        content=user_message[:100],
                        event_date=mentioned_time,
                        event_type="conversation",
                    )

            logger.debug(f"用户交互已记录: {session_id}")

        except Exception as e:
            logger.debug(f"记录用户交互失败: {e}")

    def extract_and_update_growth(self, message: str) -> None:
        """Extract interests, skills etc from user message and update growth tracking."""
        if not self.state.experience_bank:
            return

        try:
            message_lower = message.lower()

            for skill in ["python", "java", "javascript", "c++", "latex"]:
                if skill.lower() in message_lower:
                    self.state.experience_bank.update_growth("skills", skill)

            for interest in ["编程", "旅游", "音乐", "电影", "游戏"]:
                if interest in message:
                    self.state.experience_bank.update_growth("interests", interest)

            if "成长" in message or "加油" in message:
                self.state.experience_bank.update_growth("views", "乐观向上")
            if "伤心" in message or "难过" in message:
                self.state.experience_bank.update_growth("views", "需要陪伴")

        except Exception as e:
            logger.debug(f"提取成长信息失败: {e}")

    def detect_and_record_projects(self, message: str, session_id: str) -> None:
        """Detect and record long-term project progress."""
        if not self.state.experience_bank:
            return

        try:
            if "上月" in message or "上周" in message:
                if "学完" in message or "学了" in message or "学习" in message:
                    project = self.extract_project_name(message)
                    if project:
                        self.state.experience_bank.record_project(
                            project_name=project,
                            description=f"用户提及：{message[:100]}",
                            status="in_progress",
                            metadata={"user_id": session_id},
                        )
                        logger.debug(f"项目已记录: {project}")

        except Exception as e:
            logger.debug(f"检测项目失败: {e}")

    def detect_and_record_promises(self, message: str, session_id: str) -> None:
        """Detect and record promises."""
        if not self.state.experience_bank:
            return

        try:
            completion_keywords = ["完成", "完成了", "做了", "已经", "成功"]
            if any(kw in message for kw in completion_keywords):
                promise_desc = self.extract_promise_description(message)
                if promise_desc:
                    self.state.experience_bank.complete_promise(
                        promise_keyword=promise_desc[:30],
                        completion_note=f"用户提及: {message[:80]}",
                    )
                    logger.debug(f"承诺已标记为完成: {promise_desc}")

            if "记得" in message or "答应" in message or "承诺" in message:
                promise_desc = self.extract_promise_description(message)
                if promise_desc:
                    self.state.experience_bank.record_promise(
                        promise=promise_desc,
                        related_user_id=session_id,
                        metadata={"mentioned_in_message": message[:100]},
                    )
                    logger.debug(f"承诺已记录: {promise_desc}")

        except Exception as e:
            logger.debug(f"检测承诺失败: {e}")

    @staticmethod
    def extract_project_name(message: str) -> str | None:
        """Extract project name from message."""
        keywords = ["课程", "书籍", "作品", "项目"]
        for kw in keywords:
            if kw in message:
                idx = message.find(kw)
                return message[max(0, idx - 10) : min(len(message), idx + 30)].strip()
        return None

    @staticmethod
    def extract_promise_description(message: str) -> str | None:
        """Extract promise description from message."""
        return message[:100].strip() if len(message) > 0 else None

    def record_circadian_state(self) -> None:
        """Record circadian state based on current time."""
        if not self.state.experience_bank:
            return

        try:
            now = datetime.now()
            hour = now.hour

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
                state = "傍晚"
                energy = 6
                creativity = 6
            else:
                state = "深夜"
                energy = 4
                creativity = 5

            energy += random.randint(-2, 2)
            creativity += random.randint(-2, 2)
            mood = random.choice(["开心", "中性", "沮丧"])

            self.state.experience_bank.record_circadian_state(
                state, energy, creativity, mood
            )

        except Exception as e:
            logger.debug(f"记录生物钟失败: {e}")

    def analyze_relationship_network(self, user_id: str) -> None:
        """Perform intelligent compression of relationship network."""
        if not self.state.experience_bank:
            return

        try:
            milestones = self.state.experience_bank.extract_relationship_milestones(
                user_id, max_milestones=10
            )

            if milestones:
                logger.debug(f"[关系网络] 提取事件: {len(milestones)}个")

            profile = self.state.experience_bank.generate_relationship_profile(user_id)

            if profile:
                logger.debug(
                    f"[关系网络] 特征: {profile.get('relationship_characteristics')}"
                )

        except Exception as e:
            logger.debug(f"[关系网络] 分析失败: {e}")
