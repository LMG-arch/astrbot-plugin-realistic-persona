"""
异步思考引擎
模拟角色的持续思考过程，产生日常状态和内心独白
"""

import json
import random
from datetime import datetime
from pathlib import Path
from typing import Any

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
                file_path.write_text("", encoding="utf-8")

        if not self.status_file.exists():
            self.status_file.write_text(
                json.dumps(
                    {
                        "current_mood": "平静",
                        "energy_level": 50,
                        "last_thought_time": None,
                        "thought_count_today": 0,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

    def _extract_relevant_schedule(self, schedule: str, current_hour: int) -> str:
        """从完整日程中提取与当前时间段相关的部分"""
        if not schedule:
            return ""

        # Time period keywords to match against schedule lines
        time_keywords = {
            range(6, 9): ["早上", "起床", "晨", "早餐"],
            range(9, 12): ["上午", "上课", "上班", "学习", "工作"],
            range(12, 14): ["中午", "午饭", "午餐", "午休"],
            range(14, 18): ["下午", "继续"],
            range(18, 21): ["傍晚", "晚", "晚饭", "晚餐", "散步", "娱乐"],
            range(21, 24): ["睡前", "睡觉", "洗漱", "休息"],
            range(0, 6): ["失眠", "深夜", "凌晨"],
        }

        # Find the matching keywords for current hour
        keywords = []
        for time_range, kws in time_keywords.items():
            if current_hour in time_range:
                keywords = kws
                break

        if not keywords:
            return ""

        # Extract relevant lines from the schedule
        lines = schedule.split("\n")
        relevant = []
        for line in lines:
            line_stripped = line.strip()
            if not line_stripped:
                continue
            for kw in keywords:
                if kw in line_stripped:
                    relevant.append(line_stripped)
                    break
            # Also match time ranges like "9:", "14:", etc.
            for i in range(current_hour, current_hour + 3):
                if f"{i}:" in line_stripped or f"{i:02d}:" in line_stripped:
                    if line_stripped not in relevant:
                        relevant.append(line_stripped)
                    break

        return "；".join(relevant[:3]) if relevant else ""

    def _build_context_fallback(
        self,
        hour: int,
        weather: str | None,
        schedule: str | None,
        news: str | None,
        recent_conversations: str | None,
        recent_experiences: str | None,
    ) -> str | None:
        """当LLM不可用时，用上下文数据拼接一个有意义的思考（比静态模板更好）

        Returns:
            拼接的思考内容，或 None（上下文不足时）
        """
        parts = []

        # 优先用最近聊天/经历，这些最有信息量
        if recent_experiences:
            # 取最近一条经历
            first = recent_experiences.split("；")[0][:30]
            if first:
                parts.append(f"刚才{first}，")

        if recent_conversations:
            # 取最近对话的关键词
            first = recent_conversations.split("；")[0][:30]
            if first:
                parts.append(f"想起之前聊天说到的{first[:20]}，")

        # 用日程添加具体感
        if schedule:
            schedule_excerpt = self._extract_relevant_schedule(schedule, hour)
            if schedule_excerpt:
                # 取日程中的第一个关键词
                parts.append(f"今天{schedule_excerpt[:20]}，")

        # 天气补充
        if weather and len(parts) > 0:
            if "雨" in weather:
                parts.append("窗外的雨声让人心静")
            elif "晴" in weather:
                parts.append("外面阳光不错")
            elif "雪" in weather:
                parts.append("下雪了呢")

        # 拼接
        if parts:
            result = "".join(parts)
            # 确保长度合理（15-60字）
            if len(result) > 60:
                result = result[:57] + "..."
            return result

        return None

    async def generate_thought(
        self,
        llm_action,
        weather: str | None = None,
        current_time: datetime | None = None,
        persona_profile: str = "",
        schedule: str | None = None,
        news: str | None = None,
        recent_conversations: str | None = None,
        recent_experiences: str | None = None,
    ) -> str | None:
        """
        使用大模型生成一条思考/内心独白

        Args:
            llm_action: LLM动作实例，用于调用大模型
            weather: 当前天气
            current_time: 当前时间
            persona_profile: 人格描述，用于指导大模型生成符合人设的思考
            schedule: 今日日程
            news: 今日新闻
            recent_conversations: 最近对话摘要
            recent_experiences: 最近经历摘要

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

            # 构建丰富的上下文信息
            context_parts = []
            if weather:
                context_parts.append(f"天气：{weather}")
            if schedule:
                # 只取与当前时间段相关的日程
                schedule_excerpt = self._extract_relevant_schedule(schedule, hour)
                if schedule_excerpt:
                    context_parts.append(f"当前日程安排：{schedule_excerpt}")
            if news:
                context_parts.append(f"今日新闻：{news[:100]}")
            if recent_conversations:
                context_parts.append(f"最近聊天：{recent_conversations[:120]}")
            if recent_experiences:
                context_parts.append(f"最近经历：{recent_experiences[:100]}")

            context_info = "；".join(context_parts) if context_parts else "暂无额外信息"

            # Anti-repetition: include recent thoughts to avoid redundancy
            recent_thoughts_text = ""
            recent = self.get_today_thoughts()
            if recent:
                recent_contents = [
                    r.get("content", "") for r in recent[-5:] if r.get("content")
                ]
                if recent_contents:
                    recent_thoughts_text = f"\n今天已经想过的内容（避免重复）：{'；'.join(recent_contents)}"

            prompt = f"""你是{persona_profile if persona_profile else "一个有思考能力的人"}。
现在是{current_time.strftime("%Y年%m月%d日 %H:%M")}，{time_info}。

当前情境：{context_info}{recent_thoughts_text}

请基于以上真实情境，生成一段属于你自己的内心独白。要求：
1. 内容真实自然，像真人内心独白
2. 长度在15-50字之间
3. 必须结合当前的日程、天气、最近聊天内容或经历来思考
4. 符合你的人设特点，有个人情感色彩
5. 表达你对具体事情的感受或想法，不是泛泛的感叹
6. 与今天已有的思考内容不同，关注新的角度
7. 适合在对话中自然引用（如"我刚才还在想..."）

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
            # 优先尝试用上下文数据拼接一个有意义的思考
            context_thought = self._build_context_fallback(
                hour, weather, schedule, news, recent_conversations, recent_experiences
            )
            if context_thought:
                self._save_thought(context_thought, current_time)
                logger.info(f"[思考引擎] 使用上下文备用思考: {context_thought}")
                return context_thought

            # 上下文不足时使用静态模板
            logger.debug("[思考引擎] 上下文不足，使用静态模板")

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

    async def generate_activity(
        self,
        llm_action=None,
        current_time: datetime | None = None,
        persona_profile: str = "",
        weather: str | None = None,
        schedule: str | None = None,
    ) -> str | None:
        """
        生成日常活动记录，优先使用LLM结合上下文生成

        Args:
            llm_action: LLM动作实例，用于调用大模型生成活动
            current_time: 当前时间
            persona_profile: 人格描述
            weather: 当前天气
            schedule: 当前日程

        Returns:
            生成的活动内容
        """
        try:
            if current_time is None:
                current_time = datetime.now()

            # 优先使用LLM生成真实的活动
            if llm_action:
                try:
                    hour = current_time.hour
                    if 6 <= hour < 12:
                        time_info = "清晨/上午"
                    elif 12 <= hour < 14:
                        time_info = "中午"
                    elif 14 <= hour < 18:
                        time_info = "下午"
                    elif 18 <= hour < 22:
                        time_info = "傍晚/晚上"
                    else:
                        time_info = "深夜"

                    context_parts = []
                    context_parts.append(
                        f"现在是{current_time.strftime('%Y年%m月%d日 %H:%M')}，{time_info}"
                    )
                    if weather:
                        context_parts.append(f"天气：{weather}")
                    if schedule:
                        schedule_excerpt = self._extract_relevant_schedule(
                            schedule, hour
                        )
                        if schedule_excerpt:
                            context_parts.append(f"当前日程安排：{schedule_excerpt}")
                    persona_desc = (
                        persona_profile if persona_profile else "一个有生活的人"
                    )

                    # Anti-repetition: include recent activities
                    recent_activities = self.get_today_activities()
                    recent_act_text = ""
                    if recent_activities:
                        act_contents = [
                            r.get("content", "")
                            for r in recent_activities[-5:]
                            if r.get("content")
                        ]
                        if act_contents:
                            recent_act_text = f"\n今天已经做过的活动（避免重复）：{'；'.join(act_contents)}"

                    prompt = f"你是{persona_desc}。\n"
                    prompt += "；".join(context_parts)
                    prompt += recent_act_text
                    prompt += "\n\n请描述你此刻正在做的一件具体日常小事，如在做什么、吃什么、看什么、想什么等。要求：具体有画面感，与已记录的活动不同，不要泛泛而谈。"

                    activity = await llm_action.generate_activity(prompt)
                    if activity:
                        self._save_activity(activity, current_time)
                        logger.info(f"[思考引擎] LLM生成活动: {activity}")
                        return activity
                    else:
                        logger.warning("[思考引擎] LLM未能生成活动，使用备用方案")
                except Exception as e:
                    logger.warning(f"[思考引擎] LLM生成活动失败: {e}，使用备用方案")

            # 备用方案：从模板随机选择
            logger.debug("[思考引擎] 使用备用活动生成方案")
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
                "type": "thought",
            }

            with open(self.thoughts_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

            logger.debug("[思考引擎] 思考已保存到本地")

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
                "type": "activity",
            }

            with open(self.activities_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

            logger.debug("[思考引擎] 活动已保存到本地")

        except Exception as e:
            logger.error(f"[思考引擎] 保存活动失败: {e}")

    def get_today_thoughts(self) -> list[dict[str, Any]]:
        """获取今天的所有思考"""
        try:
            today_str = datetime.now().strftime("%Y-%m-%d")
            thoughts = []

            with open(self.thoughts_file, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        record = json.loads(line)
                        if record.get("date") == today_str:
                            thoughts.append(record)

            return thoughts

        except Exception as e:
            logger.error(f"[思考引擎] 获取今天的思考失败: {e}")
            return []

    def get_today_activities(self) -> list[dict[str, Any]]:
        """获取今天的所有活动"""
        try:
            today_str = datetime.now().strftime("%Y-%m-%d")
            activities = []

            with open(self.activities_file, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        record = json.loads(line)
                        if record.get("date") == today_str:
                            activities.append(record)

            return activities

        except Exception as e:
            logger.error(f"[思考引擎] 获取今天的活动失败: {e}")
            return []
