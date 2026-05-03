"""
新闻获取模块 (News Getter Module)
基于 astrbot_plugin_daily_news 的实现方式，为拟人化角色提供联网新闻功能

版本: v1.0.0
作者: custom
最后更新: 2025-01-01
"""

from datetime import datetime
from pathlib import Path

import aiohttp

from astrbot.api import logger


class NewsGetter:
    """新闻获取器

    负责从多个数据源获取新闻信息，用于为角色构建生活背景
    采用多源容错策略，确保获取可靠性

    属性:
        data_dir: 数据存储目录
        enable_online_fetch: 是否启用联网获取
        topics: 关注的新闻主题列表
    """

    def __init__(
        self,
        data_dir: Path,
        enable_online_fetch: bool = True,
        topics: list[str] | None = None,
    ):
        """初始化新闻获取器

        Args:
            data_dir: 数据存储目录
            enable_online_fetch: 是否启用联网获取，默认True
            topics: 关注的新闻主题列表
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.enable_online_fetch = enable_online_fetch
        self.topics = topics or ["科技", "生活方式", "兴趣相关话题"]

        # 新闻数据缓存文件
        self.news_cache_file = self.data_dir / "news_cache.json"

        logger.debug(
            f"[新闻获取器] 已初始化，启用联网: {enable_online_fetch}, 主题: {topics}"
        )

    async def fetch_news_data(self, topics: list[str] | None = None) -> dict | None:
        """获取新闻数据

        采用多源容错策略，依次尝试从多个API获取数据

        Args:
            topics: 新闻主题列表，默认使用初始化时设置的主题

        Returns:
            新闻数据字典，包含 news 和 date 字段；获取失败返回 None

        示例:
            {
                "date": "2025-01-01",
                "news": [
                    {"title": "...", "summary": "..."},
                    ...
                ],
                "source": "API名称"
            }
        """
        if not self.enable_online_fetch:
            logger.warning("[新闻获取器] 联网获取已禁用")
            return None

        topics = topics or self.topics

        # 多个API源，按优先级排列
        api_sources = [
            self._fetch_from_baidu_news,
            self._fetch_from_bing_news,
            self._fetch_from_generic_api,
        ]

        for api_func in api_sources:
            try:
                logger.debug(f"[新闻获取器] 尝试 {api_func.__name__}...")
                data = await api_func(topics)
                if data:
                    logger.info(f"[新闻获取器] 成功从 {api_func.__name__} 获取新闻")
                    return data
            except Exception as e:
                logger.warning(f"[新闻获取器] {api_func.__name__} 失败: {e}")
                continue

        logger.error("[新闻获取器] 所有新闻源均获取失败")
        return None

    async def _fetch_from_baidu_news(self, topics: list[str]) -> dict | None:
        """从百度热搜获取数据

        Args:
            topics: 新闻主题列表

        Returns:
            新闻数据字典或None
        """
        try:
            url = "https://top.baidu.com/board?tab=realtime"

            async with aiohttp.ClientSession() as session:
                timeout = aiohttp.ClientTimeout(total=10)
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }
                async with session.get(url, timeout=timeout, headers=headers) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        import re

                        # Extract hot search titles from the page
                        titles = re.findall(
                            r'class="c-single-text-ellipsis"[^>]*>([^<]+)<', text
                        )
                        if not titles:
                            titles = re.findall(
                                r'<div[^>]*title="([^"]+)"[^>]*class="[^"]*title[^"]*"',
                                text,
                            )
                        if not titles:
                            # Fallback pattern for baidu hot search
                            titles = re.findall(
                                r'content_[^"]*"[^>]*>([^<]{4,60})<', text
                            )

                        news_list = []
                        for title in titles[:5]:
                            title = title.strip()
                            if title and len(title) > 3 and "百度" not in title:
                                news_list.append(
                                    {
                                        "title": title,
                                        "summary": "来自百度热搜",
                                    }
                                )

                        if news_list:
                            return {
                                "date": datetime.now().strftime("%Y-%m-%d"),
                                "news": news_list[:3],
                                "source": "百度热搜",
                            }
        except Exception as e:
            logger.debug(f"[新闻获取器] 百度热搜API错误: {e}")

        return None

    async def _fetch_from_bing_news(self, topics: list[str]) -> dict | None:
        """从必应新闻获取数据

        Args:
            topics: 新闻主题列表

        Returns:
            新闻数据字典或None
        """
        try:
            topic_query = " ".join(topics[:2])  # 使用前2个主题
            url = f"https://cn.bing.com/news/search?q={topic_query}&format=rss"

            async with aiohttp.ClientSession() as session:
                timeout = aiohttp.ClientTimeout(total=10)
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }
                async with session.get(url, timeout=timeout, headers=headers) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        # 简单的RSS解析
                        news_list = []

                        # 提取标题（简单正则）
                        import re

                        titles = re.findall(r"<title>([^<]+)</title>", text)
                        for title in titles[
                            1:4
                        ]:  # 跳过第一个（RSS标题），取接下来的3条
                            if title and len(title) > 5:
                                news_list.append(
                                    {"title": title, "summary": "来自必应新闻"}
                                )

                        if news_list:
                            return {
                                "date": datetime.now().strftime("%Y-%m-%d"),
                                "news": news_list,
                                "source": "必应新闻",
                            }
        except Exception as e:
            logger.debug(f"[新闻获取器] 必应新闻API错误: {e}")

        return None

    async def _fetch_from_generic_api(self, topics: list[str]) -> dict | None:
        """从搜狗新闻获取数据

        Args:
            topics: 新闻主题列表

        Returns:
            新闻数据字典或None
        """
        try:
            topic_query = topics[0] if topics else "今日新闻"

            url = f"https://news.sogou.com/news?query={topic_query}&sort=1"

            async with aiohttp.ClientSession() as session:
                timeout = aiohttp.ClientTimeout(total=10)
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }
                async with session.get(url, timeout=timeout, headers=headers) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        import re

                        # Extract news titles from sogou
                        titles = re.findall(
                            r"<h3[^>]*>.*?<a[^>]*>([^<]+)</a>", text, re.DOTALL
                        )
                        if not titles:
                            titles = re.findall(
                                r'class="[^"]*title[^"]*"[^>]*>([^<]{6,80})<', text
                            )

                        news_list = []
                        for title in titles[:3]:
                            title = title.strip()
                            if title and len(title) > 5:
                                news_list.append(
                                    {
                                        "title": title,
                                        "summary": "来自搜狗新闻",
                                    }
                                )

                        if news_list:
                            return {
                                "date": datetime.now().strftime("%Y-%m-%d"),
                                "news": news_list,
                                "source": "搜狗新闻",
                            }
        except Exception as e:
            logger.debug(f"[新闻获取器] 搜狗新闻API错误: {e}")

        return None

    def generate_news_text(self, news_data: dict) -> str:
        """将新闻数据转换为文本格式

        Args:
            news_data: 新闻数据字典

        Returns:
            格式化的新闻文本
        """
        if not news_data or "news" not in news_data:
            return ""

        try:
            date = news_data.get("date", "")
            news_items = news_data.get("news", [])
            source = news_data.get("source", "新闻源")

            text = f"【{date}早间新闻】来自{source}\n\n"

            for i, item in enumerate(news_items, 1):
                title = item.get("title", "").strip()
                summary = item.get("summary", "").strip()

                if title:
                    text += f"{i}. {title}\n"
                    if summary:
                        text += f"   {summary}\n"

            text += f"\n【数据来源】{source}"
            return text
        except Exception as e:
            logger.error(f"[新闻获取器] 生成新闻文本失败: {e}")
            return ""

    def save_news_cache(self, today_str: str, news_data: dict) -> bool:
        """保存新闻缓存到本地

        Args:
            today_str: 日期字符串 (YYYY-MM-DD)
            news_data: 新闻数据字典

        Returns:
            是否保存成功
        """
        try:
            import json

            # 读取现有缓存
            cache = {}
            if self.news_cache_file.exists():
                with open(self.news_cache_file, encoding="utf-8") as f:
                    cache = json.load(f)

            # 更新缓存
            cache[today_str] = news_data

            # 写入缓存
            with open(self.news_cache_file, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)

            logger.debug(f"[新闻获取器] 新闻缓存已保存: {today_str}")
            return True
        except Exception as e:
            logger.error(f"[新闻获取器] 保存新闻缓存失败: {e}")
            return False

    def load_news_cache(self, today_str: str) -> dict | None:
        """从本地加载新闻缓存

        Args:
            today_str: 日期字符串 (YYYY-MM-DD)

        Returns:
            新闻数据字典或None
        """
        try:
            import json

            if not self.news_cache_file.exists():
                return None

            with open(self.news_cache_file, encoding="utf-8") as f:
                cache = json.load(f)

            if today_str in cache:
                logger.debug(f"[新闻获取器] 从缓存加载新闻: {today_str}")
                return cache[today_str]
        except Exception as e:
            logger.debug(f"[新闻获取器] 加载新闻缓存失败: {e}")

        return None
