import random
import zoneinfo
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from astrbot.api import logger
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.star.context import Context

from .operate import PostOperator

# ============================
# 自动发说说（支持每天多次、时间段和失眠功能）
# ============================


class AutoPublish:
    def __init__(self, context: Context, config: AstrBotConfig, operator: PostOperator):
        self.context = context
        self.config = config
        self.operator = operator

        tz = context.get_config().get("timezone")
        self.timezone = (
            zoneinfo.ZoneInfo(tz) if tz else zoneinfo.ZoneInfo("Asia/Shanghai")
        )

        self.scheduler = AsyncIOScheduler(timezone=self.timezone)

        # 获取配置
        self.publish_times_per_day = config.get("publish_times_per_day", 3)
        self.publish_time_ranges = config.get("publish_time_ranges", [])
        self.insomnia_probability = config.get("insomnia_probability", 0.15)

        # 如果未指定时间段或为空，或者时间段数量与发说说次数不匹配，自动重新生成
        if (
            not self.publish_time_ranges
            or len(self.publish_time_ranges) != self.publish_times_per_day
        ):
            reason = (
                "时间段为空"
                if not self.publish_time_ranges
                else f"时间段数量({len(self.publish_time_ranges)})与发说说次数({self.publish_times_per_day})不匹配"
            )
            self.publish_time_ranges = self._auto_generate_time_ranges(
                self.publish_times_per_day
            )
            logger.info(
                f"[自动发说说] {reason}，自动重新分配时间段: {self.publish_time_ranges}"
            )

        # 记录今日发布次数
        self.today_publish_count = 0
        self.last_publish_date = ""

        self.scheduler.start()
        self._schedule_daily_posts()
        self._schedule_insomnia_check()
        if self.config.get("enable_auto_reply_comments", True):
            self._schedule_comment_check()

        logger.info(
            f"[自动发说说] 已启动，每天{self.publish_times_per_day}次，时间段{self.publish_time_ranges}"
        )

    @staticmethod
    def _auto_generate_time_ranges(count: int) -> list[str]:
        """根据每天发说说次数自动分配时间段

        将活跃时段(9:00-22:00)均分为 count 个区间，每个区间用 'start-end' 格式。

        Args:
            count: 每天发说说次数

        Returns:
            时间段列表，如 ['9-13', '13-18', '18-22']
        """
        if count <= 0:
            return []
        if count == 1:
            return ["9-22"]

        start_hour = 9
        end_hour = 22
        total_hours = end_hour - start_hour
        # 均分时间段
        slot_size = total_hours / count
        ranges = []
        for i in range(count):
            s = int(start_hour + i * slot_size)
            e = int(start_hour + (i + 1) * slot_size)
            # 确保最后一个段到 end_hour
            if i == count - 1:
                e = end_hour
            ranges.append(f"{s}-{e}")
        return ranges

    def _schedule_comment_check(self):
        """安排定期检查评论并回复的任务"""
        # 每10分钟检查一次新评论
        self.scheduler.add_job(
            func=self._check_and_reply_comments,
            trigger=IntervalTrigger(
                minutes=10, timezone=self.timezone
            ),  # 每10分钟检查一次
            name="comment_checker",
            max_instances=1,
        )
        logger.info("[自动回复评论] 已启动，每10分钟检查一次")

    async def _check_and_reply_comments(self):
        """检查并回复评论"""
        try:
            # 检查operator是否正确初始化
            if not self.operator:
                logger.debug("[SCHEDULER] operator 未初始化，跳过评论检查")
                return

            # 检查operator中的qzone是否可用
            if not hasattr(self.operator, "qzone") or not self.operator.qzone:
                logger.debug("[SCHEDULER] operator.qzone 未初始化，跳过评论检查")
                return

            # 检查qzone.ctx是否可用
            if not hasattr(self.operator.qzone, "ctx") or not self.operator.qzone.ctx:
                logger.debug("[SCHEDULER] operator.qzone.ctx 未初始化，跳过评论检查")
                return

            logger.debug("[SCHEDULER] 开始检查新评论并回复")
            await self.operator.auto_reply_to_comments()
            logger.debug("[SCHEDULER] 评论检查和回复完成")
        except Exception as e:
            logger.error(f"[SCHEDULER] 检查和回复评论失败: {e}")
            logger.error(f"[自动回复评论] 检查和回复评论失败: {e}")

    def _schedule_daily_posts(self):
        """安排每天的发说说任务"""
        # 每天凌晨0点重置计数器并安排当天任务
        self.scheduler.add_job(
            func=self._reset_and_schedule_today,
            trigger=CronTrigger(hour=0, minute=0, timezone=self.timezone),
            name="daily_reset_scheduler",
            max_instances=1,
        )

        # 立即安排今天的任务
        logger.debug("[SCHEDULER] 开始安排今天的发说说任务")
        self._schedule_today_posts()

    def _reset_and_schedule_today(self):
        """重置计数器并安排今天的发布任务"""
        self.today_publish_count = 0
        # Reset last_publish_date BEFORE _schedule_today_posts so it doesn't skip
        self.last_publish_date = ""
        self._schedule_today_posts()
        today_str = datetime.now(self.timezone).strftime("%Y-%m-%d")
        logger.debug(f"[SCHEDULER] 新的一天开始: {today_str}, 重置发布计数器")
        logger.info("[自动发说说] 新的一天，重置计数器")

    def _schedule_today_posts(self):
        """安排今天的发布任务"""
        now = datetime.now(self.timezone)
        today_str = now.strftime("%Y-%m-%d")

        # 如果已经安排过今天的任务，不重复安排
        if self.last_publish_date == today_str:
            logger.debug(f"[SCHEDULER] {today_str} 的发布任务已安排，跳过")
            return

        self.last_publish_date = today_str
        logger.debug(
            f"[SCHEDULER] 开始为 {today_str} 安排 {self.publish_times_per_day} 次发布任务"
        )

        # 根据配置的次数和时间段，生成随机时间点
        for i in range(self.publish_times_per_day):
            # 选择一个时间段
            time_range = self.publish_time_ranges[i % len(self.publish_time_ranges)]

            # 支持两种格式：小时范围（如"9-12"）和具体时间范围（如"20:00-20:20"）
            if ":" in time_range:
                # 具体时间范围格式，如"20:00-20:20"
                start_time_str, end_time_str = time_range.split("-")
                start_hour, start_minute = map(int, start_time_str.split(":"))
                end_hour, end_minute = map(int, end_time_str.split(":"))

                # 计算总分钟数范围
                start_total_minutes = start_hour * 60 + start_minute
                end_total_minutes = end_hour * 60 + end_minute

                # 如果结束时间小于开始时间（跨天），需要特殊处理
                if end_total_minutes <= start_total_minutes:
                    # 跨天情况，比如"23:30-01:30"
                    total_minutes_diff = (
                        24 * 60 - start_total_minutes
                    ) + end_total_minutes
                    random_offset = random.randint(0, total_minutes_diff)
                    if random_offset <= (24 * 60 - start_total_minutes):
                        # 在当天范围内
                        final_total_minutes = start_total_minutes + random_offset
                        random_hour = final_total_minutes // 60
                        random_minute = final_total_minutes % 60
                    else:
                        # 在跨天范围内
                        final_total_minutes = (
                            random_offset - (24 * 60 - start_total_minutes)
                        ) % (24 * 60)
                        random_hour = final_total_minutes // 60
                        random_minute = final_total_minutes % 60
                else:
                    # 普通情况
                    random_total_minutes = random.randint(
                        start_total_minutes, end_total_minutes
                    )
                    random_hour = random_total_minutes // 60
                    random_minute = random_total_minutes % 60
            else:
                # 小时范围格式，如"9-12"
                start_hour, end_hour = map(int, time_range.split("-"))

                # 在该时间段内随机选择一个时间
                random_hour = random.randint(start_hour, end_hour - 1)
                random_minute = random.randint(0, 59)

            # 计算目标时间
            target_time = now.replace(
                hour=random_hour, minute=random_minute, second=0, microsecond=0
            )

            # 如果时间已经过去，跳过
            if target_time <= now:
                logger.debug(
                    f"[SCHEDULER] 随机时间 {target_time.strftime('%H:%M')} 已过去，跳过"
                )
                continue

            # 安排任务
            self.scheduler.add_job(
                func=self._publish_post,
                trigger=DateTrigger(run_date=target_time, timezone=self.timezone),
                name=f"auto_publish_{i}_{target_time.timestamp()}",
                max_instances=1,
            )

            logger.debug(
                f"[SCHEDULER] 安排今天第{i + 1}次发布: {target_time.strftime('%H:%M')} (时间段 {time_range})"
            )
            logger.info(
                f"[自动发说说] 安排今天第{i + 1}次发布: {target_time.strftime('%H:%M')}"
            )

    def _schedule_insomnia_check(self):
        """安排失眠检查任务（23:00-02:00之间每30分钟检查一次）"""
        # 每半小时检查一次是否触发失眠发说说
        self.scheduler.add_job(
            func=self._check_insomnia,
            trigger=IntervalTrigger(minutes=30, timezone=self.timezone),
            name="insomnia_checker",
            max_instances=1,
        )

    async def _check_insomnia(self):
        """检查是否触发失眠发说说"""
        now = datetime.now(self.timezone)
        hour = now.hour

        # 只在23:00-02:00之间触发
        if not (hour >= 23 or hour < 2):
            return

        # 按概率触发
        if random.random() > self.insomnia_probability:
            logger.debug(
                f"[SCHEDULER] 失眠检查 - 时间 {now.strftime('%H:%M')}，概率未达到，跳过"
            )
            return

        logger.debug(
            f"[SCHEDULER] 失眠检查 - 时间 {now.strftime('%H:%M')}，触发失眠发说说"
        )
        logger.info("[自动发说说] 触发失眠发说说")
        await self._publish_post(insomnia=True)

    async def _publish_post(self, insomnia: bool = False):
        """执行发布任务"""
        try:
            # 检查今日发布次数（失眠不计入）
            today_str = datetime.now(self.timezone).strftime("%Y-%m-%d")
            if self.last_publish_date != today_str:
                self.today_publish_count = 0
                self.last_publish_date = today_str

            if not insomnia:
                if self.today_publish_count >= self.publish_times_per_day:
                    logger.debug(
                        f"[SCHEDULER] 今日发布次数已达上限 {self.publish_times_per_day}，跳过发布"
                    )
                    logger.info("[自动发说说] 今日发布次数已达上限，跳过")
                    return
                self.today_publish_count += 1

            logger.debug(
                f"[SCHEDULER] {'(失眠)' if insomnia else ''}开始发布说说，今日第{self.today_publish_count}次"
            )

            # 失眠时使用专门的主题生成日记
            if insomnia:
                # 先生成失眠主题的日记文本
                text = await self.operator.llm.generate_diary(topic="失眠随想")
                logger.debug(
                    f"[SCHEDULER] 失眠说说内容: {text[:50]}..."
                    if text
                    else "[SCHEDULER] 失眠说说内容: 生成失败"
                )
                # 然后调用publish_feed，传入文本和配图选项
                await self.operator.publish_feed(text=text, llm_images=True)
            else:
                # 正常发布，让llm自动生成文本和配图
                logger.debug("[SCHEDULER] 正常发布说说，调用LLM生成内容")
                await self.operator.publish_feed(llm_text=True, llm_images=True)

            logger.debug(f"[SCHEDULER] {'(失眠)' if insomnia else ''}发布成功")
            logger.info(f"[自动发说说] {'(失眠)' if insomnia else ''}发布成功")
        except Exception as e:
            logger.error(f"[SCHEDULER] 发布失败: {e}")
            logger.error(f"[自动发说说] 发布失败: {e}")

    async def do_task(self):
        """Deprecated: 为了保持兼容性"""
        await self._publish_post()

    async def terminate(self):
        self.scheduler.remove_all_jobs()
        logger.info("[自动发说说] 已停止")
