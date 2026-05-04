import asyncio
import json
import random
import re
from datetime import datetime
from typing import Any

import aiohttp
from aiocqhttp import CQHttp

from astrbot.api import logger
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.provider.provider import Provider
from astrbot.core.star.context import Context
from astrbot.core.star.star_tools import StarTools

from .post import Post


class LLMAction:
    def __init__(self, context: Context, config: AstrBotConfig, client: CQHttp):
        self.context = context
        self.config = config
        self.client = client
        # 使用 get 方法获取可选配置，默认为 None
        self.comment_provider_id = self.config.get("comment_provider_id")
        self.diary_provider_id = self.config.get("diary_provider_id")
        self.async_think_provider_id = self.config.get("async_think_provider_id", "")

        # ModelScope 生图配置
        self.ms_api_key: str | None = self.config.get("api_key")
        self.ms_api_url: str = self.config.get(
            "api_url",
            "https://api.modelscope.com/api/",
        )
        self.ms_model: str = self.config.get("ms_model", "iic/sdxl-turbo")
        self.ms_size: str = self.config.get("size", "1080x1920")
        self.weather_location: str = self.config.get("weather_location", "")

    async def _request_image_with_fallback(
        self, prompt: str, size: str | None = None
    ) -> str:
        """调用图片生成API，支持多平台和自动切换

        Args:
            prompt: 图片生成提示词
            size: 图片尺寸

        Returns:
            本地图片路径

        Raises:
            ValueError: 当所有平台都失败时
        """
        # 获取配置的主平台和备用平台
        primary_provider = self.config.get("provider", "ms")
        backup_providers = self.config.get("backup_providers", ["openai", "aliyun"])

        # 构建平台列表（主平台优先）
        all_providers = [primary_provider] + [
            p for p in backup_providers if p != primary_provider
        ]

        logger.info(f"[绘图] 尝试平台列表: {all_providers}，主平台: {primary_provider}")

        last_error = None
        for provider in all_providers:
            try:
                logger.info(f"[绘图] 尝试使用平台: {provider}")

                if provider in ["ms", "modelscope"]:
                    # ModelScope 平台
                    if not self.ms_api_key:
                        logger.warning(f"[绘图] {provider} 平台未配置API密钥，跳过")
                        continue
                    return await self._request_modelscope(prompt, size)
                elif provider == "openai":
                    # OpenAI 平台
                    openai_api_key = self.config.get("openai_api_key", "")
                    if not openai_api_key:
                        logger.warning("[绘图] OpenAI 平台未配置API密钥，跳过")
                        continue
                    return await self._request_openai_dalle(prompt, size)
                elif provider == "aliyun":
                    # 阿里云平台
                    aliyun_api_key = self.config.get("aliyun_api_key", "")
                    if not aliyun_api_key:
                        logger.warning("[绘图] 阿里云平台未配置API密钥，跳过")
                        continue
                    return await self._request_aliyun(prompt, size)
                else:
                    logger.warning(f"[绘图] 不支持的平台: {provider}，跳过")
                    continue

            except Exception as e:
                logger.warning(f"[绘图] {provider} 平台调用失败: {e}")
                last_error = e
                continue  # 尝试下一个平台

        # 如果所有平台都失败了
        if last_error:
            logger.error(f"[绘图] 所有绘图平台都失败了，最后错误: {last_error}")
            raise ValueError(f"所有绘图平台都失败了: {last_error}")
        else:
            raise ValueError("没有配置任何绘图平台")

    async def _request_modelscope(self, prompt: str, size: str | None = None) -> str:
        """调用 ModelScope 文生图，下载并保存到本地，返回本地路径"""
        if not self.ms_api_key:
            raise ValueError("未配置 ms_api_key，无法使用 ModelScope 生图")
        size = size or self.ms_size
        headers = {
            "Authorization": f"Bearer {self.ms_api_key}",
            "Content-Type": "application/json",
            "X-ModelScope-Async-Mode": "true",
        }
        payload = {
            "model": self.ms_model,
            "prompt": prompt,
            "size": size,
        }

        url = f"{self.ms_api_url}v1/images/generations"
        logger.info(f"[ModelScope] 请求URL: {url}")
        logger.info(
            f"[ModelScope] 请求参数: model={self.ms_model}, size={size}, prompt={prompt[:50]}..."
        )

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                headers=headers,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            ) as resp:
                resp_text = await resp.text()
                logger.info(f"[ModelScope] 响应状态: {resp.status}")
                logger.info(f"[ModelScope] 响应内容: {resp_text[:1000]}...")

                if resp.status != 200:
                    logger.error(f"[ModelScope] API调用失败: HTTP {resp.status}")
                    logger.error(f"[ModelScope] 错误详情: {resp_text}")
                    raise ValueError(
                        f"ModelScope API调用失败: HTTP {resp.status}, {resp_text[:200]}"
                    )

                try:
                    data = json.loads(resp_text)
                    logger.info(f"[ModelScope] 解析后的数据键: {list(data.keys())}")
                except json.JSONDecodeError as e:
                    logger.error(f"[ModelScope] 响应解析失败: {e}")
                    raise ValueError(f"ModelScope 响应解析失败: {e}")

        # 兼容多种返回格式
        image_url = None

        # 格式1: {"images": [{"url": "..."}]} (Tongyi-MAI/Z-Image-Turbo)
        if "images" in data and data["images"]:
            if isinstance(data["images"], list) and len(data["images"]) > 0:
                first_image = data["images"][0]
                if isinstance(first_image, dict) and "url" in first_image:
                    image_url = first_image["url"]
                    logger.info(
                        f"[ModelScope] 同步返回图片URL (格式1): {image_url[:50]}..."
                    )
                elif isinstance(first_image, str):
                    image_url = first_image
                    logger.info(
                        f"[ModelScope] 同步返回图片URL (格式1字符串): {image_url[:50]}..."
                    )

        # 格式2: {"output_images": ["..."]} (旧版格式)
        elif "output_images" in data and data["output_images"]:
            image_url = data["output_images"][0]
            logger.info(f"[ModelScope] 同步返回图片URL (格式2): {image_url[:50]}...")

        # 格式3: 异步任务 {"task_id": "..."}
        elif "task_id" in data:
            task_id = data["task_id"]
            logger.info(f"[ModelScope] 异步任务ID: {task_id}")
            delay = 1
            max_retries = 30
            retry_count = 0
            while retry_count < max_retries:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"{self.ms_api_url}v1/tasks/{task_id}",
                        headers={
                            "Authorization": f"Bearer {self.ms_api_key}",
                            "Content-Type": "application/json",
                            "X-ModelScope-Task-Type": "image_generation",
                        },
                    ) as r2:
                        if r2.status == 200:
                            tdata = await r2.json()
                            task_status = tdata.get("task_status")
                            logger.debug(f"[ModelScope] 任务状态: {task_status}")

                            if task_status == "SUCCEED":
                                imgs = tdata.get("output_images", [])
                                if imgs:
                                    image_url = imgs[0]
                                    logger.info(
                                        f"[ModelScope] 任务成功，图片URL: {image_url[:50]}..."
                                    )
                                break
                            elif task_status == "FAILED":
                                error_msg = tdata.get("error", "未知错误")
                                logger.error(f"[ModelScope] 任务失败: {error_msg}")
                                break
                        else:
                            logger.warning(
                                f"[ModelScope] 查询任务状态失败: HTTP {r2.status}"
                            )

                await asyncio.sleep(delay)
                delay = min(delay * 2, 10)
                retry_count += 1

            if retry_count >= max_retries:
                logger.error(f"[ModelScope] 任务超时，重试{max_retries}次后仍未完成")

        if not image_url:
            logger.error("[ModelScope] 未找到图片URL")
            logger.error(
                f"[ModelScope] 完整响应数据: {json.dumps(data, ensure_ascii=False, indent=2)}"
            )
            raise ValueError("ModelScope 未返回图片 URL")

        # 下载图片到本地
        local_path = await self._download_image(image_url)
        logger.info(f"[ModelScope] 生成的图片已保存到: {local_path}")
        return local_path

    async def _download_image(self, url: str) -> str:
        """下载图片到本地，返回本地路径"""
        # 创建images目录
        images_dir = (
            StarTools.get_data_dir("astrbot_plugin_realistic_persona") / "images"
        )
        images_dir.mkdir(parents=True, exist_ok=True)

        # 生成文件名（使用时间戳）
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"generated_{timestamp}.png"
        local_path = images_dir / filename

        # 下载图片
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                resp.raise_for_status()
                content = await resp.read()
                with open(local_path, "wb") as f:
                    f.write(content)

        return str(local_path)

    async def _request_openai_dalle(self, prompt: str, size: str | None = None) -> str:
        """调用 OpenAI DALL-E 生成图片"""
        openai_api_key = self.config.get("openai_api_key", "")
        openai_api_url = self.config.get("openai_api_url", "https://api.openai.com/v1")

        if not openai_api_key:
            raise ValueError("未配置 openai_api_key，无法使用 OpenAI DALL-E 生图")

        # 将尺寸转换为 OpenAI 支持的格式
        size = size or self.ms_size
        # OpenAI DALL-E 支持 256x256, 512x512, 1024x1024
        # 将其他尺寸映射到最接近的 OpenAI 支持的尺寸
        if "256" in size:
            openai_size = "256x256"
        elif "512" in size:
            openai_size = "512x512"
        elif "1024" in size:
            openai_size = "1024x1024"
        else:
            # 默认使用 1024x1024
            openai_size = "1024x1024"

        headers = {
            "Authorization": f"Bearer {openai_api_key}",
            "Content-Type": "application/json",
        }

        # 获取模型配置
        openai_model = self.config.get("openai_model", "dall-e-3")

        # 构建请求数据
        payload = {
            "model": openai_model,  # 从配置获取模型
            "prompt": prompt,
            "n": 1,
            "size": openai_size,
        }

        url = f"{openai_api_url}/images/generations"
        logger.info(f"[OpenAI DALL-E] 请求URL: {url}")
        logger.info(
            f"[OpenAI DALL-E] 请求参数: size={openai_size}, prompt={prompt[:50]}..."
        )

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                resp_text = await resp.text()
                logger.info(f"[OpenAI DALL-E] 响应状态: {resp.status}")
                logger.info(f"[OpenAI DALL-E] 响应内容: {resp_text[:1000]}...")

                if resp.status != 200:
                    logger.error(f"[OpenAI DALL-E] API调用失败: HTTP {resp.status}")
                    logger.error(f"[OpenAI DALL-E] 错误详情: {resp_text}")
                    raise ValueError(
                        f"OpenAI DALL-E API调用失败: HTTP {resp.status}, {resp_text[:200]}"
                    )

                try:
                    data = json.loads(resp_text)
                except json.JSONDecodeError as e:
                    logger.error(f"[OpenAI DALL-E] 响应解析失败: {e}")
                    raise ValueError(f"OpenAI DALL-E 响应解析失败: {e}")

        # 从响应中提取图片URL
        if "data" not in data or not data["data"]:
            logger.error("[OpenAI DALL-E] 未找到图片数据")
            logger.error(
                f"[OpenAI DALL-E] 完整响应数据: {json.dumps(data, ensure_ascii=False, indent=2)}"
            )
            raise ValueError("OpenAI DALL-E 未返回图片数据")

        image_url = data["data"][0].get("url")
        if not image_url:
            logger.error("[OpenAI DALL-E] 未找到图片URL")
            logger.error(
                f"[OpenAI DALL-E] 完整响应数据: {json.dumps(data, ensure_ascii=False, indent=2)}"
            )
            raise ValueError("OpenAI DALL-E 未返回图片 URL")

        # 下载图片到本地
        local_path = await self._download_image(image_url)
        logger.info(f"[OpenAI DALL-E] 生成的图片已保存到: {local_path}")
        return local_path

    async def _request_aliyun(self, prompt: str, size: str | None = None) -> str:
        """调用阿里云通义万相生成图片"""
        aliyun_api_key = self.config.get("aliyun_api_key", "")
        aliyun_api_url = self.config.get(
            "aliyun_api_url", "https://dashscope.aliyuncs.com/api/v1"
        )

        if not aliyun_api_key:
            raise ValueError("未配置 aliyun_api_key，无法使用阿里云通义万相生图")

        size = size or self.ms_size
        # 阿里云支持的尺寸格式，如 "1024*1024"
        # 将标准格式转换为阿里云格式
        ali_size = size.replace("x", "*")

        headers = {
            "Authorization": f"Bearer {aliyun_api_key}",
            "Content-Type": "application/json",
        }

        # 获取模型配置
        aliyun_model = self.config.get("aliyun_model", "wanx-v1")

        # 构建请求数据
        payload = {
            "model": aliyun_model,  # 从配置获取模型
            "input": {
                "prompt": prompt,
                "size": ali_size,
            },
            "parameters": {
                "n": 1,
            },
        }

        url = f"{aliyun_api_url}/services/aigc/text2image"
        logger.info(f"[阿里云通义万相] 请求URL: {url}")
        logger.info(
            f"[阿里云通义万相] 请求参数: size={ali_size}, prompt={prompt[:50]}..."
        )

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                resp_text = await resp.text()
                logger.info(f"[阿里云通义万相] 响应状态: {resp.status}")
                logger.info(f"[阿里云通义万相] 响应内容: {resp_text[:1000]}...")

                if resp.status != 200:
                    logger.error(f"[阿里云通义万相] API调用失败: HTTP {resp.status}")
                    logger.error(f"[阿里云通义万相] 错误详情: {resp_text}")
                    raise ValueError(
                        f"阿里云通义万相 API调用失败: HTTP {resp.status}, {resp_text[:200]}"
                    )

                try:
                    data = json.loads(resp_text)
                except json.JSONDecodeError as e:
                    logger.error(f"[阿里云通义万相] 响应解析失败: {e}")
                    raise ValueError(f"阿里云通义万相 响应解析失败: {e}")

        # 从响应中提取图片URL
        if (
            "output" not in data
            or "results" not in data["output"]
            or not data["output"]["results"]
        ):
            logger.error("[阿里云通义万相] 未找到图片数据")
            logger.error(
                f"[阿里云通义万相] 完整响应数据: {json.dumps(data, ensure_ascii=False, indent=2)}"
            )
            raise ValueError("阿里云通义万相 未返回图片数据")

        image_url = data["output"]["results"][0].get("url")
        if not image_url:
            logger.error("[阿里云通义万相] 未找到图片URL")
            logger.error(
                f"[阿里云通义万相] 完整响应数据: {json.dumps(data, ensure_ascii=False, indent=2)}"
            )
            raise ValueError("阿里云通义万相 未返回图片 URL")

        # 下载图片到本地
        local_path = await self._download_image(image_url)
        logger.info(f"[阿里云通义万相] 生成的图片已保存到: {local_path}")
        return local_path

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

    async def _get_private_msg_contexts(
        self, user_id: str, max_count: int = 100
    ) -> list[dict]:
        """
        获取与指定用户的私聊历史消息

        Args:
            user_id: 用户QQ号
            max_count: 最多获取消息条数

        Returns:
            对话上下文列表
        """
        try:
            contexts: list[dict] = []
            message_seq = 0

            while len(contexts) < max_count:
                payloads = {
                    "user_id": user_id,
                    "message_seq": message_seq,
                    "count": 100,  # 每次获取100条
                }

                result: dict = await self.client.api.call_action(
                    "get_friend_msg_history", **payloads
                )

                if not result or "messages" not in result:
                    logger.debug(f"获取用户 {user_id} 的私聊历史失败")
                    break

                round_messages = result["messages"]
                if not round_messages:
                    break

                message_seq = round_messages[-1].get("message_id", 0)
                contexts.extend(self._build_context(round_messages))

                # 如果返回的消息少于100条，说明已经没有更多了
                if len(round_messages) < 100:
                    break

            logger.info(f"从用户 {user_id} 获取了 {len(contexts)} 条私聊消息")
            return contexts[:max_count]  # 限制最大数量

        except Exception as e:
            logger.error(f"获取私聊历史失败: {e}")
            return []

    async def _get_msg_contexts(
        self, group_id: str, max_count: int | None = None
    ) -> list[dict]:
        """获取群聊历史消息

        Args:
            group_id: 群号
            max_count: 最多获取消息条数，如果为None则使用配置值
        """
        message_seq = 0
        contexts: list[dict] = []
        diary_max_msg = max_count or self.config.get("diary_max_msg", 100)
        while len(contexts) < diary_max_msg:
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
        """提取三对双引号之间的内容，如果没有则返回原始内容"""
        if not diary:
            return ""

        start_marker = '"""'
        end_marker = '"""'
        start = diary.find(start_marker)
        if start == -1:
            # 没有找到开始标记，返回原始内容
            logger.debug("extract_content: 未找到三对双引号，返回原始内容")
            return diary.strip()

        start += len(start_marker)
        end = diary.find(end_marker, start)
        if end == -1:
            # 没有找到结束标记，返回原始内容
            logger.debug("extract_content: 未找到结束的三对双引号，返回原始内容")
            return diary.strip()

        content = diary[start:end].strip()
        if not content:
            # 提取的内容为空，返回原始内容
            logger.debug("extract_content: 提取内容为空，返回原始内容")
            return diary.strip()

        return content

    async def _compress_contexts(
        self,
        contexts: list[dict[str, str]],
        max_rounds: int | None = None,
        compression_threshold: int | None = None,
    ) -> list[dict[str, str]]:
        """压缩对话历史上下文，减少token使用

        Args:
            contexts: 原始对话上下文列表
            max_rounds: 最大对话轮数，超出部分将被丢弃（保留最新的）
            compression_threshold: 压缩阈值（字符数），超过此值时进行压缩

        Returns:
            压缩后的对话上下文列表
        """
        if not contexts:
            return contexts

        # 从配置获取默认值
        if max_rounds is None:
            max_rounds = self.config.get("history_max_rounds", 10)
        if compression_threshold is None:
            compression_threshold = self.config.get(
                "history_compression_threshold", 2000
            )

        # 首先检查是否超过最大轮数限制
        if len(contexts) > max_rounds:
            # 保留最新的max_rounds轮对话
            contexts = contexts[-max_rounds:]
            logger.debug(
                f"[历史压缩] 超过最大轮数限制({max_rounds})，保留最新的{len(contexts)}轮对话"
            )

        # 检查总字符数是否超过压缩阈值
        total_chars = sum(len(ctx.get("content", "")) for ctx in contexts)
        if total_chars <= compression_threshold:
            logger.debug(
                f"[历史压缩] 总字符数({total_chars})未超过压缩阈值({compression_threshold})，无需压缩"
            )
            return contexts

        logger.info(
            f"[历史压缩] 总字符数({total_chars})超过压缩阈值({compression_threshold})，开始压缩"
        )

        # 检查是否启用了压缩功能
        if not self.config.get("enable_history_compression", True):
            logger.info("[历史压缩] 压缩功能已禁用，返回原始上下文")
            return contexts

        # 进行压缩 - 保留重要信息，精简内容
        compressed_contexts = []
        for ctx in contexts:
            role = ctx.get("role", "user")
            content = ctx.get("content", "")

            if len(content) <= 500:  # 如果内容已经很短，直接保留
                compressed_contexts.append({"role": role, "content": content})
                continue

            # 对长内容进行摘要
            try:
                compressed_content = await self._summarize_content(content)
                compressed_contexts.append(
                    {"role": role, "content": compressed_content}
                )
                logger.debug(
                    f"[历史压缩] 压缩内容: {len(content)} -> {len(compressed_content)} 字符"
                )
            except Exception as e:
                logger.warning(f"[历史压缩] 压缩失败，使用原始内容: {e}")
                # 如果压缩失败，截取前面的部分
                truncated_content = content[:500] + "..."
                compressed_contexts.append({"role": role, "content": truncated_content})
                logger.debug(f"[历史压缩] 使用截取内容: {len(truncated_content)} 字符")

        return compressed_contexts

    async def _summarize_content(self, content: str) -> str:
        """使用LLM对长内容进行摘要

        Args:
            content: 需要摘要的内容

        Returns:
            摘要后的内容
        """
        if len(content) <= 500:
            return content

        # 获取提供商
        provider = self.context.get_using_provider()
        if not isinstance(provider, Provider):
            logger.warning("未配置LLM提供商，无法进行内容摘要")
            # 简单截断
            return content[:500] + "..."

        # 构建摘要提示词
        system_prompt = "你是一个文本摘要助手。请将输入的对话内容精简为关键信息，保留主要内容和情感，输出长度控制在200字以内。只需输出摘要内容，不要添加任何解释。"
        prompt = f"请摘要以下内容：\n{content}"

        try:
            response = await provider.text_chat(
                system_prompt=system_prompt, prompt=prompt
            )
            summary = response.completion_text.strip()

            # 如果摘要太长，进一步截断
            if len(summary) > 500:
                summary = summary[:500] + "..."

            return summary
        except Exception as e:
            logger.warning(f"LLM摘要失败: {e}，使用截断方法")
            # 摘要失败时使用简单截断
            return content[:300] + "..."

    async def generate_diary(
        self,
        group_id: str = "",
        topic: str | None = None,
        persona_profile: str = "",
        user_id: str = "",
    ) -> str | None:
        """
        根据聊天记录 + 人设 + 当天时间/天气/日程生成日记文本

        Args:
            group_id: 群号，留空则随机选一个群
            topic: 主题，留空则由LLM自己选择
            persona_profile: 人设描述，优先使用传入的参数，留空则从系统获取
            user_id: 优先使用的用户ID，如果指定则从该用户的私聊历史生成，留空则从群聊读取
        """
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

        # 优先从指定用户的私聊获取对话历史
        if user_id and user_id.strip():
            logger.info(f"优先从用户 {user_id} 的私聊历史生成说说")
            diary_max_msg = self.config.get("diary_max_msg", 100)
            contexts = await self._get_private_msg_contexts(
                user_id, max_count=diary_max_msg
            )

            if not contexts:
                logger.warning(f"无法从用户 {user_id} 获取私聊历史，回退到群聊模式")
            else:
                logger.info(f"成功从用户 {user_id} 获取了 {len(contexts)} 条对话")

        # 如果没有指定用户或私聊历史为空，则从群聊获取
        if not contexts:
            if group_id:
                contexts = await self._get_msg_contexts(group_id)
            else:  # 随机获取一个群组
                group_list = await self.client.get_group_list()
                ignore_groups = self.config.get("ignore_groups", [])
                group_ids = [
                    str(group["group_id"])
                    for group in group_list
                    if str(group["group_id"]) not in ignore_groups
                ]
                if not group_ids:
                    logger.warning("未找到可用群组")
                    return None
                contexts = await self._get_msg_contexts(random.choice(group_ids))
        # TODO: 更多模式

        # 人设：优先使用传入的参数，其次从系统获取
        if not persona_profile or not persona_profile.strip():
            try:
                persona_mgr = self.context.persona_manager
                default_persona = await persona_mgr.get_default_persona_v3()
                persona_profile = default_persona.get("prompt", "")
            except Exception:
                persona_profile = ""
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        weekday = "一二三四五六日"[now.weekday()]
        weather_desc = await self._get_weather_desc()

        # 获取当天的日程安排
        schedule_text = ""
        try:
            from .local_data_manager import LocalDataManager

            data_dir = (
                self.context.get_data_dir("astrbot_plugin_realistic_persona")
                / "local_data"
            )
            data_mgr = LocalDataManager(data_dir)
            schedule_text = data_mgr.get_schedule_data(today_str)
            if schedule_text:
                logger.info("获取到当天日程安排")
            else:
                logger.info("未找到当天日程安排")
        except Exception as e:
            logger.warning(f"获取日程安排失败: {e}")

        life_header = [
            f"今天是 {today_str}（星期{weekday}）。",
            "你要以第一人称写一条简短的 QQ 空间说说，分享今天的某个生活片段或感受。",
            "重要：你就是这个角色，直接以第一人称输出说说内容，不要添加任何第三人称的描述、确认、解释或多余的话。",
            "内容要贴近真实人类生活，自然随意，不要提到自己是 AI。",
            "长度控制在 2-3 句话以内，每句话不超过 30 字。",
        ]
        if persona_profile:
            life_header.append(f"以下是你的角色设定，请保持一致：{persona_profile}")
        if weather_desc:
            life_header.append(f"你所在城市的天气概况：{weather_desc}")
        if schedule_text:
            life_header.append(
                f"你今天的日程安排：{schedule_text[:300]}..."
            )  # 限制长度避免提示词过长
            life_header.append(
                "请结合今天的日程安排和对话历史，生成相关的感慨或事件，不要直接复制对话内容，而是根据对话历史和日程安排生成相关的感受或经历。"
            )

        # 注入经历银行上下文：最近活动、成长轨迹
        if hasattr(self, "experience_bank") and self.experience_bank:
            try:
                growth = self.experience_bank.get_growth_summary()
                if growth:
                    skills = growth.get("skills", {})
                    if skills:
                        skill_list = []
                        for name, info in skills.items():
                            if isinstance(info, dict):
                                skill_list.append(f"{name}(Lv.{info.get('level', 1)})")
                            else:
                                skill_list.append(f"{name}(Lv.{info})")
                        life_header.append(f"你的技能：{', '.join(skill_list[:8])}")

                    interests = growth.get("interests", [])
                    if interests:
                        interest_names = [
                            i.get("item", str(i)) if isinstance(i, dict) else str(i)
                            for i in interests[:6]
                        ]
                        life_header.append(f"你的兴趣：{', '.join(interest_names)}")

                recent_convs = self.experience_bank.get_recent_conversations(limit=3)
                if recent_convs:
                    recent_topics = []
                    for conv in recent_convs:
                        msg = conv.get("user_message", "")
                        if msg:
                            recent_topics.append(msg[:40])
                    if recent_topics:
                        life_header.append(
                            f"最近的聊天话题：{'、'.join(recent_topics)}"
                        )
            except Exception as e:
                logger.debug(f"[日记生成] 获取经历银行上下文失败: {e}")

        # 注入人格演化上下文
        if hasattr(self, "personality_evolution") and self.personality_evolution:
            try:
                summary = self.personality_evolution.get_personality_summary()
                if summary:
                    phase = summary.get("current_phase", "stable")
                    phase_name = "稳定期" if phase == "stable" else "变化期"
                    expr = summary.get("expression_levels", {})
                    vocab = expr.get("vocabulary", 5)
                    humor = expr.get("humor", 5)
                    habits = summary.get("core_habits", [])
                    life_header.append(
                        f"你的表达风格（{phase_name}）：词汇水平{vocab}/10，幽默感{humor}/10"
                    )
                    if habits:
                        life_header.append(f"你的核心习惯：{', '.join(habits[:3])}")
            except Exception as e:
                logger.debug(f"[日记生成] 获取人格演化上下文失败: {e}")

        life_header_text = "\n".join(life_header) + "\n\n"

        # 系统提示，要求使用三对双引号包裹正文
        diary_prompt = self.config.get(
            "diary_prompt",
            "写作风格：\n"
            "- 用口语化、随意的语气，像朋友圈那样轻松\n"
            "- 可以包含 Emoji 表情增加生动性\n"
            "- 只写 2-3 句话，简洁明了\n"
            "- 不要长篇大论，不要流水账式的叙述\n"
            "- 可以是分享心情、小感慨、有趣的事、即时感受、思考、或者emo等\n"
            "\n示例：\n"
            "- “今天天气超好，在公园晒了一下午的太阳🌞”\n"
            "- “终于学会了那道难题，感觉自己还是挺聪明的呀😏”\n"
            "- “晚风很舒服，散步回家的路上看到了超美的晚霞✨”",
        )
        system_prompt = (
            life_header_text
            + f"# 写作主题：{topic or '从聊天内容和今日日程中选一个与今天生活相关的主题'}\n\n"
            "# 输出格式要求：\n"
            '- 使用三对双引号（"""）将正文内容包裹起来。\n\n' + diary_prompt
        )

        logger.debug(f"{system_prompt}\n\n{contexts}")

        try:
            # 应用历史压缩
            compressed_contexts = await self._compress_contexts(contexts)
            logger.debug(
                f"[历史压缩] 压缩前: {len(contexts)} 轮对话, 压缩后: {len(compressed_contexts)} 轮对话"
            )

            llm_response = await provider.text_chat(
                system_prompt=system_prompt,
                contexts=compressed_contexts,  # 使用压缩后的上下文
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
            comment_prompt = self.config.get(
                "comment_prompt", "请根据帖子内容生成一条简短的评论。"
            )
            llm_response = await provider.text_chat(
                system_prompt=comment_prompt,
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

    async def generate_thought(self, prompt: str) -> str | None:
        """让大模型根据提示生成一段思考或内心独白

        Args:
            prompt: 生成思考的提示词
        """
        # 优先使用async_think_provider_id，其次diary_provider_id，最后默认提供商
        provider = None
        if self.async_think_provider_id:
            provider = self.context.get_provider_by_id(self.async_think_provider_id)
        if not provider and self.diary_provider_id:
            provider = self.context.get_provider_by_id(self.diary_provider_id)
        if not provider:
            provider = self.context.get_using_provider()
        if not isinstance(provider, Provider):
            logger.error("未配置用于文本生成任务的 LLM 提供商")
            return None

        try:
            logger.debug(f"[思考生成] 请求提示: {prompt}")

            llm_response = await provider.text_chat(
                system_prompt="你是一个善于思考的助手。请根据给定的情境生成一段自然、真实的内心独白或思考。要求：1. 内容真实自然，像真人内心独白；2. 长度在15-50字之间；3. 体现给定情境的特点；4. 直接返回思考内容，不要添加其他解释或说明。",
                prompt=prompt,
            )
            thought = (llm_response.completion_text or "").strip()

            # 清理返回的内容，只保留思考部分
            # 如果包含多余的解释，只取第一行或去除多余的字符
            lines = thought.split("\n")
            thought = lines[0].strip()  # 取第一行

            # 去除可能的引号
            if thought.startswith('"') and thought.endswith('"'):
                thought = thought[1:-1]

            logger.info(f"[思考生成] 生成的思考：{thought}")
            return thought

        except Exception as e:
            logger.error(f"[思考生成] LLM调用失败：{e}")
            return None

    async def generate_activity(self, prompt: str) -> str | None:
        """让大模型根据提示生成一段日常活动描述

        Args:
            prompt: 生成活动的提示词
        """
        # 优先使用async_think_provider_id，其次diary_provider_id，最后默认提供商
        provider = None
        if self.async_think_provider_id:
            provider = self.context.get_provider_by_id(self.async_think_provider_id)
        if not provider and self.diary_provider_id:
            provider = self.context.get_provider_by_id(self.diary_provider_id)
        if not provider:
            provider = self.context.get_using_provider()
        if not isinstance(provider, Provider):
            logger.error("未配置用于文本生成任务的 LLM 提供商")
            return None

        try:
            logger.debug(f"[活动生成] 请求提示: {prompt}")

            llm_response = await provider.text_chat(
                system_prompt="你是一个正在度过日常生活的人。根据给定的情境，描述你此刻正在做的一件日常小事。要求：1.真实自然，贴近生活；2.长度10-30字；3.具体且有画面感；4.直接返回活动内容，不要添加解释。",
                prompt=prompt,
            )
            activity = (llm_response.completion_text or "").strip()

            # 清理返回的内容
            lines = activity.split("\n")
            activity = lines[0].strip()

            # 去除可能的引号
            if activity.startswith('"') and activity.endswith('"'):
                activity = activity[1:-1]

            logger.info(f"[活动生成] 生成的活动：{activity}")
            return activity

        except Exception as e:
            logger.error(f"[活动生成] LLM调用失败：{e}")
            return None

    async def generate_nickname(self, prompt: str) -> str | None:
        """让大模型根据提示生成一个合适的昵称

        Args:
            prompt: 生成昵称的提示词
        """
        # 如果配置了 diary_provider_id 则使用，否则使用默认提供商
        provider = None
        if self.diary_provider_id:
            provider = self.context.get_provider_by_id(self.diary_provider_id)
        if not provider:
            provider = self.context.get_using_provider()
        if not isinstance(provider, Provider):
            logger.error("未配置用于文本生成任务的 LLM 提供商")
            return None

        try:
            logger.debug(f"[昵称生成] 请求提示: {prompt}")

            llm_response = await provider.text_chat(
                system_prompt="你是一个昵称生成助手。请根据给定的信息生成一个合适的QQ昵称。要求：1. 昵称应该自然、真实，像真实用户会使用的昵称；2. 长度控制在2-10个字符；3. 不要包含特殊符号或表情；4. 直接返回昵称，不要包含其他解释或说明。",
                prompt=prompt,
            )
            nickname = (llm_response.completion_text or "").strip()

            # 清理返回的内容，只保留昵称部分
            # 如果包含多余的解释，只取第一行或去除多余的字符
            lines = nickname.split("\n")
            nickname = lines[0].strip()  # 取第一行

            # 去除可能的引号
            if nickname.startswith('"') and nickname.endswith('"'):
                nickname = nickname[1:-1]

            logger.info(f"[昵称生成] 生成的昵称：{nickname}")
            return nickname

        except Exception as e:
            logger.error(f"[昵称生成] LLM调用失败：{e}")
            return None

    async def generate_image_prompt_from_diary(
        self, diary: str, group_id: str = "", user_id: str = ""
    ) -> str | None:
        """让大模型根据日记和生活状态生成画图提示词

        Args:
            diary: 日记内容
            group_id: 群号，用于获取对话历史
            user_id: 用户ID，用于获取私聊历史
        """
        # 如果配置了 diary_provider_id 则使用，否则使用默认提供商
        provider = None
        if self.diary_provider_id:
            provider = self.context.get_provider_by_id(self.diary_provider_id)
        if not provider:
            provider = self.context.get_using_provider()
        if not isinstance(provider, Provider):
            logger.error("未配置用于文本生成任务的 LLM 提供商")
            return None

        # 获取对话历史作为上下文
        contexts = []
        try:
            if user_id and user_id.strip():
                # 从私聊获取
                logger.info(f"[绘画提示词生成] 尝试从用户 {user_id} 获取私聊历史")
                contexts = await self._get_private_msg_contexts(user_id, max_count=20)
                logger.info(
                    f"[绘画提示词生成] 从用户 {user_id} 获取了 {len(contexts)} 条对话"
                )
            elif group_id:
                # 从群聊获取
                logger.info(f"[绘画提示词生成] 尝试从群 {group_id} 获取群聊历史")
                contexts = await self._get_msg_contexts(group_id, max_count=20)
                logger.info(
                    f"[绘画提示词生成] 从群 {group_id} 获取了 {len(contexts)} 条对话"
                )
            else:
                logger.warning(
                    "[绘画提示词生成] user_id 和 group_id 都为空，无法获取对话历史"
                )
        except Exception as e:
            logger.error(f"[绘画提示词生成] 获取对话历史失败: {e}", exc_info=True)

        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        weekday = "一二三四五六日"[now.weekday()]
        weather_desc = await self._get_weather_desc()

        # 获取当天的日程信息（特别是穿着）
        schedule_text = ""
        outfit = ""
        try:
            # 尝试从缓存获取当天日程
            from .local_data_manager import LocalDataManager

            data_dir = (
                self.context.get_data_dir("astrbot_plugin_realistic_persona")
                / "local_data"
            )
            data_mgr = LocalDataManager(data_dir)
            schedule_text = data_mgr.get_schedule_data(today_str)

            if schedule_text:
                logger.info("[绘画提示词生成] 获取到当天日程")
                # 提取穿着信息
                lines = schedule_text.split("\n")
                for line in lines:
                    if "今日穿搭" in line or "穿搭" in line or "穿着" in line:
                        outfit = (
                            line.replace("今日穿搭：", "").replace("穿搭：", "").strip()
                        )
                        logger.info(f"[绘画提示词生成] 提取到穿着信息: {outfit}")
                        break
            else:
                logger.warning("[绘画提示词生成] 未找到当天日程")
        except Exception as e:
            logger.debug(f"[绘画提示词生成] 获取日程失败: {e}")

        system_prompt = [
            "你现在的任务是：根据给定的【今天的 QQ 空间日记】和生活背景，生成一条用于文生图的图片提示词。",
            "画面应当是真实人类的一天中的某个生活场景，可以是上班路上、教室里、咖啡馆、自习室、在家看书、晚上散步等。",
            "请避免出现聊天窗口、对话气泡、电脑屏幕特写等“AI 对话”画面，也不要出现“AI”“机器人”等字样。",
        ]

        # 从配置文件读取绘画禁止规则
        forbidden_rules = self.config.get("image_forbidden_rules", "").strip()
        if forbidden_rules:
            system_prompt.append(forbidden_rules)

        system_prompt.extend(
            [
                "只描述画面中的人物、场景、光线、构图和氛围，可以适当补充环境细节。",
                "输出一段简洁但信息丰富的中文提示词（可以适当带一些英文风格词汇），不要分点，不要解释。",
                f"今天是 {today_str}（星期{weekday}）。",
            ]
        )

        # 重要：如果有穿着信息，必须严格遵循
        if outfit:
            system_prompt.append(
                f"★重要：人物穿着必须为：{outfit}。这是今天的实际穿着，请严格遵循，不要更改。"
            )

        if weather_desc:
            system_prompt.append(
                f"天气情况：{weather_desc}。可以考虑天气对场景的影响。"
            )

        # 如果有日程信息，也加入参考
        if schedule_text:
            # 提取当前时间可能对应的活动
            current_hour = now.hour
            schedule_lines = schedule_text.split("\n")
            current_activity = None

            # 根据当前小时匹配日程中的活动
            for line in schedule_lines:
                if (
                    current_hour >= 6
                    and current_hour < 9
                    and ("早上" in line or "早餐" in line or "起床" in line)
                ):
                    current_activity = line
                    break
                elif (
                    current_hour >= 9
                    and current_hour < 12
                    and (
                        "上午" in line
                        or "工作" in line
                        or "上课" in line
                        or "学习" in line
                    )
                ):
                    current_activity = line
                    break
                elif (
                    current_hour >= 12
                    and current_hour < 14
                    and ("中午" in line or "午餐" in line or "午休" in line)
                ):
                    current_activity = line
                    break
                elif (
                    current_hour >= 14
                    and current_hour < 18
                    and (
                        "下午" in line
                        or "下午" in line
                        or "工作" in line
                        or "学习" in line
                    )
                ):
                    current_activity = line
                    break
                elif (
                    current_hour >= 18
                    and current_hour < 20
                    and ("傍晚" in line or "晚餐" in line or "晚上" in line)
                ):
                    current_activity = line
                    break
                elif (
                    current_hour >= 20
                    and current_hour < 23
                    and (
                        "晚上" in line
                        or "娱乐" in line
                        or "学习" in line
                        or "社交" in line
                    )
                ):
                    current_activity = line
                    break
                elif (
                    current_hour >= 23
                    or current_hour < 6
                    and ("睡前" in line or "睡觉" in line or "洗漱" in line)
                ):
                    current_activity = line
                    break

            if current_activity:
                system_prompt.append(
                    f"当前时间 {current_hour}:00 左右的活动安排：{current_activity}。请根据当前时间段的活动安排生成符合场景的图片。"
                )
            else:
                system_prompt.append(
                    f"今天的日程安排：{schedule_text[:200]}...。请根据日记内容和日程安排生成符合场景的图片。"
                )

        # 如果有对话历史，提示大模型参考
        if contexts:
            system_prompt.append(
                "可以参考下面的对话历史，了解当前情境和活动，只是参考最近的活动，不是现在的。"
            )

        full_system_prompt = "\n".join(system_prompt)
        try:
            # 应用历史压缩
            compressed_contexts = await self._compress_contexts(contexts)
            logger.debug(
                f"[历史压缩] 画图提示词生成 - 压缩前: {len(contexts)} 轮对话, 压缩后: {len(compressed_contexts)} 轮对话"
            )

            resp = await provider.text_chat(
                system_prompt=full_system_prompt,
                prompt=f"今天的日记内容如下：\n{diary}",
                contexts=compressed_contexts,  # 使用压缩后的对话历史
            )
            prompt_text = (resp.completion_text or "").strip()
            logger.info(f"LLM 生成的配图提示词：{prompt_text}")
            return prompt_text
        except Exception as e:
            raise ValueError(f"LLM 生成配图提示词失败：{e}")
