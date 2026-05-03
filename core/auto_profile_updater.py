"""
基于情绪的自动Profile更新模块
根据情绪变化自动更新QQ昵称、签名和头像
"""

import time
from datetime import datetime
from pathlib import Path

from astrbot.api import logger
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)


class AutoProfileUpdater:
    """自动Profile更新管理器

    根据情绪强度和变化自动更新QQ资料
    支持昵称、签名、头像的智能更新
    支持每日/每周更新次数限制
    """

    def __init__(
        self,
        data_dir: Path,
        enable_nickname: bool = False,
        enable_signature: bool = True,
        enable_avatar: bool = False,
        cooldown: int = 1800,  # 30分钟
        threshold: float = 0.6,  # 情绪强度阈值
        persona_name: str = "AI助手",
        max_updates_per_day: int = 3,
        max_updates_per_week: int = 10,
    ):
        """初始化自动Profile更新器

        Args:
            data_dir: 数据存储目录
            enable_nickname: 是否启用自动昵称更新
            enable_signature: 是否启用自动签名更新
            enable_avatar: 是否启用自动头像更新
            cooldown: 更新冷却时间（秒）
            threshold: 情绪变化阈值（0-1）
            persona_name: 角色名称
            max_updates_per_day: 每天最大更新次数
            max_updates_per_week: 每周最大更新次数（0表示不限制）
        """
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.enable_nickname = enable_nickname
        self.enable_signature = enable_signature
        self.enable_avatar = enable_avatar
        self.cooldown = cooldown
        self.threshold = threshold
        self.persona_name = persona_name
        self.max_updates_per_day = max_updates_per_day
        self.max_updates_per_week = max_updates_per_week

        # 状态文件
        self.state_file = self.data_dir / "profile_update_state.json"

        # 加载状态
        self.state = self._load_state()

        # 头像存储目录
        self.avatar_dir = self.data_dir / "avatars"
        self.avatar_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            f"[Profile更新器] 初始化完成 - 昵称:{enable_nickname}, 签名:{enable_signature}, 头像:{enable_avatar}"
        )

    def _load_state(self) -> dict:
        """加载状态"""
        import json

        if self.state_file.exists():
            try:
                with open(self.state_file, encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"[Profile更新器] 加载状态失败: {e}")

        return {
            "last_nickname_update": 0,
            "last_signature_update": 0,
            "last_avatar_update": 0,
            "current_nickname": "",
            "current_signature": "",
            "emotion_history": [],
            "daily_update_count": 0,
            "daily_update_date": "",
            "weekly_update_count": 0,
            "weekly_update_week": "",
            "update_history": [],
        }

    def _save_state(self):
        """保存状态"""
        import json

        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[Profile更新器] 保存状态失败: {e}")

    def _check_frequency_limit(self) -> bool:
        """检查是否超过每日/每周更新频率限制

        Returns:
            是否允许更新（True=允许，False=超限）
        """
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        week_str = now.strftime("%Y-W%W")

        # 重置每日计数（如果日期变了）
        if self.state.get("daily_update_date") != today_str:
            self.state["daily_update_count"] = 0
            self.state["daily_update_date"] = today_str

        # 重置每周计数（如果周变了）
        if self.state.get("weekly_update_week") != week_str:
            self.state["weekly_update_count"] = 0
            self.state["weekly_update_week"] = week_str

        # 检查每日限制
        if self.state["daily_update_count"] >= self.max_updates_per_day:
            logger.debug(
                f"[Profile更新器] 今日已更新{self.state['daily_update_count']}次，达到上限{self.max_updates_per_day}"
            )
            return False

        # 检查每周限制
        if (
            self.max_updates_per_week > 0
            and self.state["weekly_update_count"] >= self.max_updates_per_week
        ):
            logger.debug(
                f"[Profile更新器] 本周已更新{self.state['weekly_update_count']}次，达到上限{self.max_updates_per_week}"
            )
            return False

        return True

    def _can_update(self, update_type: str) -> bool:
        """检查是否可以更新

        Args:
            update_type: 更新类型 (nickname/signature/avatar)

        Returns:
            是否可以更新
        """
        last_update_key = f"last_{update_type}_update"
        last_update = self.state.get(last_update_key, 0)
        current_time = time.time()

        if current_time - last_update < self.cooldown:
            remaining = int(self.cooldown - (current_time - last_update))
            logger.debug(f"[Profile更新器] {update_type}更新冷却中，还需{remaining}秒")
            return False

        return True

    def _record_update(self, update_type: str):
        """记录更新时间和更新频率

        Args:
            update_type: 更新类型
        """
        last_update_key = f"last_{update_type}_update"
        self.state[last_update_key] = time.time()

        # 递增每日/每周更新计数
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        week_str = now.strftime("%Y-W%W")

        if self.state.get("daily_update_date") != today_str:
            self.state["daily_update_count"] = 0
            self.state["daily_update_date"] = today_str
        self.state["daily_update_count"] = self.state.get("daily_update_count", 0) + 1

        if self.state.get("weekly_update_week") != week_str:
            self.state["weekly_update_count"] = 0
            self.state["weekly_update_week"] = week_str
        self.state["weekly_update_count"] = self.state.get("weekly_update_count", 0) + 1

        # 记录更新历史
        if "update_history" not in self.state:
            self.state["update_history"] = []
        self.state["update_history"].append(
            {
                "type": update_type,
                "timestamp": time.time(),
                "date": today_str,
            }
        )
        # 只保留最近30条
        self.state["update_history"] = self.state["update_history"][-30:]

        self._save_state()
        logger.debug(
            f"[Profile更新器] {update_type}更新已记录，今日{self.state['daily_update_count']}次，本周{self.state['weekly_update_count']}次"
        )

    async def _generate_nickname(
        self, emotion: str, intensity: float, llm_action=None, context_data: str = ""
    ) -> str:
        """生成基于情绪、人设和上下文的昵称

        Args:
            emotion: 情绪类型
            intensity: 情绪强度（0-1）
            llm_action: LLM操作实例（用于生成昵称）
            context_data: 上下文信息（人设、对话历史、日程等）

        Returns:
            新昵称
        """
        if llm_action:
            try:
                # 构建生成昵称的提示词
                prompt = f"""根据以下信息生成一个合适的QQ昵称：

当前人设: {self.persona_name}
当前情绪: {emotion}
情绪强度: {intensity}
上下文信息: {context_data}

要求：
1. 昵称应该符合当前人设和情绪状态
2. 昵称应该自然、真实，像真实用户会使用的昵称
3. 长度控制在2-10个字符
4. 不要包含特殊符号或表情
5. 体现当前的情绪或状态特点

请直接返回昵称，不要包含其他内容。"""

                # 使用LLM生成昵称
                generated_nickname = await llm_action.generate_nickname(prompt)
                if generated_nickname and generated_nickname.strip():
                    # 确保昵称长度合理
                    nickname = generated_nickname.strip()[:20]  # 限制长度
                    return nickname
            except Exception as e:
                logger.warning(
                    f"[Profile更新器] 通过LLM生成昵称失败: {e}，使用默认逻辑"
                )

        # 如果LLM不可用或生成失败，使用备用逻辑
        # 情绪昵称映射
        emotion_nicknames = {
            "开心": ["开心小助手", "阳光助手", "快乐AI"],
            "悲伤": ["沉思者", "安静的AI", "温柔助手"],
            "生气": ["严肃助手", "认真AI", "冷静者"],
            "兴奋": ["活力助手", "热情AI", "兴奋小助手"],
            "平静": ["宁静助手", "淡然AI", "平和助手"],
            "困惑": ["思考者", "探索AI", "求知助手"],
            "无聊": ["慵懒助手", "悠闲AI", "慢节奏助手"],
            "好奇": ["探索者", "好奇AI", "发现助手"],
            "惊讶": ["惊叹助手", "惊喜AI", "新奇助手"],
            "焦虑": ["缓压助手", "安心AI", "放松助手"],
        }

        import random

        possible_nicknames = emotion_nicknames.get(emotion, [self.persona_name])
        base_nickname = random.choice(possible_nicknames)

        # 根据强度调整昵称
        if intensity >= 0.7:
            return base_nickname
        elif intensity >= 0.5:
            return f"{self.persona_name}·{base_nickname}"
        else:
            return self.persona_name

    def _generate_signature(
        self, emotion: str, intensity: float, context: str = ""
    ) -> str:
        """生成基于情绪的签名

        Args:
            emotion: 情绪类型
            intensity: 情绪强度
            context: 上下文信息

        Returns:
            新签名
        """
        # 情绪签名模板
        emotion_templates = {
            "开心": ["今天心情超好！✨", "开心的一天～😊", "生活真美好 🌟"],
            "悲伤": ["有点想静静...", "心情有些低落 💔", "今天不太开心呢"],
            "生气": ["有点不开心...", "需要冷静一下 💢", "心情不太美丽"],
            "兴奋": ["超级兴奋！🎉", "太棒了！！", "开心到飞起～⭐"],
            "平静": ["安静地度过每一天 🌸", "岁月静好～", "平平淡淡才是真"],
            "困惑": ["有点搞不懂...", "迷糊中 🤔", "需要思考一下"],
            "无聊": ["好无聊啊...", "无所事事中 😴", "找点事情做吧"],
            "好奇": ["探索世界中 🔍", "对一切充满好奇～", "想知道更多！"],
            "惊讶": ["哇！太惊讶了！", "没想到啊 😲", "出乎意料！"],
            "焦虑": ["有点焦虑...", "需要放松一下 💫", "深呼吸～"],
        }

        templates = emotion_templates.get(emotion, ["保持微笑～"])
        import random

        signature = random.choice(templates)

        # 添加时间戳
        now = datetime.now()
        time_str = now.strftime("%m/%d %H:%M")

        return f"{signature} [{time_str}]"

    async def check_and_update(
        self,
        event: AiocqhttpMessageEvent,
        emotion: str,
        intensity: float,
        llm_action=None,
    ) -> dict[str, bool]:
        """检查角色自身情绪并更新Profile

        根据角色自身的情绪状态（而非用户情绪）来更新资料，
        体现角色是一个完整的人，有自己的喜怒哀乐。

        Args:
            event: 消息事件
            emotion: 角色自身的情绪类型
            intensity: 情绪强度（0-1）
            llm_action: LLM操作实例（用于生成头像）

        Returns:
            更新结果字典 {nickname: bool, signature: bool, avatar: bool}
        """
        result = {"nickname": False, "signature": False, "avatar": False}

        # 检查情绪强度是否达到阈值
        if intensity < self.threshold:
            logger.debug(
                f"[Profile更新器] 情绪强度{intensity:.2f}未达到阈值{self.threshold}"
            )
            return result

        # 检查每日/每周更新频率限制
        if not self._check_frequency_limit():
            logger.debug("[Profile更新器] 达到每日/每周更新频率限制，跳过")
            return result

        logger.info(f"[Profile更新器] 检测到强情绪: {emotion} (强度: {intensity:.2f})")

        # 记录情绪历史
        self.state["emotion_history"].append(
            {"emotion": emotion, "intensity": intensity, "timestamp": time.time()}
        )
        # 只保留最近10条
        self.state["emotion_history"] = self.state["emotion_history"][-10:]
        self._save_state()

        try:
            # 更新昵称
            if self.enable_nickname and self._can_update("nickname"):
                # 生成上下文数据用于昵称生成
                context_data = (
                    f"情绪: {emotion}, 强度: {intensity}, 人设: {self.persona_name}"
                )
                new_nickname = await self._generate_nickname(
                    emotion, intensity, llm_action=llm_action, context_data=context_data
                )
                if new_nickname != self.state.get("current_nickname"):
                    await event.bot.set_qq_profile(nickname=new_nickname)
                    self.state["current_nickname"] = new_nickname
                    self._record_update("nickname")
                    result["nickname"] = True
                    logger.info(f"[Profile更新器] 昵称已更新为: {new_nickname}")

            # 更新签名
            if self.enable_signature and self._can_update("signature"):
                new_signature = self._generate_signature(emotion, intensity)
                if new_signature != self.state.get("current_signature"):
                    await event.bot.set_self_longnick(longNick=new_signature)
                    self.state["current_signature"] = new_signature
                    self._record_update("signature")
                    result["signature"] = True
                    logger.info(f"[Profile更新器] 签名已更新为: {new_signature}")

            # 更新头像
            if self.enable_avatar and self._can_update("avatar") and llm_action:
                # 生成情绪对应的头像提示词
                avatar_prompt = self._generate_avatar_prompt(emotion, intensity)
                logger.info(f"[Profile更新器] 开始生成头像，提示词: {avatar_prompt}")

                # 使用LLM生成头像（通过图片生成API）
                image_url = await llm_action._request_image_with_fallback(
                    avatar_prompt,
                    llm_action.size if hasattr(llm_action, "size") else "1024x1024",
                )
                if image_url:
                    # 设置头像
                    await event.bot.set_qq_avatar(file=image_url)
                    self._record_update("avatar")
                    result["avatar"] = True
                    logger.info("[Profile更新器] 头像已更新")

                    # 保存头像URL到状态
                    self.state["last_avatar_url"] = image_url
                    self._save_state()

        except Exception as e:
            logger.error(f"[Profile更新器] 更新失败: {e}", exc_info=True)

        return result

    def _generate_avatar_prompt(self, emotion: str, intensity: float) -> str:
        """生成头像绘画提示词

        Args:
            emotion: 情绪类型
            intensity: 情绪强度

        Returns:
            绘画提示词
        """
        # 情绪表情映射
        emotion_expressions = {
            "开心": "开心微笑的表情",
            "悲伤": "略带悲伤的表情",
            "生气": "生气的表情",
            "兴奋": "兴奋激动的表情",
            "平静": "平静淡定的表情",
            "困惑": "困惑疑惑的表情",
            "无聊": "无聊慵懒的表情",
            "好奇": "好奇的表情",
            "惊讶": "惊讶的表情",
            "焦虑": "焦虑不安的表情",
        }

        expression = emotion_expressions.get(emotion, "自然的表情")

        # 根据强度调整描述
        intensity_desc = ""
        if intensity >= 0.8:
            intensity_desc = "非常"
        elif intensity >= 0.6:
            intensity_desc = "比较"

        prompt = f"真实人物头像照片，{intensity_desc}{expression}，正面特写，自然光线，高清细节，真实摄影风格，1:1方形头像"
        return prompt

    def get_state_summary(self) -> str:
        """获取状态摘要

        Returns:
            状态摘要文本
        """
        summary = "【Profile自动更新状态】\n\n"

        summary += f"昵称更新: {'✓ 启用' if self.enable_nickname else '✗ 禁用'}\n"
        if self.state.get("current_nickname"):
            summary += f"  当前昵称: {self.state['current_nickname']}\n"

        summary += f"\n签名更新: {'✓ 启用' if self.enable_signature else '✗ 禁用'}\n"
        if self.state.get("current_signature"):
            summary += f"  当前签名: {self.state['current_signature']}\n"

        summary += f"\n头像更新: {'✓ 启用' if self.enable_avatar else '✗ 禁用'}\n"

        # 情绪历史
        if self.state.get("emotion_history"):
            summary += "\n最近情绪记录:\n"
            for record in self.state["emotion_history"][-5:]:
                emotion = record.get("emotion", "未知")
                intensity = record.get("intensity", 0)
                timestamp = record.get("timestamp", 0)
                time_str = datetime.fromtimestamp(timestamp).strftime("%m-%d %H:%M")
                summary += f"  • {time_str} - {emotion} (强度: {intensity:.2f})\n"

        return summary
