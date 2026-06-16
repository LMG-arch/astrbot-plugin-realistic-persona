import asyncio
import json
import random
import re
from datetime import datetime

import aiohttp

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent

from .base import BaseManager


class ImageManager(BaseManager):
    """Manages AI image generation: ModelScope, OpenAI DALL-E, Aliyun, prompt enhancement."""

    # Prefix marker for draw failures — callers check this instead of
    # fragile keyword substring matching like "失败" / "错误".
    DRAW_FAIL_PREFIX = "__DRAW_FAIL__"

    @classmethod
    def is_draw_success(cls, result: str | None) -> bool:
        """Check if a draw_func result indicates success."""
        if not result:
            return False
        return not result.startswith(cls.DRAW_FAIL_PREFIX)

    async def request_modelscope(
        self, prompt: str, size: str, session: aiohttp.ClientSession
    ) -> str:
        """Send request to ModelScope API."""
        common_headers = {
            "Authorization": f"Bearer {self.state.api_key}",
            "Content-Type": "application/json",
        }

        current_seed = random.randint(1, 2147483647)
        payload = {
            "model": self.state.model,
            "prompt": prompt,
            "seed": current_seed,
            "size": size,
            "steps": 30,
        }

        async with session.post(
            f"{self.state.api_url}v1/images/generations",
            headers={**common_headers, "X-ModelScope-Async-Mode": "true"},
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            timeout=aiohttp.ClientTimeout(total=30),
        ) as response:
            response.raise_for_status()
            task_response = await response.json()
            task_id = task_response.get("task_id")

            if not task_id:
                raise Exception("未能获取任务ID，生成图片失败。")

        delay = 1
        max_delay = 10
        max_retries = 30
        retry_count = 0
        while retry_count < max_retries:
            retry_count += 1
            async with session.get(
                f"{self.state.api_url}v1/tasks/{task_id}",
                headers={
                    **common_headers,
                    "X-ModelScope-Task-Type": "image_generation",
                },
            ) as result_response:
                result_response.raise_for_status()
                data = await result_response.json()

                task_status = data.get("task_status")
                if task_status == "SUCCEED":
                    output_images = data.get("output_images", [])
                    if output_images:
                        return output_images[0]
                    else:
                        raise Exception("图片生成成功但未返回图片URL。")
                elif task_status == "FAILED":
                    raise Exception("图片生成失败。")

                await asyncio.sleep(delay)
                delay = min(delay * 2, max_delay)
        raise Exception("图片生成超时：轮询超过最大重试次数")

    async def request_image_with_fallback(self, prompt: str, size: str = "") -> str:
        """Call image generation API with multi-platform support and auto-switching."""
        primary_provider = self.config.get("provider", "ms")
        backup_providers = self.config.get("backup_providers", ["openai", "aliyun"])

        if not size:
            size = self.state.size if hasattr(self.state, "size") else "1024x1024"

        all_providers = [primary_provider] + [
            p for p in backup_providers if p != primary_provider
        ]

        logger.info(f"[绘图] 尝试平台列表: {all_providers}，主平台: {primary_provider}")

        last_error = None
        for provider in all_providers:
            try:
                logger.info(f"[绘图] 尝试使用平台: {provider}")

                if provider.lower() in ["ms", "modelscope"]:
                    if not self.state.api_key:
                        logger.warning(f"[绘图] {provider} 平台未配置API密钥，跳过")
                        continue
                    async with aiohttp.ClientSession() as session:
                        return await self.request_modelscope(prompt, size, session)
                elif provider.lower() == "openai":
                    openai_api_key = self.config.get("openai_api_key", "")
                    if not openai_api_key:
                        logger.warning("[绘图] OpenAI 平台未配置API密钥，跳过")
                        continue
                    return await self.request_openai_dalle(prompt, size, openai_api_key)
                elif provider.lower() == "aliyun":
                    aliyun_api_key = self.config.get("aliyun_api_key", "")
                    if not aliyun_api_key:
                        logger.warning("[绘图] 阿里云平台未配置API密钥，跳过")
                        continue
                    return await self.request_aliyun(prompt, size, aliyun_api_key)
                else:
                    logger.warning(f"[绘图] 不支持的平台: {provider}，跳过")
                    continue

            except Exception as e:
                logger.warning(f"[绘图] {provider} 平台调用失败: {e}")
                last_error = e
                continue

        if last_error:
            logger.error(f"[绘图] 所有绘图平台都失败了，最后错误: {last_error}")
            raise Exception(f"所有绘图平台都失败了: {last_error}")
        else:
            raise Exception("没有配置任何绘图平台")

    async def request_openai_dalle(self, prompt: str, size: str, api_key: str) -> str:
        """Call OpenAI DALL-E to generate image."""
        # Parse size dimensions and map to nearest supported DALL-E size
        supported_sizes = {"256x256", "512x512", "1024x1024"}
        if size in supported_sizes:
            openai_size = size
        else:
            try:
                w, h = size.lower().split("x", 1)
                max_dim = max(int(w), int(h))
            except (ValueError, AttributeError):
                max_dim = 1024
            if max_dim <= 256:
                openai_size = "256x256"
            elif max_dim <= 512:
                openai_size = "512x512"
            else:
                openai_size = "1024x1024"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        openai_model = self.config.get("openai_model", "dall-e-3")

        payload = {
            "model": openai_model,
            "prompt": prompt,
            "n": 1,
            "size": openai_size,
        }

        openai_api_url = self.config.get("openai_api_url", "https://api.openai.com/v1")
        url = f"{openai_api_url}/images/generations"
        logger.debug(f"[OpenAI DALL-E] 请求URL: {url.split('?')[0]}")

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                resp_text = await resp.text()
                logger.info(f"[OpenAI DALL-E] 响应状态: {resp.status}")

                if resp.status != 200:
                    logger.error(f"[OpenAI DALL-E] API调用失败: HTTP {resp.status}")
                    raise Exception(
                        f"OpenAI DALL-E API调用失败: HTTP {resp.status}, {resp_text[:200]}"
                    )

                try:
                    data = json.loads(resp_text)
                except json.JSONDecodeError as e:
                    raise Exception(f"OpenAI DALL-E 响应解析失败: {e}")

        if "data" not in data or not data["data"]:
            raise Exception("OpenAI DALL-E 未返回图片数据")

        image_url = data["data"][0].get("url")
        if not image_url:
            raise Exception("OpenAI DALL-E 未返回图片 URL")

        return image_url

    async def request_aliyun(self, prompt: str, size: str, api_key: str) -> str:
        """Call Aliyun Tongyi Wanxiang to generate image."""
        ali_size = size.replace("x", "*")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        aliyun_model = self.config.get("aliyun_model", "wanx-v1")

        payload = {
            "model": aliyun_model,
            "input": {
                "prompt": prompt,
                "size": ali_size,
            },
            "parameters": {
                "n": 1,
            },
        }

        aliyun_api_url = self.config.get(
            "aliyun_api_url", "https://dashscope.aliyuncs.com/api/v1"
        )
        url = f"{aliyun_api_url}/services/aigc/text2image"

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                resp_text = await resp.text()
                logger.info(f"[阿里云通义万相] 响应状态: {resp.status}")

                if resp.status != 200:
                    raise Exception(
                        f"阿里云通义万相 API调用失败: HTTP {resp.status}, {resp_text[:200]}"
                    )

                try:
                    data = json.loads(resp_text)
                except json.JSONDecodeError as e:
                    raise Exception(f"阿里云通义万相 响应解析失败: {e}")

        if (
            "output" not in data
            or "results" not in data["output"]
            or not data["output"]["results"]
        ):
            raise Exception("阿里云通义万相 未返回图片数据")

        image_url = data["output"]["results"][0].get("url")
        if not image_url:
            raise Exception("阿里云通义万相 未返回图片 URL")

        return image_url

    async def request_image(self, prompt: str, size: str) -> str:
        """Request image generation based on configured provider."""
        try:
            if not prompt:
                raise ValueError("请提供提示词！")
            return await self.request_image_with_fallback(prompt, size)
        except aiohttp.ClientError as e:
            raise Exception(f"网络请求失败: {str(e)}")
        except json.JSONDecodeError as e:
            raise Exception(f"解析API响应失败: {str(e)}")
        except Exception as e:
            raise e

    async def enhance_drawing_prompt(
        self,
        original_prompt: str,
        event: AstrMessageEvent | None = None,
        life_manager=None,
        emotion_manager=None,
    ) -> str:
        """Use LLM to generate context-aware drawing prompt, with fallback."""
        try:
            now = datetime.now()

            persona_profile = await self.state.get_persona_profile()
            if not persona_profile:
                if life_manager:
                    persona_profile = await life_manager.get_system_persona_profile()

            schedule_text = ""
            outfit = ""
            if life_manager:
                schedule_text = await life_manager.maybe_generate_schedule(now)
                if schedule_text:
                    for line in schedule_text.split("\n"):
                        line_clean = line.strip().lstrip("0123456789.、·-").strip()
                        line_clean = (
                            line_clean.replace("**", "").replace("*", "").strip()
                        )
                        if "穿搭" in line_clean or "穿着" in line_clean:
                            for prefix in (
                                "今日穿搭：",
                                "穿搭：",
                                "穿着：",
                                "今日穿搭:",
                                "穿搭:",
                                "穿着:",
                            ):
                                if prefix in line_clean:
                                    outfit = line_clean.split(prefix, 1)[1].strip()
                                    break
                            if not outfit and (
                                "穿搭" in line_clean or "穿着" in line_clean
                            ):
                                for sep in ("：", ":", "，"):
                                    if sep in line_clean:
                                        outfit = line_clean.split(sep, 1)[1].strip()
                                        break
                            if outfit:
                                break

            raw_weather = ""
            weather_desc = ""
            if life_manager:
                raw_weather = await life_manager.get_weather_desc()
                weather_desc = life_manager.parse_weather_for_drawing(raw_weather)

            emotion_desc = ""
            if event:
                try:
                    session_id = event.get_session_id()
                    emotion_analysis = self.state.context_state.get_state(
                        session_id, "emotion_analysis"
                    )
                    if emotion_analysis and emotion_analysis.get("emotion"):
                        em = emotion_analysis["emotion"]
                        emotion_desc = (
                            str(em.value) if hasattr(em, "value") else str(em)
                        )
                except Exception:
                    pass

            recent_conv = ""
            try:
                if self.state.experience_bank:
                    convs = self.state.experience_bank.get_recent_conversations(limit=5)
                    if convs:
                        conv_items = []
                        for c in convs[-3:]:
                            user_msg = c.get("user_message", "")[:80]
                            if user_msg:
                                conv_items.append(f"用户: {user_msg}")
                        if conv_items:
                            recent_conv = "；".join(conv_items)
            except Exception as e:
                logger.debug(f"[绘图提示词生成] 获取最近对话失败: {e}")

            drawing_history = ""
            try:
                recent_prompts = (
                    self.state.local_data_manager.get_recent_drawing_prompts(
                        days=2, max_count=3
                    )
                )
                if recent_prompts:
                    history_items = [
                        item.get("original_prompt", "")[:50]
                        for item in recent_prompts
                        if item.get("original_prompt")
                    ]
                    if history_items:
                        drawing_history = "；".join(history_items)
            except Exception as e:
                logger.debug(f"[绘图提示词生成] 获取历史绘画失败: {e}")

            hour = now.hour
            if 5 <= hour < 8:
                time_desc = "清晨"
            elif 8 <= hour < 12:
                time_desc = "上午"
            elif 12 <= hour < 14:
                time_desc = "中午"
            elif 14 <= hour < 18:
                time_desc = "下午"
            elif 18 <= hour < 20:
                time_desc = "傍晚"
            elif 20 <= hour < 22:
                time_desc = "夜晚"
            else:
                time_desc = "深夜"

            forbidden_rules = self.config.get("image_forbidden_rules", "").strip()

            current_schedule = ""
            if life_manager:
                current_schedule = life_manager.get_current_period_schedule(
                    schedule_text, now
                )

            provider_id = self.state.get_provider_id()
            if provider_id and self.context and hasattr(self.context, "llm_generate"):
                logger.info(
                    "[绘图提示词生成] ✅ LLM可用，使用LLM生成上下文感知提示词..."
                )
                meta_prompt = (
                    f"你是一个专业的AI绘图提示词生成器。根据以下上下文信息，将用户的绘图请求转化为一段详细的、"
                    f"适合AI图片生成模型的英文提示词。\n\n"
                    f"## 用户绘图请求\n{original_prompt[:500]}\n\n"
                    f"## 角色人设\n{persona_profile[:500] if persona_profile else '未配置'}\n\n"
                    f"## 今日穿搭\n{outfit if outfit else '未指定'}\n\n"
                    f"## 当前时段活动\n{current_schedule if current_schedule else '无'}\n\n"
                    f"## 天气情况\n{weather_desc if weather_desc else '未知'}\n\n"
                    f"## 当前时间\n{time_desc}\n\n"
                    f"## 情绪状态\n{emotion_desc if emotion_desc else '未知'}\n\n"
                    f"## 最近对话\n{recent_conv if recent_conv else '无'}\n\n"
                    f"## 历史绘画（避免重复）\n{drawing_history if drawing_history else '无'}\n\n"
                    f"## 禁止规则\n{forbidden_rules if forbidden_rules else '无'}\n\n"
                    f"## 要求\n"
                    f"1. 提示词必须是英文\n"
                    f"2. 必须包含人物外貌、穿搭、场景、时间、光线、风格等细节\n"
                    f"3. 确保人物形象与人设一致\n"
                    f"4. 穿搭信息要与今日穿搭匹配\n"
                    f"5. 场景氛围要与天气和时间一致\n"
                    f"6. 结合当前时段活动描述场景\n"
                    f"7. 严格遵守所有禁止规则\n"
                    f"8. 避免与历史绘画重复\n"
                    f"9. 只输出提示词本身，不要有任何解释或前缀\n\n"
                    f"英文提示词："
                )

                try:
                    resp = await self.context.llm_generate(
                        chat_provider_id=provider_id,
                        prompt=meta_prompt,
                    )
                    generated = (resp.completion_text or "").strip()
                    if generated:
                        generated = generated.strip("`").strip()
                        for prefix in (
                            "Prompt:",
                            "prompt:",
                            "PROMPT:",
                            "English prompt:",
                        ):
                            if generated.startswith(prefix):
                                generated = generated[len(prefix) :].strip()
                        logger.info(
                            f"[绘图提示词生成] ✅ LLM成功生成提示词: {generated[:100]}..."
                        )
                        try:
                            self.state.local_data_manager.save_drawing_prompt(
                                original_prompt, generated
                            )
                        except Exception as e:
                            logger.debug(f"[绘图提示词生成] 保存失败: {e}")
                        return generated
                    else:
                        logger.warning("[绘图提示词生成] LLM返回空结果，回退到拼接方式")
                except Exception as e:
                    logger.warning(f"[绘图提示词生成] LLM生成失败，回退到拼接方式: {e}")

            logger.info(
                "[绘图提示词生成] ⚠️ LLM不可用或未配置provider，使用关键词拼接方式生成提示词"
            )
            return self.build_drawing_prompt_fallback(
                original_prompt,
                persona_profile=persona_profile,
                outfit=outfit,
                weather_desc=weather_desc,
                time_desc=time_desc,
                forbidden_rules=forbidden_rules,
                conversation_context=recent_conv,
                drawing_history=drawing_history,
            )

        except Exception as e:
            logger.error(f"[绘图提示词生成] 失败: {e}", exc_info=True)
            return original_prompt

    def build_drawing_prompt_fallback(
        self,
        original_prompt: str,
        persona_profile: str = "",
        outfit: str = "",
        weather_desc: str = "",
        time_desc: str = "",
        forbidden_rules: str = "",
        conversation_context: str = "",
        drawing_history: str = "",
    ) -> str:
        """Fallback drawing prompt generation via keyword concatenation."""
        enhanced_parts = [f"画面内容：{original_prompt}"]

        if persona_profile:
            age_match = re.search(r"(\d+)岁", persona_profile)
            gender_hints = []
            if "女" in persona_profile or "她" in persona_profile:
                gender_hints.append("女性")
            elif "男" in persona_profile or "他" in persona_profile:
                gender_hints.append("男性")
            appearance_desc = ""
            if age_match:
                appearance_desc += f"{age_match.group(1)}岁"
            if gender_hints:
                appearance_desc += gender_hints[0]
            if appearance_desc:
                enhanced_parts.append(f"人物：{appearance_desc}")

        if outfit:
            enhanced_parts.append(f"穿着：{outfit}")
        if weather_desc:
            enhanced_parts.append(f"天气：{weather_desc}")

        time_light_map = {
            "清晨": "清晨，柔和的晨光",
            "上午": "上午，明亮的日光",
            "中午": "中午，强烈的阳光",
            "下午": "下午，温暖的光线",
            "傍晚": "傍晚，金色的夕阳",
            "夜晚": "夜晚，柔和的灯光",
            "深夜": "深夜，昏暗的光线",
        }
        enhanced_parts.append(
            f"时间：{time_light_map.get(time_desc, '白天，自然光线')}"
        )

        style_desc = "风格：真实摄影风格，自然光线，高清细节"
        if forbidden_rules:
            style_desc += "。" + forbidden_rules
        enhanced_parts.append(style_desc)

        if conversation_context:
            enhanced_parts.append(f"背景：{conversation_context}")
        if drawing_history:
            enhanced_parts.append(f"参考：{drawing_history}")

        enhanced_prompt = "，".join(enhanced_parts)
        logger.info(f"[绘图提示词回退] 拼接: {enhanced_prompt[:100]}...")
        return enhanced_prompt

    async def detect_and_handle_image_generation(
        self, text: str, event: AstrMessageEvent, draw_func=None
    ) -> bool:
        """Detect LLM response image generation content and auto-invoke drawing tool."""
        if not self.state.enable_image_generation_detection:
            logger.debug("[图像生成检测] 图像生成检测功能已禁用，跳过检测")
            return False

        logger.info(f"[图像生成检测] 检测响应文本: {text[:200]}...")

        json_pattern = r'(\{[^{}]*"action"\s*:\s*"[^"]*(?:generate_image|image|draw|picture|photo|绘画|图片|照片|绘图)[^"]*"[^{}]*\})'
        matches = re.findall(json_pattern, text, re.IGNORECASE | re.DOTALL)

        logger.info(f"[图像生成检测] 找到 {len(matches)} 个JSON匹配项")

        for match in matches:
            try:
                json_obj = json.loads(match)
                logger.info(f"[图像生成检测] 解析JSON: {json_obj}")

                if isinstance(json_obj, dict):
                    action = json_obj.get("action", "").lower()
                    logger.info(f"[图像生成检测] 检查动作: {action}")
                    if (
                        "generate_image" in action
                        or "image" in action
                        or "draw" in action
                    ):
                        logger.info(f"[图像生成检测] 检测到图像生成JSON: {json_obj}")

                        action_input = json_obj.get("action_input", "")
                        if action_input:
                            if isinstance(action_input, str):
                                try:
                                    input_obj = json.loads(action_input)
                                    prompt = input_obj.get(
                                        "prompt", input_obj.get("description", "")
                                    )
                                    size = input_obj.get(
                                        "aspect_ratio",
                                        input_obj.get("size", "1024x1024"),
                                    )
                                except json.JSONDecodeError:
                                    prompt = action_input
                                    size = "1024x1024"
                            else:
                                prompt = action_input.get(
                                    "prompt", action_input.get("description", "")
                                )
                                size = action_input.get(
                                    "aspect_ratio",
                                    action_input.get("size", "1024x1024"),
                                )
                        else:
                            prompt = json_obj.get(
                                "prompt", json_obj.get("description", "")
                            )
                            size = json_obj.get(
                                "aspect_ratio", json_obj.get("size", "1024x1024")
                            )

                        if prompt and draw_func:
                            logger.info(
                                f"[图像生成检测] 提取到提示词: {prompt[:100]}..."
                            )
                            try:
                                result = await draw_func(event, prompt, size)
                                if self.is_draw_success(result):
                                    logger.info("[图像生成检测] 自动调用绘图工具成功")
                                    return True
                                else:
                                    logger.warning(
                                        f"[图像生成检测] 自动调用绘图工具失败: {result}"
                                    )
                            except Exception as e:
                                logger.error(
                                    f"[图像生成检测] 自动调用绘图工具时出错: {e}",
                                    exc_info=True,
                                )

            except json.JSONDecodeError:
                logger.warning(f"[图像生成检测] JSON解析失败: {match[:100]}...")
                continue

        image_keywords = [
            "生成图片",
            "画一张",
            "画个",
            "画一幅",
            "制作图片",
            "绘图",
            "生成图像",
            "画出来",
            "图片生成",
            "图像生成",
        ]
        for keyword in image_keywords:
            if keyword in text:
                logger.info(f"[图像生成检测] 检测到图像生成关键词: {keyword}")
                prompt_pattern = f"{re.escape(keyword)}[：:：:]?\\s*([^。！？\n]+)"
                prompt_match = re.search(prompt_pattern, text, re.DOTALL)
                if prompt_match:
                    prompt = prompt_match.group(1).strip()
                    if prompt and draw_func:
                        logger.info(
                            f"[图像生成检测] 提取到非JSON格式提示词: {prompt[:100]}..."
                        )
                        try:
                            result = await draw_func(event, prompt, "1024x1024")
                            if self.is_draw_success(result):
                                logger.info("[图像生成检测] 自动调用绘图工具成功")
                                return True
                            else:
                                logger.warning(
                                    f"[图像生成检测] 自动调用绘图工具失败: {result}"
                                )
                        except Exception as e:
                            logger.error(
                                f"[图像生成检测] 自动调用绘图工具时出错: {e}",
                                exc_info=True,
                            )

        multiline_json_pattern = (
            r"""\{\s*["']action["']\s*:\s*["']generate_image["'].*?\}"""
        )
        multiline_matches = re.findall(
            multiline_json_pattern, text, re.IGNORECASE | re.DOTALL
        )

        logger.info(f"[图像生成检测] 找到 {len(multiline_matches)} 个多行JSON匹配项")

        for match in multiline_matches:
            try:
                json_obj = json.loads(match)
                logger.info(f"[图像生成检测] 解析多行JSON: {json_obj}")
                if isinstance(json_obj, dict):
                    action = json_obj.get("action", "").lower()
                    if "generate_image" in action:
                        action_input = json_obj.get("action_input", "")
                        if isinstance(action_input, str):
                            try:
                                input_obj = json.loads(action_input)
                                prompt = input_obj.get(
                                    "prompt", input_obj.get("description", "")
                                )
                                size = input_obj.get(
                                    "aspect_ratio", input_obj.get("size", "1024x1024")
                                )
                            except json.JSONDecodeError:
                                prompt = action_input
                                size = "1024x1024"
                        else:
                            prompt = action_input.get(
                                "prompt", action_input.get("description", "")
                            )
                            size = action_input.get(
                                "aspect_ratio", action_input.get("size", "1024x1024")
                            )

                        if prompt and draw_func:
                            logger.info(
                                f"[图像生成检测] 从多行JSON提取到提示词: {prompt[:100]}..."
                            )
                            try:
                                result = await draw_func(event, prompt, size)
                                if self.is_draw_success(result):
                                    logger.info("[图像生成检测] 自动调用绘图工具成功")
                                    return True
                                else:
                                    logger.warning(
                                        f"[图像生成检测] 自动调用绘图工具失败: {result}"
                                    )
                            except Exception as e:
                                logger.error(
                                    f"[图像生成检测] 自动调用绘图工具时出错: {e}",
                                    exc_info=True,
                                )
            except json.JSONDecodeError:
                logger.warning(f"[图像生成检测] 多行JSON解析失败: {match[:100]}...")
                continue

        return False
