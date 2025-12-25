import random
import re
from datetime import datetime
from typing import Any

import aiohttp
import asyncio
import json
from aiocqhttp import CQHttp

from astrbot.api import logger
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.provider.provider import Provider
from astrbot.core.star.context import Context

from .post import Post


class LLMAction:
    def __init__(self, context: Context, config: AstrBotConfig, client: CQHttp):
        self.context = context
        self.config = config
        self.client = client
        # 使用 get 方法获取可选配置，默认为 None
        self.comment_provider_id = self.config.get("comment_provider_id")
        self.diary_provider_id = self.config.get("diary_provider_id")

        # ModelScope 生图配置
        self.ms_api_key: str | None = self.config.get("ms_api_key")
        self.ms_api_url: str = self.config.get(
            "ms_api_url",
            "https://api.modelscope.com/api/",
        )
        self.ms_model: str = self.config.get("ms_model", "iic/sdxl-turbo")
        self.ms_size: str = self.config.get("ms_size", "1080x1920")
        self.weather_location: str = self.config.get("weather_location", "")

    async def _request_modelscope(self, prompt: str, size: str | None = None) -> str:
        """调用 ModelScope 文生图，返回图片 URL"""
        if not self.ms_api_key:
            raise ValueError("未配置 ms_api_key，无法使用 ModelScope 生图")
        size = size or self.ms_size
        headers = {
            "Authorization": f"Bearer {self.ms_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.ms_model,
            "prompt": prompt,
            "size": size,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.ms_api_url}v1/images/generations",
                headers=headers,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
        # 简单兼容同步/异步两种返回格式
        if "output_images" in data and data["output_images"]:
            return data["output_images"][0]
        if "task_id" in data:
            task_id = data["task_id"]
            delay = 1
            while True:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"{self.ms_api_url}v1/tasks/{task_id}",
                        headers={
                            "Authorization": f"Bearer {self.ms_api_key}",
                            "Content-Type": "application/json",
                            "X-ModelScope-Task-Type": "image_generation",
                        },
                    ) as r2:
                        r2.raise_for_status()
                        tdata = await r2.json()
                if tdata.get("task_status") == "SUCCEED":
                    imgs = tdata.get("output_images", [])
                    if imgs:
                        return imgs[0]
                    break
                if tdata.get("task_status") == "FAILED":
                    break
                await asyncio.sleep(delay)
                delay = min(delay * 2, 10)
        raise ValueError("ModelScope 未返回图片 URL")

    async def _get_weather_desc(self) -> str:
        """获取简单天气描述（用于写日记和画图提示词）"""
        if not self.weather_location:
            return ""
        try:
            async with aiohttp.ClientSession() as session:
                url = f"https://wttr.in/{self.weather_location}?format=3&lang=zh-cn"
                async with session.get(url, timeout=5) as resp:
                    if resp.status == 200:
                        return (await resp.text()).strip()
        except Exception:
            return ""
        return ""

    def _build_context(
        self, round_messages: list[dict[str, Any]]
    ) -> list[dict[str, str]]:
        """把所有回合里的纯文本消息打包成 openai-style 的 user 上下文。"""
        contexts: list[dict[str, str]] = []
        for msg in round_messages:
            text_segments = [
                seg["data"]["text"] for seg in msg["message"] if seg["type"] == "text"
            ]
            text = f"{msg['sender']['nickname']}: {''.join(text_segments).strip()}"
            if text:
                contexts.append({"role": "user", "content": text})
        return contexts

    async def _get_msg_contexts(self, group_id: str) -> list[dict]:
        """获取群聊历史消息"""
        message_seq = 0
        contexts: list[dict] = []
        while len(contexts) < self.config["diary_max_msg"]:
            payloads = {
                "group_id": group_id,
                "message_seq": message_seq,
                "count": 200,
                "reverseOrder": True,
            }
            result: dict = await self.client.api.call_action(
                "get_group_msg_history", **payloads
            )
            round_messages = result["messages"]
            if not round_messages:
                break
            message_seq = round_messages[0]["message_id"]

            contexts.extend(self._build_context(round_messages))
        return contexts

    @staticmethod
    def extract_content(diary: str) -> str:
        start_marker = '"""'
        end_marker = '"""'
        start = diary.find(start_marker) + len(start_marker)
        end = diary.find(end_marker, start)
        if start != -1 and end != -1:
            return diary[start:end].strip()
        return ""

    async def generate_diary(self, group_id: str = "", topic: str | None = None) -> str | None:
        """根据聊天记录 + 人设 + 当天时间/天气生成日记文本"""
        # 如果配置了 diary_provider_id 则使用，否则使用默认提供商
        provider = None
        if self.diary_provider_id:
            provider = self.context.get_provider_by_id(self.diary_provider_id)
        if not provider:
            provider = self.context.get_using_provider()
        if not isinstance(provider, Provider):
            logger.error("未配置用于文本生成任务的 LLM 提供商")
            return None
        contexts = []

        if group_id:
            contexts = await self._get_msg_contexts(group_id)
        else:  # 随机获取一个群组
            group_list = await self.client.get_group_list()
            group_ids = [
                str(group["group_id"])
                for group in group_list
                if str(group["group_id"]) not in self.config["ignore_groups"]
            ]
            if not group_ids:
                logger.warning("未找到可用群组")
                return None
            contexts = await self._get_msg_contexts(random.choice(group_ids))
        # TODO: 更多模式
        
        # 人设 + 当天时间/天气
        persona_profile = ""
        try:
            persona_mgr = self.context.persona_manager
            default_persona = await persona_mgr.get_default_persona_v3()
            persona_profile = default_persona["prompt"] or ""
        except Exception:
            persona_profile = ""
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        weekday = "一二三四五六日"[now.weekday()]
        weather_desc = await self._get_weather_desc()
        
        life_header = [
            f"今天是 {today_str}（星期{weekday}）。",
            "你要以第一人称写一篇简短的“今天的 QQ 空间说说/日记”，",
            "内容要贴近真实人类生活，有起床、上班/上课、吃饭、娱乐、睡前等片段，不要提到自己是 AI。",
        ]
        if persona_profile:
            life_header.append(f"以下是你的角色设定，请保持一致：{persona_profile}")
        if weather_desc:
            life_header.append(f"你所在城市的天气概况：{weather_desc}")
        life_header_text = "\n".join(life_header) + "\n\n"
        
        # 系统提示，要求使用三对双引号包裹正文
        system_prompt = (
            life_header_text
            + f"# 写作主题：{topic or '从聊天内容中选一个与今天生活相关的主题'}\n\n"
            "# 输出格式要求：\n"
            '- 使用三对双引号（""")将正文内容包裹起来。\n\n'
            + self.config["diary_prompt"]
        )
        
        logger.debug(f"{system_prompt}\n\n{contexts}")

        try:
            llm_response = await provider.text_chat(
                system_prompt=system_prompt,
                contexts=contexts,
            )
            diary = self.extract_content(llm_response.completion_text)
            logger.info(f"LLM 生成的日记：{diary}")
            return diary

        except Exception as e:
            raise ValueError(f"LLM 调用失败：{e}")

    async def generate_comment(self, post: Post) -> str | None:
        """根据帖子内容生成评论"""
        # 如果配置了 comment_provider_id 则使用，否则使用默认提供商
        provider = None
        if self.comment_provider_id:
            provider = self.context.get_provider_by_id(self.comment_provider_id)
        if not provider:
            provider = self.context.get_using_provider()
        if not isinstance(provider, Provider):
            logger.error("未配置用于文本生成任务的 LLM 提供商")
            return None
        try:
            content = post.text
            if post.rt_con:  # 转发文本
                content += f"\n[转发]\n{post.rt_con}"

            prompt = f"\n[帖子内容]：\n{content}"

            logger.debug(prompt)
            llm_response = await provider.text_chat(
                system_prompt=self.config["comment_prompt"],
                prompt=prompt,
                image_urls=post.images,
            )
            comment = re.sub(r"[\s\u3000]+", "", llm_response.completion_text).rstrip(
                "。"
            )
            logger.info(f"LLM 生成的评论：{comment}")
            return comment

        except Exception as e:
            raise ValueError(f"LLM 调用失败：{e}")

    async def generate_image_prompt_from_diary(self, diary: str) -> str | None:
        """让大模型根据日记和生活状态生成画图提示词"""
        # 如果配置了 diary_provider_id 则使用，否则使用默认提供商
        provider = None
        if self.diary_provider_id:
            provider = self.context.get_provider_by_id(self.diary_provider_id)
        if not provider:
            provider = self.context.get_using_provider()
        if not isinstance(provider, Provider):
            logger.error("未配置用于文本生成任务的 LLM 提供商")
            return None
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        weekday = "一二三四五六日"[now.weekday()]
        weather_desc = await self._get_weather_desc()
        system_prompt = [
            "你现在的任务是：根据给定的【今天的 QQ 空间日记】和生活背景，生成一条用于文生图的图片提示词。",
            "画面应当是真实人类的一天中的某个生活场景，可以是上班路上、教室里、咖啡馆、自习室、在家看书、晚上散步等。",
            "请避免出现聊天窗口、对话气泡、电脑屏幕特写等“AI 对话”画面，也不要出现“AI”“机器人”等字样。",
            "只描述画面中的人物、场景、光线、构图和氛围，可以适当补充环境细节。",
            "输出一段简洁但信息丰富的中文提示词（可以适当带一些英文风格词汇），不要分点，不要解释。",
            f"今天是 {today_str}（星期{weekday}）。",
        ]
        if weather_desc:
            system_prompt.append(f"天气情况：{weather_desc}。可以考虑天气对场景的影响。")
        full_system_prompt = "\n".join(system_prompt)
        try:
            resp = await provider.text_chat(
                system_prompt=full_system_prompt,
                prompt=f"今天的日记内容如下：\n{diary}",
            )
            prompt_text = (resp.completion_text or "").strip()
            logger.info(f"LLM 生成的配图提示词：{prompt_text}")
            return prompt_text
        except Exception as e:
            raise ValueError(f"LLM 生成配图提示词失败：{e}")
