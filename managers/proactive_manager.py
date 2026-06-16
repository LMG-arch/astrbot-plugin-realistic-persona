import random
import time
from datetime import datetime

from astrbot.api import logger

from .base import BaseManager


class ProactiveManager(BaseManager):
    """Manages proactive messaging: greetings, sharing, session discovery."""

    FALLBACK_GREETINGS = [
        "在吗？最近怎么样？😊",
        "很久没聊天了，忙吗？",
        "很久不见，有空聊聊吗？",
        "最近过得好吗？😌",
        "有空聊聊天吗？好久不见了！",
    ]

    async def send_proactive_message(
        self, message: str, session_id: str, context_data: dict
    ):
        """Callback for sending proactive messages."""
        try:
            if not session_id:
                logger.warning("[主动消息] 缺少session_id，无法发送")
                return

            if not message:
                user_id = context_data.get("user_id", "")
                message = await self.generate_proactive_greeting(user_id)
                if not message:
                    logger.warning("[主动消息] 无法生成问候消息，跳过")
                    return

            logger.info(f"[主动消息] 准备发送到会话 {session_id}: {message[:50]}...")
            logger.info(f"[主动消息] 内容: {message}")

            from astrbot.api.event import MessageChain, Plain

            chain = MessageChain([Plain(message)])
            try:
                sent = await self.context.send_message(session_id, chain)
                if sent:
                    logger.info(f"[主动消息] 已发送到会话 {session_id}")
                else:
                    logger.warning(
                        f"[主动消息] 未找到匹配平台，消息未发送: {session_id}"
                    )
            except Exception as e:
                logger.warning(f"[主动消息] 发送失败: {e}")
                logger.warning(f"[主动消息] 消息已生成但未能发送: {message[:50]}...")

        except Exception as e:
            logger.error(f"[主动消息] 发送失败: {e}", exc_info=True)

    async def generate_proactive_greeting(
        self, session_id: str = "", life_manager=None
    ) -> str:
        """Generate proactive greeting message based on history context."""
        try:
            context_parts = []
            now = datetime.now()

            if session_id:
                try:
                    conversation_history = await self.get_recent_conversation_context(
                        session_id
                    )
                    if conversation_history:
                        context_parts.append(
                            f"[最近对话回顾：{' '.join(conversation_history[:3])}]"
                        )
                except Exception as e:
                    logger.debug(f"获取对话历史失败: {e}")

            if life_manager:
                try:
                    schedule_info = await life_manager.maybe_generate_schedule(now)
                    if schedule_info:
                        context_parts.append(f"[今日日程：{schedule_info[:200]}]")
                except Exception as e:
                    logger.debug(f"获取日程失败: {e}")

            try:
                if hasattr(self.state, "_weather_cache") and self.state._weather_cache:
                    weather_info = self.state._weather_cache.get("data")
                    if weather_info:
                        context_parts.append(f"[当前天气：{weather_info}]")
            except Exception as e:
                logger.debug(f"获取天气失败: {e}")

            try:
                if hasattr(self.state, "_news_cache") and self.state._news_cache:
                    news_info = self.state._news_cache.get("data")
                    if news_info:
                        context_parts.append(f"[今日新闻：{news_info[:150]}]")
            except Exception as e:
                logger.debug(f"获取新闻失败: {e}")

            try:
                if self.state.experience_bank and session_id:
                    recent_exp = self.state.experience_bank.get_recent_conversations(
                        session_id, limit=3
                    )
                    if recent_exp:
                        exp_texts = [
                            c.get("bot_response", "")
                            for c in recent_exp
                            if c.get("bot_response")
                        ]
                        if exp_texts:
                            context_parts.append(
                                f"[最近互动：{'；'.join(exp_texts[:2])}]"
                            )
            except Exception as e:
                logger.debug(f"获取经历信息失败: {e}")

            context_info = "\n".join(context_parts) if context_parts else ""

            persona_profile = await self.state.get_persona_profile()
            greeting_prompt = (
                f"你是{self.state.persona_name}，{persona_profile}。\n"
                f"现在是{now.strftime('%Y年%m月%d日 %H:%M')}。\n"
                f"你注意到用户很久没来聊天了，想主动联系一下。\n"
                f"{context_info}\n\n"
                "请生成一条自然、亲切、符合你人设的主动问候消息，不要超过15个字。\n"
                "要求：\n"
                "1. 语气自然，像真人一样聊天\n"
                "2. 可以结合当前时间、天气、日程或之前的对话内容\n"
                "3. 表达关心或好奇，邀请用户聊天\n"
                "4. 不要使用过于正式的语言\n"
                "5. 不要提及你是AI或机器人\n\n"
                "消息内容："
            )

            provider_id = self.state.get_provider_id()
            if provider_id and self.context and hasattr(self.context, "llm_generate"):
                try:
                    resp = await self.context.llm_generate(
                        chat_provider_id=provider_id,
                        prompt=greeting_prompt,
                    )
                    generated_greeting = (resp.completion_text or "").strip()
                    if generated_greeting:
                        # Enforce 15-character limit as requested in the prompt
                        if len(generated_greeting) > 15:
                            generated_greeting = generated_greeting[:15]
                        logger.info(f"[主动消息] LLM生成问候: {generated_greeting}")
                        return generated_greeting
                except Exception as e:
                    logger.debug(f"LLM生成问候失败: {e}")

            greetings = self.FALLBACK_GREETINGS + [
                f"{self.state.persona_name}，在忙什么呢？",
            ]
            return random.choice(greetings)
        except Exception as e:
            logger.error(f"生成主动问候失败: {e}")
            greetings = self.FALLBACK_GREETINGS + [
                f"{self.state.persona_name}，在忙什么呢？",
            ]
            return random.choice(greetings)

    async def get_recent_conversation_context(self, session_id: str) -> list:
        """Get recent conversation context."""
        try:
            if self.state.experience_bank:
                recent_conversations = (
                    self.state.experience_bank.get_recent_conversations(
                        session_id, limit=5
                    )
                )
                if recent_conversations:
                    user_messages = []
                    for conv in recent_conversations:
                        if "user_message" in conv and conv["user_message"]:
                            user_messages.append(conv["user_message"])
                    return user_messages
        except Exception as e:
            logger.debug(f"获取对话历史上下文失败: {e}")
        return []

    async def check_and_share_life(self, life_manager=None):
        """Check if in allowed time range and generate/send proactive share."""
        try:
            now = datetime.now()
            current_hour = now.hour

            if life_manager and not life_manager.is_in_share_time_range(current_hour):
                logger.debug(
                    f"[主动分享] 当前时间 {current_hour}:00 不在分享时间段内，跳过"
                )
                return

            target_sessions = self.config.get("proactive_target_sessions", "")
            if not target_sessions:
                logger.debug("[主动分享] 未配置目标会话白名单，跳过")
                return

            allowed = [s.strip() for s in target_sessions.split(",") if s.strip()]
            if not allowed:
                return

            for session_id in allowed:
                try:
                    share_content = await self.generate_proactive_share(
                        session_id, life_manager=life_manager
                    )
                    if not share_content:
                        logger.debug(f"[主动分享] 未能为会话 {session_id} 生成分享内容")
                        continue

                    from astrbot.api.event import MessageChain, Plain

                    chain = MessageChain([Plain(share_content)])
                    try:
                        sent = await self.context.send_message(session_id, chain)
                        if sent:
                            logger.info(
                                f"[主动分享] 已发送到会话 {session_id}: {share_content[:50]}..."
                            )
                        else:
                            logger.warning(f"[主动分享] 消息未发送到会话 {session_id}")
                    except Exception as e:
                        logger.warning(f"[主动分享] 发送到会话 {session_id} 失败: {e}")
                except Exception as e:
                    logger.error(f"[主动分享] 处理会话 {session_id} 失败: {e}")

        except Exception as e:
            logger.error(f"[主动分享] 执行失败: {e}", exc_info=True)

    async def generate_proactive_share(self, session_id: str, life_manager=None) -> str:
        """Generate proactive share content."""
        try:
            now = datetime.now()
            context_parts = []
            persona_profile = await self.state.get_persona_profile()

            if life_manager:
                try:
                    schedule_info = await life_manager.maybe_generate_schedule(now)
                    if schedule_info:
                        current_activity = life_manager.get_current_schedule_item(
                            schedule_info, now
                        )
                        if current_activity:
                            context_parts.append(f"[当前日程活动：{current_activity}]")
                        else:
                            context_parts.append(
                                f"[今日日程（参考）：{schedule_info[:200]}]"
                            )
                except Exception as e:
                    logger.debug(f"[主动分享] 获取日程失败: {e}")

            try:
                if hasattr(self.state, "_weather_cache") and self.state._weather_cache:
                    weather_info = self.state._weather_cache.get("data")
                    if weather_info:
                        context_parts.append(f"[当前天气：{weather_info}]")
            except Exception as e:
                logger.debug(f"[主动分享] 获取天气失败: {e}")

            try:
                if self.state.experience_bank:
                    recent_convs = self.state.experience_bank.get_recent_conversations(
                        session_id, limit=5
                    )
                    if recent_convs:
                        conv_summaries = []
                        for conv in recent_convs[-3:]:
                            user_msg = conv.get("user_message", "")
                            bot_msg = conv.get("bot_response", "")
                            if user_msg:
                                conv_summaries.append(f"用户说: {user_msg[:50]}")
                            if bot_msg:
                                conv_summaries.append(f"我说: {bot_msg[:50]}")
                        if conv_summaries:
                            context_parts.append(
                                f"[最近对话：{'; '.join(conv_summaries)}]"
                            )
            except Exception as e:
                logger.debug(f"[主动分享] 获取对话历史失败: {e}")

            try:
                if self.state.experience_bank:
                    recent_events = self.state.experience_bank.get_recent_events(
                        limit=3
                    )
                    if recent_events:
                        event_texts = [
                            e.get("description", "")
                            for e in recent_events
                            if e.get("description")
                        ]
                        if event_texts:
                            context_parts.append(
                                f"[最近经历：{'；'.join(event_texts[:3])}]"
                            )
            except Exception as e:
                logger.debug(f"[主动分享] 获取经历失败: {e}")

            try:
                if (
                    hasattr(self.state, "personality_evolution")
                    and self.state.personality_evolution
                ):
                    evo_summary = (
                        self.state.personality_evolution.get_personality_summary()
                    )
                    if evo_summary:
                        expr = evo_summary.get("expression_levels", {})
                        if expr:
                            vocab = expr.get("vocabulary", 5)
                            humor = expr.get("humor", 5)
                            context_parts.append(
                                f"[性格特点：词汇水平{vocab}/10，幽默感{humor}/10]"
                            )
            except Exception as e:
                logger.debug(f"[主动分享] 获取人格演化失败: {e}")

            time_desc = ""
            if life_manager:
                time_desc = life_manager.get_time_description(now)

            context_info = "\n".join(context_parts) if context_parts else ""

            share_prompt = (
                f"你是{self.state.persona_name}，{persona_profile}。\n"
                f"现在是{now.strftime('%Y年%m月%d日 %H:%M')}，{time_desc}。\n"
                f"{context_info}\n\n"
                "你正在社交平台上主动分享自己的生活状态。\n"
                "请生成一条自然的生活分享/状态更新，要求：\n"
                "1. 像真人发朋友圈/空间一样自然随意\n"
                "2. 结合当前时间、正在做的事情（根据日程）、天气、心情\n"
                "3. 如果有最近的对话或经历，可以自然地提及或呼应\n"
                "4. 表达当下的真实感受和状态，不要太刻意\n"
                "5. 控制在30字以内，可以带表情\n"
                "6. 不要提及你是AI或机器人\n"
                "7. 不要每次都用相同的句式，内容要有变化\n"
                "8. 可以是感慨、吐槽、分享趣事、表达心情等多种形式\n\n"
                "生活分享内容："
            )

            provider_id = self.state.get_provider_id()
            if provider_id and self.context and hasattr(self.context, "llm_generate"):
                try:
                    resp = await self.context.llm_generate(
                        chat_provider_id=provider_id,
                        prompt=share_prompt,
                    )
                    generated_share = (resp.completion_text or "").strip()
                    if generated_share:
                        logger.info(f"[主动分享] LLM生成分享: {generated_share}")
                        return generated_share
                except Exception as e:
                    logger.debug(f"[主动分享] LLM生成失败: {e}")

            if life_manager:
                return life_manager.build_fallback_share(now)
            return ""

        except Exception as e:
            logger.error(f"[主动分享] 生成分享内容失败: {e}")
            return ""

    async def get_available_sessions(self) -> list[dict]:
        """Get known sessions via AstrBot DB API."""
        sessions = []
        try:
            db = self.context.get_db()
            if db and hasattr(db, "get_session_conversations"):
                result = await db.get_session_conversations(page=1, page_size=50)
                if result:
                    conv_list = result[0] if isinstance(result, tuple) else result
                    for conv in conv_list:
                        session_info = {
                            "session_id": conv.get("session_id", ""),
                            "persona_name": conv.get("persona_name", ""),
                            "title": conv.get("title", ""),
                        }
                        if session_info["session_id"]:
                            sessions.append(session_info)
        except Exception as e:
            logger.debug(f"[主动消息] 获取会话列表失败: {e}")
        return sessions

    # Loneliness-triggered proactive messaging: rate-limited to once per hour
    _last_loneliness_trigger: float = 0.0
    _loneliness_cooldown: int = 3600

    async def check_loneliness_and_act(self, life_manager=None):
        """Check psychology engine for loneliness and send a proactive message.

        Rate-limited: triggers at most once per hour.
        Only acts when a target session whitelist is configured.
        """
        try:
            if not self.state.psychology_engine:
                return

            # Rate limit check
            now_ts = time.time()
            if now_ts - self._last_loneliness_trigger < self._loneliness_cooldown:
                logger.debug("[孤独感检查] 冷却中，跳过")
                return

            connection = self.state.psychology_engine.check_connection_need()
            if not connection.get("feels_lonely"):
                return

            target_sessions = self.config.get("proactive_target_sessions", "")
            if not target_sessions:
                logger.debug("[孤独感检查] 未配置目标会话白名单，跳过")
                return

            allowed = [s.strip() for s in target_sessions.split(",") if s.strip()]
            if not allowed:
                return

            # Pick the first allowed session
            session_id = allowed[0]

            logger.info(
                f"[孤独感检查] 角色感到孤独（已无互动"
                f"{connection.get('time_since_interaction', 0):.0f}秒），"
                f"向会话 {session_id} 发送主动消息"
            )

            greeting = await self.generate_proactive_greeting(
                session_id=session_id, life_manager=life_manager
            )
            if greeting:
                from astrbot.api.event import MessageChain, Plain

                chain = MessageChain([Plain(greeting)])
                try:
                    sent = await self.context.send_message(session_id, chain)
                    if sent:
                        self._last_loneliness_trigger = now_ts
                        logger.info(f"[孤独感检查] 已发送孤独感问候到 {session_id}")
                    else:
                        logger.warning(f"[孤独感检查] 消息未发送到 {session_id}")
                except Exception as e:
                    logger.warning(f"[孤独感检查] 发送失败: {e}")

        except Exception as e:
            logger.error(f"[孤独感检查] 执行失败: {e}")
