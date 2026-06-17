import re
import time
from datetime import datetime
from urllib.parse import quote

import aiohttp

from astrbot.api import logger

from .base import BaseManager


class LifeManager(BaseManager):
    """Manages life simulation: schedule, weather, news, time descriptions."""

    async def build_life_context(
        self, event, analysis: dict | None, emotion_manager=None, image_manager=None
    ) -> str:
        """Build life context info (schedule, weather, news, thoughts, activities)."""
        try:
            now = datetime.now()
            context_parts = []

            schedule = await self.maybe_generate_schedule(now)
            if schedule:
                context_parts.append(f"今日安排：{schedule[:200]}...")

            weather = await self.get_weather_desc()
            if weather:
                context_parts.append(f"天气情况：{weather}")

            news_window_end = (self.state.news_hour + 3) % 24
            if news_window_end > self.state.news_hour:
                in_news_window = self.state.news_hour <= now.hour < news_window_end
            else:
                in_news_window = (
                    now.hour >= self.state.news_hour or now.hour < news_window_end
                )
            if in_news_window:
                news = await self.maybe_fetch_news(now)
                if news:
                    context_parts.append(f"今日新闻：{news[:150]}...")

            if self.state.thought_engine:
                try:
                    recent_thoughts = self.state.thought_engine.get_today_thoughts()
                    if recent_thoughts:
                        thought_texts = [
                            t.get("content", "")
                            for t in recent_thoughts[-3:]
                            if t.get("content")
                        ]
                        if thought_texts:
                            context_parts.append(
                                f"最近内心想法：{'；'.join(thought_texts)}"
                            )
                    recent_activities = self.state.thought_engine.get_today_activities()
                    if recent_activities:
                        act_texts = [
                            a.get("content", "")
                            for a in recent_activities[-3:]
                            if a.get("content")
                        ]
                        if act_texts:
                            context_parts.append(
                                f"最近在做的事：{'；'.join(act_texts)}"
                            )
                except Exception as e:
                    logger.debug(f"获取最近思考/活动失败: {e}")

            # Inject dormant data from experience bank
            if self.state.experience_bank:
                try:
                    projects = self.state.experience_bank.get_recent_projects(
                        status="in_progress", limit=3
                    )
                    if projects:
                        proj_names = [
                            p.get("project_name", "")
                            for p in projects
                            if p.get("project_name")
                        ]
                        if proj_names:
                            context_parts.append(
                                f"正在进行的事：{', '.join(proj_names)}"
                            )

                    promises = self.state.experience_bank.get_pending_promises(limit=3)
                    if promises:
                        promise_texts = [
                            p.get("promise", "")[:30]
                            for p in promises
                            if p.get("promise")
                        ]
                        if promise_texts:
                            context_parts.append(
                                f"答应过的事：{'; '.join(promise_texts)}"
                            )

                    circadian = self.state.experience_bank.get_recent_circadian()
                    if circadian:
                        energy = circadian.get("energy_level", 5)
                        mood = circadian.get("mood", "中性")
                        context_parts.append(f"当前状态：精力{energy}/10，心情-{mood}")
                except Exception as e:
                    logger.debug(f"注入沉睡数据失败: {e}")

            return "\n".join(context_parts) if context_parts else ""
        except Exception as e:
            logger.error(f"构建生活上下文失败: {e}")
            return ""

    async def maybe_generate_schedule(self, now: datetime) -> str:
        """Generate daily schedule when needed (using local data manager)."""
        today_str = now.strftime("%Y-%m-%d")

        cached_schedule = self.state.local_data_manager.get_schedule_data(today_str)
        if cached_schedule:
            logger.info(f"从本地数据获取 {today_str} 的日程信息")
            self.state._schedule_cache = {"data": cached_schedule, "date": today_str}
            return cached_schedule

        if (
            self.state._schedule_cache["date"] == today_str
            and self.state._schedule_cache["data"]
        ):
            logger.debug(f"使用缓存的日程: {today_str}")
            return self.state._schedule_cache["data"]

        if now.hour < self.state.schedule_hour:
            logger.debug(
                f"当前时间 {now.hour} 小于日程生成时间 {self.state.schedule_hour}，跳过生成"
            )
            return ""

        persona_profile = await self.get_system_persona_profile()
        logger.debug(f"获取系统人设成功，长度: {len(persona_profile)} 字符")

        provider_id = self.state.get_provider_id()
        if not provider_id:
            logger.warning("未找到可用的LLM提供者，无法生成日程")
            return self.build_fallback_schedule(today_str)

        schedule_text = ""
        weather_desc = await self.get_weather_desc()
        weather_hint = ""
        if weather_desc:
            weather_hint = f"当地天气：{weather_desc}。请根据天气选择合适的穿着（例如：下雨带伞、寒冷穿厚衣、热天穿薄衣）。\n"
        else:
            weather_hint = "请根据当前季节和常规天气选择合适的穿着。\n"

        if self.state.schedule_prompt and self.state.schedule_prompt.strip():
            custom_prompt = self.state.schedule_prompt.strip()
            custom_prompt = custom_prompt.replace(
                "{persona_name}", self.state.persona_name
            )
            custom_prompt = custom_prompt.replace("{persona_profile}", persona_profile)
            custom_prompt = custom_prompt.replace("{today}", today_str)
            custom_prompt = custom_prompt.replace("{weather}", weather_desc or "未知")
            prompt = custom_prompt
            logger.info("使用自定义日程生成提示词")
        else:
            prompt = (
                f"你是{self.state.persona_name}，{persona_profile}。\n"
                f"今天是{today_str}。\n"
                f"{weather_hint}\n"
                "请直接输出今天的详细生活安排：\n\n"
                "1. 今日穿搭：根据人设、当地天气和今天的活动，描述具体穿着（上衣、下装、鞋子、外套/配饰等），必须符合天气情况、角色性格和身份\n"
                "2. 早上（6:00-9:00）：起床时间、洗漱、早餐、出门准备等具体活动\n"
                "3. 上午（9:00-12:00）：主要活动（工作/上课/其他），具体在做什么\n"
                "4. 中午（12:00-14:00）：午餐地点和内容、午休安排\n"
                "5. 下午（14:00-18:00）：下午的具体安排和活动\n"
                "6. 前晚（18:00-20:00）：晚餐、休闲活动\n"
                "7. 晚上（20:00-23:00）：娱乐、学习、社交等活动\n"
                "8. 睡前（23:00-24:00）：洗漱、放松、睡觉准备\n\n"
                "重要：直接输出日程内容，不要添加任何确认、回复或解释性的话。用口语化表达，贴近真实人类生活，不要提到AI。每个时段1-2句话即可。"
            )

        logger.info(f"开始生成 {today_str} 的日程")
        try:
            resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
            )
            schedule_text = (resp.completion_text or "").strip()
            logger.info(f"日程生成成功，长度: {len(schedule_text)} 字符")
        except Exception as e:
            logger.error(f"生成日程失败: {e}")
            try:
                simple_prompt = f"为{self.state.persona_name}规划{today_str}的简单日程，包含穿搭和主要活动。"
                resp = await self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=simple_prompt,
                )
                schedule_text = (resp.completion_text or "").strip()
                if schedule_text:
                    logger.info(
                        f"使用简化提示词生成日程成功，长度: {len(schedule_text)} 字符"
                    )
                else:
                    logger.warning("简化提示词也无法生成日程")
                    schedule_text = self.build_fallback_schedule(today_str)
            except Exception as e2:
                logger.error(f"简化提示词生成日程也失败: {e2}")
                schedule_text = self.build_fallback_schedule(today_str)

        if not schedule_text:
            schedule_text = self.build_fallback_schedule(today_str)

        self.state._schedule_cache = {"data": schedule_text, "date": today_str}
        try:
            self.state.local_data_manager.save_schedule_data(today_str, schedule_text)
        except Exception as e:
            logger.error(f"保存日程数据失败: {e}")

        self.state.today_schedule_display = (
            f"[当前日程 - {today_str}]\n\n{schedule_text}"
        )
        logger.debug("已更新日程显示")

        return schedule_text

    async def maybe_fetch_news(self, now: datetime) -> str:
        """Fetch morning news when needed."""
        today_str = now.strftime("%Y-%m-%d")

        if now.hour < self.state.news_hour:
            logger.debug(
                f"当前时间 {now.hour} 小于新闻获取时间 {self.state.news_hour}，跳过获取"
            )
            return ""

        if self.state.news_getter:
            cached_news = self.state.news_getter.load_news_cache(today_str)
            if cached_news:
                logger.info(f"从本地缓存加载新闻: {today_str}")
                news_text = self.state.news_getter.generate_news_text(cached_news)
                self.state._news_cache = {"data": news_text, "date": today_str}
                return news_text

        if (
            self.state._news_cache["date"] == today_str
            and self.state._news_cache["data"]
        ):
            logger.debug(f"使用内存缓存的新闻: {today_str}")
            return self.state._news_cache["data"]

        news_text = ""

        if self.state.enable_news_getter and self.state.news_getter:
            try:
                logger.info(f"开始通过新闻获取模块获取 {today_str} 的早间新闻")
                news_data = await self.state.news_getter.fetch_news_data(
                    self.state.news_topics
                )
                if news_data:
                    news_text = self.state.news_getter.generate_news_text(news_data)
                    logger.info(f"新闻获取成功，长度: {len(news_text)} 字符")
                    self.state.news_getter.save_news_cache(today_str, news_data)
                else:
                    logger.warning("新闻获取模块未能获取新闻")
            except Exception as e:
                logger.error(f"新闻获取模块出错: {e}")

        if not news_text:
            try:
                logger.info(f"回退到LLM联网搜索获取 {today_str} 的新闻")
                provider_id = self.state.get_provider_id()
                if provider_id:
                    topics = ", ".join(self.state.news_topics)
                    if self.state.news_prompt and self.state.news_prompt.strip():
                        custom_prompt = self.state.news_prompt.strip()
                        custom_prompt = custom_prompt.replace("{today}", today_str)
                        custom_prompt = custom_prompt.replace("{topics}", topics)
                        prompt = custom_prompt
                        logger.info("使用自定义新闻获取提示词")
                    else:
                        prompt = f"联网搜索{today_str}早间新闻，关注{topics}，列出3条标题+简述。"
                    resp = await self.context.llm_generate(
                        chat_provider_id=provider_id,
                        prompt=prompt,
                    )
                    news_text = (resp.completion_text or "").strip()
                    if news_text and len(news_text) >= 20:
                        logger.info(f"LLM联网搜索成功，长度: {len(news_text)} 字符")
                    else:
                        logger.warning("LLM未能成功获取新闻")
                        news_text = ""
            except Exception as e:
                logger.error(f"LLM联网搜索失败: {e}")

        self.state._news_cache = {"data": news_text, "date": today_str}
        if news_text:
            self.state.local_data_manager.save_news_data(today_str, news_text)

        return news_text

    async def get_weather_desc(self) -> str:
        """Get local weather description."""
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")

        if not self.state.weather_location:
            logger.debug("未配置天气位置，跳过天气查询")
            return ""

        cached_weather = self.state.local_data_manager.get_weather_data(today_str)
        if cached_weather:
            logger.info(f"从本地数据获取 {today_str} 的天气信息")
            current_time = time.time()
            self.state._weather_cache = {
                "data": cached_weather,
                "timestamp": current_time,
            }
            return cached_weather

        current_time = time.time()
        if (
            self.state._weather_cache["data"]
            and (current_time - self.state._weather_cache["timestamp"]) < 3600
        ):
            logger.debug(f"使用内存缓存的天气数据: {self.state._weather_cache['data']}")
            return self.state._weather_cache["data"]

        weather_text = ""

        try:
            session = self.state.get_http_session()
            url = f"https://wttr.in/{quote(self.state.weather_location, safe='')}?format=3&lang=zh-cn"
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    weather_text = (await resp.text()).strip()
                    if (
                        weather_text
                        and "抱歉" not in weather_text
                        and "无法" not in weather_text
                        and "未知" not in weather_text
                    ):
                        logger.info(f"通过wttr.in获取天气成功: {weather_text}")
                    else:
                        weather_text = ""
        except Exception as e:
            logger.debug(f"通过wttr.in获取天气失败: {e}")

        if not weather_text:
            provider_id = self.state.get_provider_id()
            if provider_id:
                try:
                    prompt = f"查询{self.state.weather_location}天气，仅返回简要描述。"
                    logger.info(f"开始查询 {self.state.weather_location} 的天气")
                    resp = await self.context.llm_generate(
                        chat_provider_id=provider_id,
                        prompt=prompt,
                    )
                    weather_text = (resp.completion_text or "").strip()
                    if (
                        weather_text
                        and "抱歉" not in weather_text
                        and "无法" not in weather_text
                        and "未知" not in weather_text
                    ):
                        logger.info(f"天气查询成功: {weather_text}")
                    else:
                        weather_text = ""
                except Exception as e:
                    logger.debug(f"使用天气工具获取天气失败: {e}")

        if weather_text:
            self.state._weather_cache = {
                "data": weather_text,
                "timestamp": current_time,
            }
            self.state.local_data_manager.save_weather_data(today_str, weather_text)
            if self.state.enable_async_thinking and self.state.async_thinking_scheduler:
                try:
                    self.state.async_thinking_scheduler.set_weather(weather_text)
                    logger.debug(f"天气信息已更新到调度器: {weather_text}")
                except Exception as e:
                    logger.debug(f"更新天气信息到调度器失败: {e}")

        return weather_text or ""

    @staticmethod
    def parse_weather_for_drawing(raw_weather: str) -> str:
        """Parse raw weather data into a clean description for drawing prompts."""
        if not raw_weather:
            return ""

        weather = raw_weather.strip()

        if ":" in weather:
            weather = weather.split(":", 1)[1].strip()

        weather_map = {
            "☀": "晴天",
            "🌤": "晴间多云",
            "⛅": "多云",
            "🌥": "阴天",
            "☁": "阴天",
            "🌦": "小雨",
            "🌧": "下雨",
            "⛈": "雷雨",
            "🌩": "雷电",
            "🌨": "下雪",
            "❄": "下雪",
            "🌫": "雾天",
            "🌪": "大风",
            "💨": "大风",
        }

        weather_desc = ""
        for emoji, desc in weather_map.items():
            if emoji in weather:
                weather_desc = desc
                break

        temp_match = re.search(r"[+-]?\d+[°℃]", weather)
        if temp_match:
            temp_str = temp_match.group(0).replace("°C", "").replace("℃", "")
            try:
                temp = int(temp_str)
                if temp < 0:
                    weather_desc = (
                        f"寒冷，{temp}°C"
                        if not weather_desc
                        else f"{weather_desc}，{temp}°C"
                    )
                elif temp < 10:
                    weather_desc = (
                        f"凉爽，{temp}°C"
                        if not weather_desc
                        else f"{weather_desc}，{temp}°C"
                    )
                elif temp < 25:
                    weather_desc = (
                        f"温和，{temp}°C"
                        if not weather_desc
                        else f"{weather_desc}，{temp}°C"
                    )
                elif temp < 35:
                    weather_desc = (
                        f"炎热，{temp}°C"
                        if not weather_desc
                        else f"{weather_desc}，{temp}°C"
                    )
                else:
                    weather_desc = (
                        f"酷热，{temp}°C"
                        if not weather_desc
                        else f"{weather_desc}，{temp}°C"
                    )
            except ValueError:
                pass

        if not weather_desc:
            weather_desc = weather[:30] if weather else ""

        return weather_desc

    @staticmethod
    def get_current_period_schedule(schedule_text: str, now: datetime) -> str:
        """Extract only the current time period's schedule for drawing prompt."""
        if not schedule_text:
            return ""

        hour = now.hour
        time_patterns = []
        if 6 <= hour < 9:
            time_patterns = [
                "6:00",
                "6：00",
                "早上",
                "上午(6",
                "早晨",
                "7:00",
                "7：00",
                "8:00",
                "8：00",
            ]
        elif 9 <= hour < 12:
            time_patterns = ["9:00", "9：00", "上午", "工作", "上课", "10:00", "11:00"]
        elif 12 <= hour < 14:
            time_patterns = ["12:00", "12：00", "中午", "午餐", "午休", "13:00"]
        elif 14 <= hour < 18:
            time_patterns = ["14:00", "14：00", "下午", "15:00", "16:00", "17:00"]
        elif 18 <= hour < 20:
            time_patterns = [
                "18:00",
                "18：00",
                "傍晚",
                "晚餐",
                "前晚",
                "19:00",
                "19：00",
            ]
        elif 20 <= hour < 23:
            time_patterns = [
                "20:00",
                "20：00",
                "晚上",
                "21:00",
                "22:00",
                "娱乐",
                "休闲",
            ]
        else:
            time_patterns = ["23:00", "23：00", "睡前", "深夜", "睡觉"]

        lines = schedule_text.split("\n")
        matched_lines = []
        for i, line in enumerate(lines):
            line_clean = line.strip().replace("**", "").replace("*", "")
            for pattern in time_patterns:
                if pattern in line_clean:
                    matched_lines.append(line_clean)
                    if i + 1 < len(lines):
                        next_line = (
                            lines[i + 1].strip().replace("**", "").replace("*", "")
                        )
                        if next_line and not any(
                            p in next_line
                            for p in [
                                "6:00",
                                "9:00",
                                "12:00",
                                "14:00",
                                "18:00",
                                "20:00",
                                "23:00",
                            ]
                        ):
                            matched_lines.append(next_line)
                    break

        if matched_lines:
            return "\n".join(matched_lines)

        return schedule_text[:100]

    def get_current_activity(self, now: datetime) -> str:
        """Infer current life activity based on time of day."""
        h = now.hour
        if h < 6 or h >= 23:
            return "已经睡觉或准备睡觉，不太方便频繁看手机"
        if 6 <= h < 9:
            return "刚起床不久，在洗漱、吃早饭或者路上通勤"
        if 9 <= h < 12:
            return "在认真上班/上课/学习，处理中午前需要完成的任务"
        if 12 <= h < 14:
            return "吃午饭、午休或刷手机放松一会儿"
        if 14 <= h < 18:
            return "继续忙工作/学习，中间会偶尔看看消息但回复不一定及时"
        if 18 <= h < 21:
            return "吃晚饭、和朋友聊天、追剧或做一些轻松的娱乐活动"
        return "准备洗漱和收尾今天的事情，一边刷手机一边慢慢放松"

    def build_fallback_schedule(self, today_str: str) -> str:
        """Fallback schedule template when LLM is unavailable."""
        return (
            f"{today_str} 的日程：\n\n"
            "今日穿搭：休闲舒适的日常装扮。\n"
            "早上：7:00起床洗漱，简单吃点早餐，整理一下今天要用的东西。\n"
            "上午：处理一些需要专注的任务，中途喝杯水休息一下。\n"
            "中午：吃个简单的午餐，午休放松半小时。\n"
            "下午：继续工作/学习，适当活动活动身体。\n"
            "傍晚：吃晚饭，出去散散步或者做点轻松的事情。\n"
            "晚上：追剧、玩游戏或者和朋友聊天，放松一下。\n"
            "睡前：洗漱，看看明天的计划，23:00左右睡觉。\n"
        )

    def get_time_description(self, now: datetime) -> str:
        """Get text description for current time."""
        hour = now.hour
        if 6 <= hour < 9:
            return "清晨时光"
        elif 9 <= hour < 12:
            return "上午时段"
        elif 12 <= hour < 14:
            return "中午时分"
        elif 14 <= hour < 18:
            return "下午时光"
        elif 18 <= hour < 20:
            return "傍晚时分"
        elif 20 <= hour < 23:
            return "晚上"
        else:
            return "深夜"

    def get_current_schedule_item(self, schedule_text: str, now: datetime) -> str:
        """Extract current time period activity from schedule text."""
        try:
            current_hour = now.hour

            time_keywords = {
                range(6, 9): ["早上", "起床", "早", "晨"],
                range(9, 12): ["上午", "上课", "上班", "工作", "课"],
                range(12, 14): ["中午", "午餐", "午饭", "午休"],
                range(14, 18): ["下午", "下午"],
                range(18, 20): ["傍晚", "晚餐", "晚饭"],
                range(20, 23): ["晚上", "晚", "夜"],
                range(23, 24): ["睡前", "睡觉", "夜"],
                range(0, 6): ["深夜", "凌晨", "失眠"],
            }

            keywords = []
            for hour_range, kws in time_keywords.items():
                if current_hour in hour_range:
                    keywords = kws
                    break

            if not keywords:
                return ""

            lines = schedule_text.split("\n")
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                for kw in keywords:
                    if kw in line:
                        cleaned = re.sub(r"^\d+\.\s*", "", line)
                        cleaned = re.sub(r"^[^：:]*[：:]\s*", "", cleaned)
                        return cleaned[:100]

        except Exception as e:
            logger.debug(f"[主动分享] 提取当前日程失败: {e}")
        return ""

    def is_in_share_time_range(self, hour: int) -> bool:
        """Check if current hour is within allowed share time ranges."""
        try:
            ranges = self.state.proactive_share_time_ranges
            if not ranges:
                return True

            for range_str in ranges.split(","):
                range_str = range_str.strip()
                if not range_str:
                    continue
                if "-" in range_str:
                    start, end = range_str.split("-")
                    start_hour = int(start.strip())
                    end_hour = int(end.strip())
                    if start_hour <= hour < end_hour:
                        return True
        except Exception as e:
            logger.debug(f"[主动分享] 解析时间段失败: {e}")
        return False

    def build_fallback_share(self, now: datetime) -> str:
        """Fallback share content when LLM is unavailable."""
        import random

        hour = now.hour
        fallbacks = {
            "morning": [
                "早安~新的一天开始了☀️",
                "起床啦，今天也要加油💪",
                "早上好呀，吃早餐了没？",
                "新的一天，新的开始🌈",
            ],
            "noon": [
                "午饭时间到！干饭人干饭魂🍚",
                "中午好~该休息一下了",
                "午饭吃了啥？🤔",
            ],
            "afternoon": [
                "下午有点犯困呢😴",
                "下午好~继续努力中",
                "喝杯下午茶☕",
            ],
            "evening": [
                "晚上好~忙碌的一天快结束了",
                "终于到晚上了，放松一下🌙",
                "晚饭后散个步🚶",
            ],
            "night": [
                "夜深了，还不想睡呢🌙",
                "深夜emo时间...",
                "晚安前再刷一会儿手机📱",
            ],
        }

        if 6 <= hour < 12:
            period = "morning"
        elif 12 <= hour < 14:
            period = "noon"
        elif 14 <= hour < 18:
            period = "afternoon"
        elif 18 <= hour < 22:
            period = "evening"
        else:
            period = "night"

        return random.choice(fallbacks[period])

    async def get_thinking_context(self) -> dict:
        """Provide context info for async thinking (weather, schedule, news, conversations, experiences)."""
        ctx: dict = {}
        now = datetime.now()

        try:
            if hasattr(self.state, "_weather_cache") and self.state._weather_cache.get(
                "data"
            ):
                ctx["weather"] = self.state._weather_cache["data"]
            else:
                weather = await self.get_weather_desc()
                if weather:
                    ctx["weather"] = weather
        except Exception as e:
            logger.debug(f"[思考上下文] 获取天气失败: {e}")

        try:
            schedule = await self.maybe_generate_schedule(now)
            if schedule:
                ctx["schedule"] = schedule
        except Exception as e:
            logger.debug(f"[思考上下文] 获取日程失败: {e}")

        try:
            if hasattr(self.state, "_news_cache") and self.state._news_cache.get(
                "data"
            ):
                ctx["news"] = self.state._news_cache["data"]
        except Exception as e:
            logger.debug(f"[思考上下文] 获取新闻失败: {e}")

        try:
            if self.state.experience_bank:
                convs = self.state.experience_bank.get_recent_conversations(limit=5)
                if convs:
                    conv_summaries = []
                    for c in convs:
                        user_msg = c.get("user_message", "")
                        bot_msg = c.get("bot_response", "")
                        if user_msg or bot_msg:
                            conv_summaries.append(f"用户:{user_msg} 机器人:{bot_msg}")
                    if conv_summaries:
                        ctx["recent_conversations"] = "；".join(conv_summaries[:5])
        except Exception as e:
            logger.debug(f"[思考上下文] 获取最近对话失败: {e}")

        try:
            if self.state.experience_bank:
                events = self.state.experience_bank.get_recent_events(limit=5)
                if events:
                    event_summaries = [
                        f"[{e.get('event_type', '')}] {e.get('description', '')}"
                        for e in events
                        if e.get("description")
                    ]
                    if event_summaries:
                        ctx["recent_experiences"] = "；".join(event_summaries[:5])
        except Exception as e:
            logger.debug(f"[思考上下文] 获取最近经历失败: {e}")

        return ctx

    async def get_system_persona_profile(self) -> str:
        """Get persona description from system."""
        try:
            default_persona = (
                await self.context.persona_manager.get_default_persona_v3()
            )
            return (
                default_persona["prompt"]
                or "一个普通的年轻人，有自己的日程、情绪和兴趣，会像真人一样安排每天的生活。"
            )
        except Exception as e:
            logger.warning(f"获取系统人设失败: {e}，使用默认人设")
            return "一个普通的年轻人，有自己的日程、情绪和兴趣，会像真人一样安排每天的生活。"
