import random
import zoneinfo
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from astrbot.api import logger
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.star.context import Context

from .operate import PostOperator

# ============================
# 基类：随机偏移的周期任务
# ============================


class AutoRandomCronTask:
    """
    基类：在 cron 规定的周期内随机某个时间点执行任务。
    子类只需实现 async do_task()。
    """

    def __init__(self, context: Context, cron_expr: str, job_name: str):
        tz = context.get_config().get("timezone")
        self.timezone = (
            zoneinfo.ZoneInfo(tz) if tz else zoneinfo.ZoneInfo("Asia/Shanghai")
        )

        self.scheduler = AsyncIOScheduler(timezone=self.timezone)
        self.scheduler.start()

        self.cron_expr = cron_expr
        self.job_name = job_name

        self.register_task()

        logger.info(f"[{self.job_name}] 已启动，任务周期：{self.cron_expr}")

    # 注册 cron → 触发 schedule_random_job
    def register_task(self):
        try:
            self.trigger = CronTrigger.from_crontab(self.cron_expr)
            self.scheduler.add_job(
                func=self.schedule_random_job,
                trigger=self.trigger,
                name=f"{self.job_name}_scheduler",
                max_instances=1,
            )
        except Exception as e:
            logger.error(f"[{self.job_name}] Cron 格式错误：{e}")

    # 计算当前周期随机时间点，并安排 DateTrigger 执行
    def schedule_random_job(self):
        now = datetime.now(self.timezone)
        next_run = self.trigger.get_next_fire_time(None, now)
        if not next_run:
            logger.error(f"[{self.job_name}] 无法计算下一次周期时间")
            return

        cycle_seconds = int((next_run - now).total_seconds())
        delay = random.randint(0, cycle_seconds)
        target_time = now + timedelta(seconds=delay)

        logger.info(f"[{self.job_name}] 下周期随机执行时间：{target_time}")

        self.scheduler.add_job(
            func=self._run_task_wrapper,
            trigger=DateTrigger(run_date=target_time, timezone=self.timezone),
            name=f"{self.job_name}_once_{target_time.timestamp()}",
            max_instances=1,
        )

    # 统一包装（方便打印日志）
    async def _run_task_wrapper(self):
        logger.info(f"[{self.job_name}] 开始执行任务")
        await self.do_task()
        logger.info(f"[{self.job_name}] 本轮任务完成")

    # 子类实现
    async def do_task(self):
        raise NotImplementedError

    async def terminate(self):
        self.scheduler.remove_all_jobs()
        logger.info(f"[{self.job_name}] 已停止")


# ============================
# 自动评论
# ============================


class AutoComment(AutoRandomCronTask):
    def __init__(
        self,
        context: Context,
        config: AstrBotConfig,
        operator: PostOperator,
    ):
        self.operator = operator
        super().__init__(context, config["comment_cron"], "AutoComment")

    async def do_task(self):
        await self.operator.read_feed(get_recent=True)


# ============================
# 自动发说说（支持每天多次、时间段和失眠功能）
# ============================


class AutoPublish:
    def __init__(
        self,
        context: Context,
        config: AstrBotConfig,
        operator: PostOperator
    ):
        self.context = context
        self.config = config
        self.operator = operator
        
        tz = context.get_config().get("timezone")
        self.timezone = (
            zoneinfo.ZoneInfo(tz) if tz else zoneinfo.ZoneInfo("Asia/Shanghai")
        )
        
        self.scheduler = AsyncIOScheduler(timezone=self.timezone)
        
        # 获取配置
        self.publish_times_per_day = config.get("publish_times_per_day", 1)
        self.publish_time_ranges = config.get("publish_time_ranges", ["9-12", "14-18", "19-22"])
        self.insomnia_probability = config.get("insomnia_probability", 0.2)
        
        # 记录今日发布次数
        self.today_publish_count = 0
        self.last_publish_date = ""
        
        self.scheduler.start()
        self._schedule_daily_posts()
        self._schedule_insomnia_check()
        
        logger.info(f"[自动发说说] 已启动，每天{self.publish_times_per_day}次，时间段{self.publish_time_ranges}")
    
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
        print("[SCHEDULER] 开始安排今天的发说说任务")  # 终端日志
        self._schedule_today_posts()
    
    def _reset_and_schedule_today(self):
        """重置计数器并安排今天的发布任务"""
        self.today_publish_count = 0
        self.last_publish_date = datetime.now(self.timezone).strftime("%Y-%m-%d")
        self._schedule_today_posts()
        print(f"[SCHEDULER] 新的一天开始: {self.last_publish_date}, 重置发布计数器")  # 终端日志
        logger.info("[自动发说说] 新的一天，重置计数器")
    
    def _schedule_today_posts(self):
        """安排今天的发布任务"""
        now = datetime.now(self.timezone)
        today_str = now.strftime("%Y-%m-%d")
        
        # 如果已经安排过今天的任务，不重复安排
        if self.last_publish_date == today_str:
            print(f"[SCHEDULER] {today_str} 的发布任务已安排，跳过")  # 终端日志
            return
        
        self.last_publish_date = today_str
        print(f"[SCHEDULER] 开始为 {today_str} 安排 {self.publish_times_per_day} 次发布任务")  # 终端日志
        
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
                    total_minutes_diff = (24 * 60 - start_total_minutes) + end_total_minutes
                    random_offset = random.randint(0, total_minutes_diff)
                    if random_offset <= (24 * 60 - start_total_minutes):
                        # 在当天范围内
                        final_total_minutes = start_total_minutes + random_offset
                        random_hour = final_total_minutes // 60
                        random_minute = final_total_minutes % 60
                    else:
                        # 在跨天范围内
                        final_total_minutes = (random_offset - (24 * 60 - start_total_minutes)) % (24 * 60)
                        random_hour = final_total_minutes // 60
                        random_minute = final_total_minutes % 60
                else:
                    # 普通情况
                    random_total_minutes = random.randint(start_total_minutes, end_total_minutes)
                    random_hour = random_total_minutes // 60
                    random_minute = random_total_minutes % 60
            else:
                # 小时范围格式，如"9-12"
                start_hour, end_hour = map(int, time_range.split("-"))
                
                # 在该时间段内随机选择一个时间
                random_hour = random.randint(start_hour, end_hour - 1)
                random_minute = random.randint(0, 59)
            
            # 计算目标时间
            target_time = now.replace(hour=random_hour, minute=random_minute, second=0, microsecond=0)
            
            # 如果时间已经过去，跳过
            if target_time <= now:
                print(f"[SCHEDULER] 随机时间 {target_time.strftime('%H:%M')} 已过去，跳过")  # 终端日志
                continue
            
            # 安排任务
            self.scheduler.add_job(
                func=self._publish_post,
                trigger=DateTrigger(run_date=target_time, timezone=self.timezone),
                name=f"auto_publish_{i}_{target_time.timestamp()}",
                max_instances=1,
            )
            
            print(f"[SCHEDULER] 安排今天第{i+1}次发布: {target_time.strftime('%H:%M')} (时间段 {time_range})")  # 终端日志
            logger.info(f"[自动发说说] 安排今天第{i+1}次发布: {target_time.strftime('%H:%M')}")
    
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
            print(f"[SCHEDULER] 失眠检查 - 时间 {now.strftime('%H:%M')}，概率未达到，跳过")  # 终端日志
            return
        
        print(f"[SCHEDULER] 失眠检查 - 时间 {now.strftime('%H:%M')}，触发失眠发说说")  # 终端日志
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
                    print(f"[SCHEDULER] 今日发布次数已达上限 {self.publish_times_per_day}，跳过发布")  # 终端日志
                    logger.info("[自动发说说] 今日发布次数已达上限，跳过")
                    return
                self.today_publish_count += 1
            
            print(f"[SCHEDULER] {'(失眠)' if insomnia else ''}开始发布说说，今日第{self.today_publish_count}次")  # 终端日志
            
            # 失眠时使用专门的主题生成日记
            if insomnia:
                # 先生成失眠主题的日记文本
                text = await self.operator.llm.generate_diary(topic="失眠随想")
                print(f"[SCHEDULER] 失眠说说内容: {text[:50]}..." if text else "[SCHEDULER] 失眠说说内容: 生成失败")  # 终端日志
                # 然后调用publish_feed，传入文本和配图选项
                await self.operator.publish_feed(text=text, llm_images=True)
            else:
                # 正常发布，让llm自动生成文本和配图
                print("[SCHEDULER] 正常发布说说，调用LLM生成内容")  # 终端日志
                await self.operator.publish_feed(llm_text=True, llm_images=True)
            
            print(f"[SCHEDULER] {'(失眠)' if insomnia else ''}发布成功")  # 终端日志
            logger.info(f"[自动发说说] {'(失眠)' if insomnia else ''}发布成功")
        except Exception as e:
            print(f"[SCHEDULER] 发布失败: {e}")  # 终端日志
            logger.error(f"[自动发说说] 发布失败: {e}")
    
    async def do_task(self):
        """Deprecated: 为了保持兼容性"""
        await self._publish_post()
    
    async def terminate(self):
        self.scheduler.remove_all_jobs()
        logger.info("[自动发说说] 已停止")
