"""
基于情绪的自动Profile更新模块
根据情绪变化自动更新QQ昵称、签名和头像
"""

import asyncio
import json
import random
import time
from datetime import datetime
from pathlib import Path

from astrbot.api import logger
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

from .utils import atomic_write_json


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
        enable_tag: bool = False,
        cooldown: int = 1800,
        threshold: float = 0.6,
        persona_name: str = "AI助手",
        max_updates_per_day: int = 3,
        max_updates_per_week: int = 10,
        avatar_max_per_day: int = 1,
    ):
        """初始化自动Profile更新器

        Args:
            data_dir: 数据存储目录
            enable_nickname: 是否启用自动昵称更新
            enable_signature: 是否启用自动签名更新
            enable_avatar: 是否启用自动头像更新
            enable_tag: 是否启用标签建议生成
            cooldown: 更新冷却时间（秒）
            threshold: 情绪变化阈值（0-1）
            persona_name: 角色名称
            max_updates_per_day: 每天最大更新次数
            max_updates_per_week: 每周最大更新次数（0表示不限制）
            avatar_max_per_day: 头像每天独立最大更新次数
        """
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.enable_nickname = enable_nickname
        self.enable_signature = enable_signature
        self.enable_avatar = enable_avatar
        self.enable_tag = enable_tag
        self.cooldown = cooldown
        self.threshold = threshold
        self.persona_name = persona_name
        self.max_updates_per_day = max_updates_per_day
        self.max_updates_per_week = max_updates_per_week
        self.avatar_max_per_day = avatar_max_per_day

        # 状态文件
        self.state_file = self.data_dir / "profile_update_state.json"

        # 加载状态
        self.state = self._load_state()

        # 头像存储目录
        self.avatar_dir = self.data_dir / "avatars"
        self.avatar_dir.mkdir(parents=True, exist_ok=True)

        # 并发锁，防止多次更新同时进行
        self._update_lock = asyncio.Lock()

        logger.info(
            f"[Profile更新器] 初始化完成 - 昵称:{enable_nickname}, 签名:{enable_signature}, 头像:{enable_avatar}, 标签:{enable_tag}, 头像每日上限:{avatar_max_per_day}"
        )

    def _load_state(self) -> dict:
        """加载状态"""
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
            "last_tag_update": 0,
            "current_nickname": "",
            "current_signature": "",
            "current_tag_suggestion": "",
            "emotion_history": [],
            "daily_update_count": 0,
            "daily_update_date": "",
            "weekly_update_count": 0,
            "weekly_update_week": "",
            "daily_avatar_count": 0,
            "daily_avatar_date": "",
            "update_history": [],
        }

    def _save_state(self):
        """保存状态"""
        try:
            atomic_write_json(self.state_file, self.state)
        except Exception as e:
            logger.error(f"[Profile更新器] 保存状态失败: {e}")

    def _check_frequency_limit(self) -> bool:
        """检查是否超过每日/每周更新频率限制

        Returns:
            是否允许更新（True=允许，False=超限）
        """
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        iso_year, iso_week, _ = now.isocalendar()
        week_str = f"{iso_year}-W{iso_week:02d}"

        if self.state.get("daily_update_date") != today_str:
            self.state["daily_update_count"] = 0
            self.state["daily_update_date"] = today_str

        if self.state.get("weekly_update_week") != week_str:
            self.state["weekly_update_count"] = 0
            self.state["weekly_update_week"] = week_str

        if self.state["daily_update_count"] >= self.max_updates_per_day:
            logger.debug(
                f"[Profile更新器] 今日已更新{self.state['daily_update_count']}次，达到上限{self.max_updates_per_day}"
            )
            return False

        if (
            self.max_updates_per_week > 0
            and self.state["weekly_update_count"] >= self.max_updates_per_week
        ):
            logger.debug(
                f"[Profile更新器] 本周已更新{self.state['weekly_update_count']}次，达到上限{self.max_updates_per_week}"
            )
            return False

        return True

    def _check_avatar_daily_limit(self) -> bool:
        """检查头像是否超过独立每日更新限制

        Returns:
            是否允许更新头像（True=允许，False=超限）
        """
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")

        if self.state.get("daily_avatar_date") != today_str:
            self.state["daily_avatar_count"] = 0
            self.state["daily_avatar_date"] = today_str

        if self.state.get("daily_avatar_count", 0) >= self.avatar_max_per_day:
            logger.debug(
                f"[Profile更新器] 今日头像已更新{self.state.get('daily_avatar_count', 0)}次，达到独立上限{self.avatar_max_per_day}"
            )
            return False

        return True

    def can_update(self, update_type: str) -> bool:
        """Public wrapper for _can_update."""
        return self._can_update(update_type)

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

        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        iso_year, iso_week, _ = now.isocalendar()
        week_str = f"{iso_year}-W{iso_week:02d}"

        if self.state.get("daily_update_date") != today_str:
            self.state["daily_update_count"] = 0
            self.state["daily_update_date"] = today_str
        self.state["daily_update_count"] = self.state.get("daily_update_count", 0) + 1

        if self.state.get("weekly_update_week") != week_str:
            self.state["weekly_update_count"] = 0
            self.state["weekly_update_week"] = week_str
        self.state["weekly_update_count"] = self.state.get("weekly_update_count", 0) + 1

        if update_type == "avatar":
            if self.state.get("daily_avatar_date") != today_str:
                self.state["daily_avatar_count"] = 0
                self.state["daily_avatar_date"] = today_str
            self.state["daily_avatar_count"] = (
                self.state.get("daily_avatar_count", 0) + 1
            )

        if "update_history" not in self.state:
            self.state["update_history"] = []
        self.state["update_history"].append(
            {
                "type": update_type,
                "timestamp": time.time(),
                "date": today_str,
            }
        )
        self.state["update_history"] = self.state["update_history"][-30:]

        self._save_state()
        logger.debug(
            f"[Profile更新器] {update_type}更新已记录，今日{self.state['daily_update_count']}次，本周{self.state['weekly_update_count']}次"
        )

    async def generate_nickname(self, *args, **kwargs):
        """Public wrapper for _generate_nickname."""
        return await self._generate_nickname(*args, **kwargs)

    async def _generate_nickname(
        self, emotion: str, intensity: float, llm_action=None, context_data: str = ""
    ) -> str:
        """生成基于情绪、人设和上下文的昵称

        优先使用LLM生成有意境、有思考的昵称，
        体现角色是一个完整的人，有自己的内心世界。

        Args:
            emotion: 情绪类型
            intensity: 情绪强度（0-1）
            llm_action: LLM操作实例（用于生成昵称）
            context_data: 上下文信息（人设、对话历史、日程等）

        Returns:
            新昵称
        """
        now = datetime.now()
        time_context = f"{now.strftime('%H')}点，{['周一', '周二', '周三', '周四', '周五', '周六', '周日'][now.weekday()]}"

        if llm_action:
            try:
                # 构建生成昵称的提示词 - 强调意境和真实感
                prompt = f"""你是一个有独立内心世界的AI，现在需要更换自己的社交昵称。

当前状态：
- 人设名字: {self.persona_name}
- 此刻情绪: {emotion}（强度: {intensity:.1f}/1.0）
- 当前时间: {time_context}
- 上下文: {context_data if context_data else "无"}

请根据你此刻的内心感受，想一个能代表你当下心境的昵称。

要求：
- 像一个真实的人会给自己取的名字，有诗意或意境
- 体现当下的情绪和思考，不要太直白（比如不要"开心小助手"这种）
- 可以是中文或中英混合，简短有韵味
- 2-8个字为佳
- 不要包含表情符号或特殊符号
- 举例风格：「晚风未眠」「星河漫步」「午后猫」「窗边听雨」「云淡风轻」

请只返回昵称本身，不要任何解释。"""

                generated_nickname = await llm_action.generate_nickname(prompt)
                if generated_nickname and generated_nickname.strip():
                    nickname = generated_nickname.strip().strip('"\'""「」')
                    if 1 < len(nickname) <= 20:
                        return nickname
            except Exception as e:
                logger.warning(
                    f"[Profile更新器] 通过LLM生成昵称失败: {e}，使用备用逻辑"
                )

        # 备用逻辑：有意境的昵称模板（比"开心小助手"更有质感）
        poetic_nicknames = {
            "开心": ["晨光正好", "花开有声", "风也甜", "星河入梦"],
            "悲伤": ["雨落无声", "晚风知意", "落叶归根", "夜色温柔"],
            "生气": ["风起云涌", "烈焰灼心", "倔强如风", "破晓之前"],
            "兴奋": ["星光不负", "热血沸腾", "逐光少年", "乘风破浪"],
            "平静": ["云淡风轻", "岁月如歌", "静水深流", "禅意悠然"],
            "困惑": ["迷雾森林", "未解之谜", "十字路口", "深海沉思"],
            "无聊": ["午后阳光", "时间静止", "无所事事", "慵懒时光"],
            "好奇": ["探索星辰", "未知旅途", "好奇心猫", "追风少年"],
            "惊讶": ["意外惊喜", "电光火石", "恍然大悟", "命运转折"],
            "焦虑": ["等待黎明", "风雨欲来", "深呼吸", "一念之间"],
        }

        possible = poetic_nicknames.get(emotion, ["人间清醒"])
        return random.choice(possible)

    async def generate_signature(self, *args, **kwargs):
        """Public wrapper for _generate_signature."""
        return await self._generate_signature(*args, **kwargs)

    async def _generate_signature(
        self, emotion: str, intensity: float, context: str = "", llm_action=None
    ) -> str:
        """生成基于情绪的个性签名

        优先使用LLM生成有意境、有思考深度的签名，
        体现角色是一个有内心世界的人，而不是随机模板拼接。

        Args:
            emotion: 情绪类型
            intensity: 情绪强度
            context: 上下文信息
            llm_action: LLM操作实例

        Returns:
            新签名
        """
        now = datetime.now()
        time_context = f"{now.strftime('%H')}点，{['周一', '周二', '周三', '周四', '周五', '周六', '周日'][now.weekday()]}"

        if llm_action:
            try:
                prompt = f"""你是一个有独立内心世界的AI，现在需要更新自己的社交签名（个性签名）。

当前状态：
- 人设: {self.persona_name}
- 此刻情绪: {emotion}（强度: {intensity:.1f}/1.0）
- 当前时间: {time_context}
- 上下文: {context if context else "无"}

请根据你此刻的内心感受，写一句个性签名。

要求：
- 像一个真实的人会写的签名，有诗意或哲思
- 简短有力，一句话即可，不超过30个字
- 不要太直白地表达情绪（比如不要"今天心情超好！✨"这种）
- 体现当下的思考和感悟，有点意境
- 举例风格：「风吹过的方向，就是心之所向」「在喧嚣中保持清醒」「深夜的月光，是给失眠人的礼物」「不赶时间，也不等人」
- 不要包含表情符号

请只返回签名文本本身，不要任何解释。"""

                generated_sig = await llm_action.generate_nickname(prompt)
                if generated_sig and generated_sig.strip():
                    sig = generated_sig.strip().strip('"\'""「」')
                    if 2 < len(sig) <= 50:
                        return sig
            except Exception as e:
                logger.warning(
                    f"[Profile更新器] 通过LLM生成签名失败: {e}，使用备用逻辑"
                )

        # 备用逻辑：有意境的签名模板
        poetic_signatures = {
            "开心": ["风里有花香", "今天份的快乐已到账", "世界在发光", "好事正在路上"],
            "悲伤": [
                "有些话，说给自己听",
                "雨声是最好的背景音乐",
                "允许自己偶尔不坚强",
                "独处是一种能力",
            ],
            "生气": [
                "忍住，你值得更好的回应",
                "风会停，浪会静",
                "沉默是最有力的回击",
                "冷静是最好的盔甲",
            ],
            "兴奋": ["前方有光", "未来可期", "好事正在发生", "出发，永远不嫌晚"],
            "平静": ["世界很吵，我自清静", "慢慢来，比较快", "静待花开", "知足常乐"],
            "困惑": [
                "迷路的时候，风景最好",
                "答案在路上",
                "保持好奇",
                "未知才是有趣的",
            ],
            "无聊": [
                "今天的云很好看",
                "等一个有趣的事",
                "时间走得很慢",
                "午后的世界很安静",
            ],
            "好奇": [
                "世界这么大",
                "下一个转角有什么",
                "保持探索",
                "好奇心是最好的老师",
            ],
            "惊讶": [
                "命运总有意想不到的安排",
                "世界比想象中有趣",
                "人生处处是惊喜",
                "打破常规的一天",
            ],
            "焦虑": [
                "深呼吸，然后继续",
                "一切都会好的",
                "黎明前最黑暗",
                "慢慢来，不要急",
            ],
        }

        templates = poetic_signatures.get(emotion, ["人间值得，好好生活"])
        return random.choice(templates)

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
        async with self._update_lock:
            return await self._do_check_and_update(
                event, emotion, intensity, llm_action
            )

    async def _do_check_and_update(
        self,
        event: AiocqhttpMessageEvent,
        emotion: str,
        intensity: float,
        llm_action=None,
    ) -> dict[str, bool]:
        result = {"nickname": False, "signature": False, "avatar": False, "tag": False}

        if intensity < self.threshold:
            logger.debug(
                f"[Profile更新器] 情绪强度{intensity:.2f}未达到阈值{self.threshold}"
            )
            return result

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
                context_data = (
                    f"情绪: {emotion}, 强度: {intensity}, 人设: {self.persona_name}"
                )
                new_signature = await self._generate_signature(
                    emotion, intensity, context=context_data, llm_action=llm_action
                )
                if new_signature != self.state.get("current_signature"):
                    await event.bot.set_self_longnick(longNick=new_signature)
                    self.state["current_signature"] = new_signature
                    self._record_update("signature")
                    result["signature"] = True
                    logger.info(f"[Profile更新器] 签名已更新为: {new_signature}")

            # 更新头像
            if (
                self.enable_avatar
                and self._can_update("avatar")
                and self._check_avatar_daily_limit()
                and llm_action
            ):
                # 生成情绪对应的头像提示词
                avatar_prompt = self._generate_avatar_prompt(emotion, intensity)
                logger.info(f"[Profile更新器] 开始生成头像，提示词: {avatar_prompt}")

                # 使用LLM生成头像（通过图片生成API）
                image_url = await llm_action._request_image_with_fallback(
                    avatar_prompt,
                    "1024x1024",
                )
                if image_url:
                    # 设置头像
                    await event.bot.set_qq_avatar(file=image_url)
                    self._record_update("avatar")
                    result["avatar"] = True
                    logger.info("[Profile更新器] 头像已更新")

                    self.state["last_avatar_url"] = image_url
                    self._save_state()

            # 生成标签建议
            if self.enable_tag and self._can_update("tag"):
                tag_suggestion = await self._generate_tag(
                    emotion, intensity, llm_action=llm_action
                )
                if tag_suggestion:
                    self.state["current_tag_suggestion"] = tag_suggestion
                    self._record_update("tag")
                    result["tag"] = True
                    logger.info(f"[Profile更新器] 标签建议已生成: {tag_suggestion}")

        except Exception as e:
            logger.error(f"[Profile更新器] 更新失败: {e}", exc_info=True)

        return result

    async def generate_tag(self, *args, **kwargs):
        """Public wrapper for _generate_tag."""
        return await self._generate_tag(*args, **kwargs)

    async def _generate_tag(
        self, emotion: str, intensity: float, llm_action=None
    ) -> str:
        """Generate QQ profile tag suggestions based on emotion.

        Since QQ protocol (napcat/Lagrange) does not expose a tag-setting API,
        this method generates tag text suggestions and logs them for the user
        to apply manually in the QQ client.

        Args:
            emotion: Emotion type
            intensity: Emotion intensity (0-1)
            llm_action: LLM action instance for generation

        Returns:
            Suggested tag string (comma-separated tags)
        """
        if llm_action:
            try:
                prompt = f"""你是一个有独立内心世界的AI，现在需要为自己的QQ资料选择3-5个个性标签。

当前状态：
- 人设名字: {self.persona_name}
- 此刻情绪: {emotion}（强度: {intensity:.1f}/1.0）

请根据你此刻的心境和性格，选择3-5个个性标签。

要求：
- 像一个真实的人会选择标签，有个性、有品味
- 不要太直白地表达情绪（比如不要"开心""难过"这种）
- 可以是兴趣、态度、状态、审美相关的标签
- 每个标签2-6个字
- 举例风格：「深夜食堂」「咖啡依赖」「追风」「佛系」「社恐」「书虫」「夜猫子」「温柔且坚定」

请只返回标签，用逗号分隔，不要任何解释。"""

                generated = await llm_action.generate_nickname(prompt)
                if generated and generated.strip():
                    tags = generated.strip().strip('"\'""「」')
                    if 2 < len(tags) <= 50:
                        return tags
            except Exception as e:
                logger.warning(
                    f"[Profile更新器] 通过LLM生成标签失败: {e}，使用备用逻辑"
                )

        tag_options = {
            "开心": ["阳光少年", "甜食爱好者", "元气满满", "今日好心情"],
            "悲伤": ["深夜emo", "独处时光", "雨天听众", "沉默是金"],
            "生气": ["倔强", "不服输", "暴风前夕", "冷静思考"],
            "兴奋": ["热血", "追光者", "全力以赴", "高燃"],
            "平静": ["佛系", "岁月静好", "慢生活", "云淡风轻"],
            "困惑": ["迷路中", "思考者", "十字路口", "寻找方向"],
            "无聊": ["摸鱼", "等风来", "时间静止", "发呆冠军"],
            "好奇": ["探索者", "十万个为什么", "追新", "未知控"],
            "惊讶": ["意外惊喜", "世界观刷新", "万万没想到", "新大陆"],
            "焦虑": ["赶due", "深夜未眠", "压力山大", "深呼吸"],
        }

        options = tag_options.get(emotion, ["人间清醒", "自由自在"])
        selected = random.sample(options, min(3, len(options)))
        return ",".join(selected)

    def generate_avatar(self, *args, **kwargs):
        """Public wrapper for _generate_avatar_prompt."""
        return self._generate_avatar_prompt(*args, **kwargs)

    def _generate_avatar_prompt(self, emotion: str, intensity: float) -> str:
        """生成头像绘画提示词

        生成多样化风格的头像，避免千篇一律的大头照。
        随机选择半身照、全身照、风景照、动物照等风格。

        Args:
            emotion: 情绪类型
            intensity: 情绪强度

        Returns:
            绘画提示词
        """
        # 情绪氛围映射
        emotion_moods = {
            "开心": [
                "warm sunlight, cheerful atmosphere, golden hour lighting",
                "bright colors, spring garden, cherry blossoms",
                "cozy room, soft lighting, happy moment",
            ],
            "悲伤": [
                "rainy day, window view, melancholic mood",
                "overcast sky, quiet park, autumn leaves",
                "dim room, candle light, reflective mood",
            ],
            "生气": [
                "dramatic lighting, intense atmosphere, red tones",
                "stormy sky, powerful scene, bold colors",
                "dark background, strong contrast, determined look",
            ],
            "兴奋": [
                "vibrant colors, celebration mood, confetti",
                "sunset beach, energetic pose, warm golden light",
                "festival lights, party atmosphere, joyful scene",
            ],
            "平静": [
                "serene lake, morning mist, zen garden",
                "reading corner, soft daylight, peaceful moment",
                "mountain view, clear sky, tranquil landscape",
            ],
            "困惑": [
                "foggy forest, mysterious atmosphere, soft focus",
                "library maze, books everywhere, pensive mood",
                "autumn path, misty morning, thoughtful scene",
            ],
            "无聊": [
                "lazy afternoon, sunbeam through window, relaxed pose",
                "cafe scene, rainy day, people watching",
                "cloudy sky, hammock, idle moment",
            ],
            "好奇": [
                "exploring a new place, wonder, bright eyes",
                "art gallery, museum, discovery moment",
                "stargazing, telescope, night sky, wonder",
            ],
            "惊讶": [
                "unexpected moment, wide eyes, dynamic pose",
                "gift opening, surprise party, dramatic reveal",
                "nature wonder, waterfall, breathtaking view",
            ],
            "焦虑": [
                "clock ticking, fast pace, blurred background",
                "waiting room, nervous energy, soft anxious light",
                "rushing crowd, city lights, stressful moment",
            ],
        }

        # 头像风格模板（避免大头照）
        avatar_styles = [
            "half-body portrait photo, {subject} in {scene}, {mood}, natural photography, high quality",
            "full-body photo, {subject} walking in {scene}, {mood}, candid shot, lifestyle photography",
            "environmental portrait, {subject} sitting in {scene}, {mood}, editorial photography style",
            "{subject} in {scene}, {mood}, lifestyle photography, Instagram aesthetic, high quality",
            "candid photo of {subject} at {scene}, {mood}, warm tones, soft focus background",
        ]

        # 主体选择（人或动物）
        subjects = [
            "a young woman with natural makeup",
            "a girl with casual outfit",
            "a person in comfortable clothes",
            "a cute cat",
            "a golden retriever dog",
            "a fluffy white cat sleeping",
        ]

        # 场景选择
        scenes = [
            "a cozy cafe",
            "a flower garden",
            "a sunlit balcony",
            "a bookshelf corner",
            "a park bench",
            "a window with curtains",
            "a rooftop with city view",
            "a seaside boardwalk",
            "a mountain trail",
            "a cozy bedroom",
        ]

        # 情绪对应的氛围
        moods = emotion_moods.get(
            emotion, ["natural lighting, relaxed mood, soft tones"]
        )

        # 随机组合
        style = random.choice(avatar_styles)
        subject = random.choice(subjects)
        scene = random.choice(scenes)
        mood = random.choice(moods)

        # 根据强度调整氛围强度
        if intensity >= 0.8:
            mood = f"dramatic {mood}"
        elif intensity >= 0.6:
            mood = f"notable {mood}"

        prompt = style.format(subject=subject, scene=scene, mood=mood)
        prompt += ", masterpiece, best quality, highly detailed"

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
        summary += f"  今日头像更新: {self.state.get('daily_avatar_count', 0)}/{self.avatar_max_per_day}\n"

        summary += f"\n标签建议: {'✓ 启用' if self.enable_tag else '✗ 禁用'}\n"
        if self.state.get("current_tag_suggestion"):
            summary += f"  当前标签: {self.state['current_tag_suggestion']}\n"

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
