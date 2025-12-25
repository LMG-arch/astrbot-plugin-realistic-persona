# -*- coding: utf-8 -*-
"""
基于情绪的个人资料管理器
自动根据情绪状态修改 QQ 昵称、签名和头像
"""
import time
import random
import asyncio
import aiohttp
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from pathlib import Path
import json

from astrbot.api import logger
from astrbot.core.provider.provider import Provider
from astrbot.core.star.context import Context
from ..emotions import EmotionType


class ProfileManager:
    """基于情绪的个人资料管理器"""
    
    def __init__(self, context: Context, config: Dict[str, Any], data_dir: Path):
        """
        初始化个人资料管理器
        
        Args:
            context: AstrBot 上下文
            config: 插件配置
            data_dir: 数据目录
        """
        self.context = context
        self.config = config
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # 状态文件
        self.profile_state_file = self.data_dir / "profile_state.json"
        
        # 当前状态
        self.current_nickname = ""
        self.current_signature = ""
        self.last_update_time = 0
        self.emotion_history = []  # 记录最近的情绪变化
        
        # 配置参数
        self.enable_auto_nickname = config.get("enable_auto_nickname", False)
        self.enable_auto_signature = config.get("enable_auto_signature", True)
        self.enable_auto_avatar = config.get("enable_auto_avatar", False)
        self.update_cooldown = config.get("profile_update_cooldown", 1800)  # 30分钟冷却
        self.emotion_threshold = config.get("emotion_change_threshold", 0.6)  # 情绪变化阈值
        
        # AI绘图配置
        self.api_key = config.get("api_key")
        self.model = config.get("model", "iic/sdxl-turbo")
        self.api_url = config.get("api_url", "https://api.modelscope.com/api/")
        self.avatar_size = "1024x1024"  # 头像固定使用方形尺寸
        
        # 头像保存目录
        self.avatar_dir = self.data_dir / "avatars"
        self.avatar_dir.mkdir(parents=True, exist_ok=True)
        
        # 加载状态
        self._load_state()
        
        logger.info("[个人资料管理器] 初始化完成")
    
    def _load_state(self):
        """加载状态"""
        try:
            if self.profile_state_file.exists():
                with open(self.profile_state_file, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                    self.current_nickname = state.get("current_nickname", "")
                    self.current_signature = state.get("current_signature", "")
                    self.last_update_time = state.get("last_update_time", 0)
                    self.emotion_history = state.get("emotion_history", [])
        except Exception as e:
            logger.error(f"[个人资料管理器] 加载状态失败: {e}")
    
    def _save_state(self):
        """保存状态"""
        try:
            state = {
                "current_nickname": self.current_nickname,
                "current_signature": self.current_signature,
                "last_update_time": self.last_update_time,
                "emotion_history": self.emotion_history[-20:]  # 只保留最近20条
            }
            with open(self.profile_state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[个人资料管理器] 保存状态失败: {e}")
    
    def record_emotion(self, emotion: EmotionType, intensity: float = 1.0):
        """
        记录情绪变化
        
        Args:
            emotion: 情绪类型
            intensity: 情绪强度 (0-1)
        """
        self.emotion_history.append({
            "emotion": emotion.value,
            "intensity": intensity,
            "timestamp": time.time()
        })
        
        # 只保留最近1小时的记录
        cutoff_time = time.time() - 3600
        self.emotion_history = [
            e for e in self.emotion_history 
            if e["timestamp"] > cutoff_time
        ]
    
    def should_update_profile(self) -> bool:
        """
        判断是否应该更新个人资料
        
        Returns:
            是否应该更新
        """
        # 检查冷却时间
        if time.time() - self.last_update_time < self.update_cooldown:
            logger.debug(f"[个人资料管理器] 冷却中，距离下次更新还需 {int(self.update_cooldown - (time.time() - self.last_update_time))} 秒")
            return False
        
        # 检查情绪变化程度
        if len(self.emotion_history) < 2:
            return False
        
        # 计算最近5分钟内的情绪波动
        recent_cutoff = time.time() - 300  # 最近5分钟
        recent_emotions = [
            e for e in self.emotion_history 
            if e["timestamp"] > recent_cutoff
        ]
        
        if len(recent_emotions) < 2:
            return False
        
        # 检查是否有强烈情绪或情绪波动大
        emotions_set = set(e["emotion"] for e in recent_emotions)
        avg_intensity = sum(e["intensity"] for e in recent_emotions) / len(recent_emotions)
        
        # 情绪种类多样或强度高
        if len(emotions_set) >= 3 or avg_intensity >= self.emotion_threshold:
            logger.info(f"[个人资料管理器] 检测到情绪波动，准备更新个人资料")
            return True
        
        return False
    
    async def generate_nickname_and_signature(
        self,
        current_emotion: Optional[EmotionType] = None,
        persona_profile: Optional[str] = None
    ) -> Dict[str, str]:
        """
        使用 LLM 生成基于情绪的昵称和签名
        
        Args:
            current_emotion: 当前主要情绪
            persona_profile: 人设描述
        
        Returns:
            包含 nickname 和 signature 的字典
        """
        provider = self.context.get_using_provider()
        if not isinstance(provider, Provider):
            logger.error("[个人资料管理器] 未找到可用的 LLM 提供商")
            return {"nickname": "", "signature": ""}
        
        try:
            # 分析最近的情绪趋势
            emotion_summary = self._summarize_emotions()
            
            # 构建提示词
            system_prompt = [
                "你现在需要根据当前的情绪状态生成一个合适的 QQ 昵称和个性签名。",
                "要求：",
                "1. 昵称：简短（2-8个字），贴合当前情绪，有个性但不夸张",
                "2. 签名：15-30字，表达当前心情或想法，真实自然",
                "3. 风格：符合真实人类的表达习惯，不要AI腔，不要过于文艺",
                "4. 保持与人设一致",
            ]
            
            if persona_profile:
                system_prompt.append(f"\n你的人设：{persona_profile}")
            
            system_prompt.append(f"\n当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
            system_prompt.append(f"\n情绪分析：{emotion_summary}")
            
            if current_emotion:
                system_prompt.append(f"\n当前主要情绪：{current_emotion.value}")
            
            system_prompt.append("\n\n请以JSON格式输出，格式如下：")
            system_prompt.append('{"nickname": "昵称内容", "signature": "签名内容"}')
            
            full_system_prompt = "\n".join(system_prompt)
            
            logger.debug(f"[个人资料管理器] 生成提示词: {full_system_prompt}")
            
            response = await provider.text_chat(
                system_prompt=full_system_prompt,
                prompt="请生成昵称和签名"
            )
            
            # 解析 JSON
            result_text = response.completion_text.strip()
            
            # 尝试提取 JSON
            import re
            json_match = re.search(r'\{[^}]*"nickname"[^}]*"signature"[^}]*\}', result_text)
            if json_match:
                result = json.loads(json_match.group())
                nickname = result.get("nickname", "")
                signature = result.get("signature", "")
                
                logger.info(f"[个人资料管理器] LLM 生成结果 - 昵称: {nickname}, 签名: {signature}")
                return {"nickname": nickname, "signature": signature}
            else:
                logger.warning(f"[个人资料管理器] 无法解析 LLM 响应: {result_text}")
                return {"nickname": "", "signature": ""}
                
        except Exception as e:
            logger.error(f"[个人资料管理器] 生成昵称和签名失败: {e}")
            return {"nickname": "", "signature": ""}
    
    def _summarize_emotions(self) -> str:
        """总结最近的情绪趋势"""
        if not self.emotion_history:
            return "情绪平稳"
        
        recent = self.emotion_history[-10:]  # 最近10条
        
        emotion_counts = {}
        total_intensity = 0
        
        for e in recent:
            emotion = e["emotion"]
            intensity = e["intensity"]
            emotion_counts[emotion] = emotion_counts.get(emotion, 0) + 1
            total_intensity += intensity
        
        avg_intensity = total_intensity / len(recent)
        
        # 找出主要情绪
        if emotion_counts:
            main_emotion = max(emotion_counts, key=lambda k: emotion_counts.get(k, 0))
        else:
            main_emotion = "平静"
        
        # 构建摘要
        if avg_intensity > 0.7:
            intensity_desc = "情绪波动较大"
        elif avg_intensity > 0.4:
            intensity_desc = "情绪有所起伏"
        else:
            intensity_desc = "情绪相对平稳"
        
        summary = f"最近主要情绪是{main_emotion}，{intensity_desc}"
        
        if len(emotion_counts) > 2:
            summary += "，情绪变化多样"
        
        return summary
    
    async def generate_avatar_image(
        self,
        current_emotion: Optional[EmotionType] = None,
        persona_profile: Optional[str] = None
    ) -> Optional[str]:
        """
        使用 LLM 和绘画工具生成基于情绪的头像
        
        Args:
            current_emotion: 当前主要情绪
            persona_profile: 人设描述
        
        Returns:
            生成的图片 URL，失败返回 None
        """
        if not self.api_key:
            logger.warning("[个人资料管理器] API密钥未配置，无法生成头像")
            return None
        
        try:
            # 构建头像生成提示词
            emotion_desc_map = {
                EmotionType.EXCITED: "兴奋激动、精神饱满",
                EmotionType.HAPPY: "开心愉悦、笑容灿烂",
                EmotionType.SAD: "难过忧伤、略显沮丧",
                EmotionType.ANGRY: "生气愤怒、表情严肃",
                EmotionType.SURPRISED: "惊讶意外、眼睛睁大",
                EmotionType.ANXIOUS: "焦虑担心、略显紧张",
                EmotionType.BORED: "无聊乏味、慵懒疲倦",
                EmotionType.CONFUSED: "困惑疑惑、若有所思",
                EmotionType.CURIOUS: "好奇探索、眼神明亮",
                EmotionType.CALM: "平静自然、表情淡然"
            }
            
            emotion_desc = emotion_desc_map.get(current_emotion, "自然真实") if current_emotion else "自然真实"
            
            # 构建提示词
            prompt_parts = []
            
            # 基础描述
            if persona_profile and len(persona_profile) < 200:
                prompt_parts.append(persona_profile[:100])  # 取人设前100字
            else:
                prompt_parts.append("一个真实的人")
            
            # 情绪描述
            prompt_parts.append(f"表情{emotion_desc}")
            
            # 风格要求
            prompt_parts.append("真人自拍照片，高清画质，自然光线，日常装扮，社交头像风格")
            
            full_prompt = "，".join(prompt_parts)
            
            logger.info(f"[个人资料管理器] 生成头像提示词: {full_prompt}")
            
            # 调用绘图 API
            image_url = await self._request_image(full_prompt, self.avatar_size)
            
            if image_url:
                logger.info(f"[个人资料管理器] 头像生成成功: {image_url}")
                return image_url
            else:
                logger.warning("[个人资料管理器] 头像生成失败，未获取到图片URL")
                return None
                
        except Exception as e:
            logger.error(f"[个人资料管理器] 生成头像失败: {e}")
            return None
    
    async def _request_image(self, prompt: str, size: str = "1024x1024") -> Optional[str]:
        """
        请求 ModelScope API 生成图片
        
        Args:
            prompt: 提示词
            size: 图片尺寸
        
        Returns:
            图片 URL，失败返回 None
        """
        try:
            async with aiohttp.ClientSession() as session:
                common_headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                }
                
                current_seed = random.randint(1, 2147483647)
                payload = {
                    "model": f"{self.model}",
                    "prompt": prompt,
                    "seed": current_seed,
                    "size": size,
                    "num_inference_steps": "30",
                }
                
                # 提交任务
                async with session.post(
                    f"{self.api_url}v1/images/generations",
                    headers={**common_headers, "X-ModelScope-Async-Mode": "true"},
                    data=json.dumps(payload, ensure_ascii=False).encode('utf-8')
                ) as response:
                    response.raise_for_status()
                    task_response = await response.json()
                    task_id = task_response.get("task_id")
                    
                    if not task_id:
                        logger.error("[个人资料管理器] 未能获取任务ID")
                        return None
                
                # 轮询结果（最多等待60秒）
                delay = 1
                max_delay = 10
                total_wait = 0
                max_total_wait = 60
                
                while total_wait < max_total_wait:
                    await asyncio.sleep(delay)
                    total_wait += delay
                    
                    async with session.get(
                        f"{self.api_url}v1/tasks/{task_id}",
                        headers={**common_headers, "X-ModelScope-Task-Type": "image_generation"},
                    ) as result_response:
                        result_response.raise_for_status()
                        data = await result_response.json()
                        
                        task_status = data.get("task_status")
                        
                        if task_status == "SUCCEEDED":
                            results = data.get("results", [])
                            if results and len(results) > 0:
                                image_url = results[0].get("url")
                                if image_url:
                                    return image_url
                            logger.warning("[个人资料管理器] 任务成功但未获取到图片URL")
                            return None
                        elif task_status == "FAILED":
                            logger.error(f"[个人资料管理器] 图片生成任务失败: {data.get('message')}")
                            return None
                        
                        # 继续等待
                        delay = min(delay * 1.5, max_delay)
                
                logger.warning("[个人资料管理器] 图片生成超时")
                return None
                
        except Exception as e:
            logger.error(f"[个人资料管理器] 请求图片生成失败: {e}")
            return None
    
    async def update_qq_profile(
        self, 
        bot, 
        nickname: Optional[str] = None,
        signature: Optional[str] = None,
        avatar_url: Optional[str] = None
    ) -> bool:
        """
        更新 QQ 个人资料
        
        Args:
            bot: aiocqhttp bot 实例
            nickname: 新昵称（可选）
            signature: 新签名（可选）
            avatar_url: 新头像URL（可选）
        
        Returns:
            是否成功更新
        """
        success = False
        
        try:
            # 更新昵称
            if nickname and self.enable_auto_nickname:
                await bot.set_qq_profile(nickname=nickname)
                self.current_nickname = nickname
                logger.info(f"[个人资料管理器] 昵称已更新: {nickname}")
                success = True
            
            # 更新签名
            if signature and self.enable_auto_signature:
                await bot.set_self_longnick(longNick=signature)
                self.current_signature = signature
                logger.info(f"[个人资料管理器] 签名已更新: {signature}")
                success = True
            
            # 更新头像
            if avatar_url and self.enable_auto_avatar:
                await bot.set_qq_avatar(file=avatar_url)
                logger.info(f"[个人资料管理器] 头像已更新: {avatar_url}")
                success = True
            
            if success:
                self.last_update_time = time.time()
                self._save_state()
            
            return success
            
        except Exception as e:
            logger.error(f"[个人资料管理器] 更新 QQ 资料失败: {e}")
            return False
    
    async def auto_update_on_emotion_change(
        self,
        bot,
        current_emotion: EmotionType,
        intensity: float = 1.0,
        persona_profile: Optional[str] = None
    ) -> bool:
        """
        根据情绪变化自动更新个人资料（包括昵称、签名和头像）
        
        Args:
            bot: aiocqhttp bot 实例
            current_emotion: 当前情绪
            intensity: 情绪强度
            persona_profile: 人设描述
        
        Returns:
            是否成功更新
        """
        # 记录情绪
        self.record_emotion(current_emotion, intensity)
        
        # 检查是否应该更新
        if not self.should_update_profile():
            return False
        
        # 生成新的昵称和签名
        result = await self.generate_nickname_and_signature(
            current_emotion=current_emotion,
            persona_profile=persona_profile
        )
        
        # 生成新的头像（如果启用）
        avatar_url = None
        if self.enable_auto_avatar:
            logger.info("[个人资料管理器] 开始生成基于情绪的头像...")
            avatar_url = await self.generate_avatar_image(
                current_emotion=current_emotion,
                persona_profile=persona_profile
            )
            if not avatar_url:
                logger.warning("[个人资料管理器] 头像生成失败，将只更新昵称和签名")
        
        # 至少有一项内容才执行更新
        if not result.get("nickname") and not result.get("signature") and not avatar_url:
            logger.warning("[个人资料管理器] 所有生成内容为空，跳过更新")
            return False
        
        # 更新 QQ 资料
        return await self.update_qq_profile(
            bot=bot,
            nickname=result.get("nickname"),
            signature=result.get("signature"),
            avatar_url=avatar_url
        )
    
    async def auto_update_on_thinking(
        self,
        bot,
        thought_content: str,
        emotion_detected: Optional[EmotionType] = None,
        persona_profile: Optional[str] = None
    ) -> bool:
        """
        在异步思考过程中根据思考内容自动更新
        
        Args:
            bot: aiocqhttp bot 实例
            thought_content: 思考内容
            emotion_detected: 从思考中检测到的情绪
            persona_profile: 人设描述
        
        Returns:
            是否成功更新
        """
        if not emotion_detected:
            return False
        
        # 假设思考中的强烈情绪强度较高
        return await self.auto_update_on_emotion_change(
            bot=bot,
            current_emotion=emotion_detected,
            intensity=0.8,
            persona_profile=persona_profile
        )
