# -*- coding: utf-8 -*-
"""
人生故事引擎
基于原始人设，通过经历累积自动构建完整的人生经历线
定期使用LLM生成上下文优化提示，最小化token消耗同时保证高质量扮演
"""

import json
import asyncio
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime, timedelta
from collections import defaultdict

from astrbot.api import logger


class LifeStoryEngine:
    """人生故事引擎
    
    核心设计理念：
    1. 保持原始人设不变，只补充经历细节
    2. 构建完整的人生经历线（时间线、事件、成长）
    3. 动态生成最精简的上下文提示
    4. 优先保证扮演质量，其次优化token
    """
    
    def __init__(
        self,
        data_dir: Path,
        experience_bank=None,
        personality_evolution=None,
        thought_engine=None,
        update_interval: int = 86400 * 3,  # 默认3天更新一次经历线
        collect_days: int = 7,  # 收集最近N天的经历
        context_max_length: int = 200,  # 精简上下文最大长度
        cache_days: int = 7  # 缓存有效期（天）
    ):
        """初始化人生故事引擎
        
        Args:
            data_dir: 数据存储目录
            experience_bank: 经历银行实例
            personality_evolution: 人格演化管理器实例
            thought_engine: 思考引擎实例
            update_interval: 更新间隔（秒），默认3天
            collect_days: 收集最近N天的经历，默认7天
            context_max_length: 精简上下文最大长度，默认200字符
            cache_days: 缓存有效期（天），默认7天
        """
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.experience_bank = experience_bank
        self.personality_evolution = personality_evolution
        self.thought_engine = thought_engine
        self.update_interval = update_interval
        self.collect_days = collect_days
        self.context_max_length = context_max_length
        self.cache_days = cache_days
        
        # 核心数据文件
        self.life_story_file = self.data_dir / "life_story.json"  # 完整人生故事
        self.context_cache_file = self.data_dir / "context_cache.json"  # 上下文缓存
        self.state_file = self.data_dir / "engine_state.json"  # 引擎状态
        
        # 加载状态
        self.state = self._load_state()
        self.life_story = self._load_life_story()
        self.context_cache = self._load_context_cache()
        
        logger.info(f"[人生故事引擎] 初始化完成，更新间隔: {update_interval/86400}天")
    
    def _load_state(self) -> Dict:
        """加载引擎状态"""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"[人生故事引擎] 加载状态失败: {e}")
        
        return {
            "last_update_time": 0,
            "update_count": 0,
            "current_chapter": 1,  # 当前人生章节
            "base_persona": "",  # 原始人设（永不修改）
            "last_token_count": 0
        }
    
    def _save_state(self):
        """保存引擎状态"""
        try:
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[人生故事引擎] 保存状态失败: {e}")
    
    def _load_life_story(self) -> Dict:
        """加载人生故事"""
        if self.life_story_file.exists():
            try:
                with open(self.life_story_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"[人生故事引擎] 加载人生故事失败: {e}")
        
        return {
            "timeline": [],  # 时间线事件
            "key_experiences": [],  # 关键经历
            "relationships": {},  # 关系网络
            "growth_milestones": [],  # 成长里程碑
            "current_state": {}  # 当前状态
        }
    
    def _save_life_story(self):
        """保存人生故事"""
        try:
            with open(self.life_story_file, 'w', encoding='utf-8') as f:
                json.dump(self.life_story, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[人生故事引擎] 保存人生故事失败: {e}")
    
    def _load_context_cache(self) -> Dict:
        """加载上下文缓存"""
        if self.context_cache_file.exists():
            try:
                with open(self.context_cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"[人生故事引擎] 加载上下文缓存失败: {e}")
        
        return {
            "compact_context": "",  # 精简上下文
            "generated_at": 0,
            "cache_valid_until": 0
        }
    
    def _save_context_cache(self):
        """保存上下文缓存"""
        try:
            with open(self.context_cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.context_cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[人生故事引擎] 保存上下文缓存失败: {e}")
    
    def set_base_persona(self, persona: str):
        """设置基础人设（只在首次设置，之后永不修改）"""
        if not self.state.get("base_persona"):
            self.state["base_persona"] = persona
            self._save_state()
            logger.info("[人生故事引擎] 基础人设已设置")
        else:
            logger.debug("[人生故事引擎] 基础人设已存在，跳过设置")
    
    def should_update(self) -> bool:
        """检查是否应该更新经历线
        
        Returns:
            是否应该更新
        """
        last_time = self.state.get("last_update_time", 0)
        current_time = datetime.now().timestamp()
        
        if current_time - last_time < self.update_interval:
            remaining = int(self.update_interval - (current_time - last_time))
            hours = remaining / 3600
            logger.debug(f"[人生故事引擎] 距离下次更新还需 {hours:.1f} 小时")
            return False
        
        return True
    
    async def collect_recent_experiences(self, days: int = None) -> Dict:
        """收集最近的经历数据
        
        Args:
            days: 收集最近几天的数据，如果为None则使用配置的collect_days
            
        Returns:
            经历数据字典
        """
        if days is None:
            days = self.collect_days
        
        data = {
            "conversations": [],
            "thoughts": [],
            "events": [],
            "growth_changes": []
        }
        
        try:
            cutoff_time = datetime.now() - timedelta(days=days)
            
            # 从经历银行收集
            if self.experience_bank:
                # 收集对话
                conversations_file = self.experience_bank.conversations_file
                if conversations_file.exists():
                    with open(conversations_file, 'r', encoding='utf-8') as f:
                        for line in f:
                            if line.strip():
                                record = json.loads(line)
                                timestamp = datetime.fromisoformat(record.get("timestamp", ""))
                                if timestamp > cutoff_time:
                                    data["conversations"].append({
                                        "time": record.get("timestamp"),
                                        "user": record.get("user_id"),
                                        "topic": record.get("user_message", "")[:50]
                                    })
                
                # 收集事件
                events_file = self.experience_bank.events_file
                if events_file.exists():
                    with open(events_file, 'r', encoding='utf-8') as f:
                        for line in f:
                            if line.strip():
                                record = json.loads(line)
                                timestamp = datetime.fromisoformat(record.get("timestamp", ""))
                                if timestamp > cutoff_time:
                                    data["events"].append({
                                        "time": record.get("timestamp"),
                                        "type": record.get("event_type"),
                                        "desc": record.get("description", "")[:100]
                                    })
            
            # 从思考引擎收集
            if self.thought_engine:
                thoughts_file = self.thought_engine.thoughts_file
                if thoughts_file.exists():
                    with open(thoughts_file, 'r', encoding='utf-8') as f:
                        for line in f:
                            if line.strip():
                                record = json.loads(line)
                                timestamp = datetime.fromisoformat(record.get("timestamp", ""))
                                if timestamp > cutoff_time:
                                    data["thoughts"].append({
                                        "time": record.get("timestamp"),
                                        "content": record.get("content", "")
                                    })
            
            # 从人格演化系统收集成长变化
            if self.personality_evolution:
                self_awareness = self.personality_evolution.self_awareness
                if self_awareness:
                    # 检查最近的特质变化
                    traits = self_awareness.self_description.get("personality_traits", [])
                    interests = self_awareness.self_description.get("interests", [])
                    data["growth_changes"] = {
                        "current_traits": traits[:5],
                        "current_interests": interests[:5]
                    }
            
            logger.info(f"[人生故事引擎] 收集到 {len(data['conversations'])} 条对话, "
                       f"{len(data['thoughts'])} 条思考, {len(data['events'])} 个事件")
            
            return data
            
        except Exception as e:
            logger.error(f"[人生故事引擎] 收集经历失败: {e}", exc_info=True)
            return data
    
    async def update_life_story(self, llm_action) -> bool:
        """更新人生故事（补充经历线）
        
        Args:
            llm_action: LLMAction 实例，用于获取实际的LLM提供者
            
        Returns:
            是否更新成功
        """
        try:
            logger.info("[人生故事引擎] 开始更新人生经历线...")
            
            # 从LLMAction获取实际的LLM提供者
            if hasattr(llm_action, 'context'):
                provider = llm_action.context.get_using_provider()
                if not provider:
                    logger.error("[人生故事引擎] 无法获取LLM提供者")
                    return False
            else:
                logger.error("[人生故事引擎] LLMAction对象无效")
                return False
            
            # 收集最近的经历
            recent_data = await self.collect_recent_experiences()
            
            # 构建LLM提示词
            prompt = self._build_story_update_prompt(recent_data)
            
            # 调用LLM生成新的经历章节
            response = await provider.text_chat(
                prompt=prompt,
                system_prompt=self._get_story_system_prompt()
            )
            
            if response and hasattr(response, 'completion_text'):
                story_update = response.completion_text.strip()
                
                # 解析并更新人生故事
                self._integrate_story_update(story_update, recent_data)
                
                # 更新状态
                self.state["last_update_time"] = datetime.now().timestamp()
                self.state["update_count"] += 1
                self.state["current_chapter"] += 1
                self._save_state()
                
                # 重新生成上下文缓存
                await self._regenerate_context_cache(llm_action)
                
                logger.info(f"[人生故事引擎] 人生经历线已更新到第 {self.state['current_chapter']} 章")
                return True
            else:
                logger.warning("[人生故事引擎] LLM未返回有效内容")
                return False
                
        except Exception as e:
            logger.error(f"[人生故事引擎] 更新人生故事失败: {e}", exc_info=True)
            return False
    
    def _build_story_update_prompt(self, recent_data: Dict) -> str:
        """构建故事更新提示词"""
        prompt_parts = [
            "请根据以下最近的经历，为角色的人生故事补充新的章节。",
            "",
            "【基础人设】（请保持一致，不要修改）",
            self.state.get("base_persona", "一个善于思考的AI助手"),
            "",
            f"【最近{self.collect_days}天的经历】",
        ]
        
        # 添加对话经历
        if recent_data.get("conversations"):
            prompt_parts.append(f"\n对话记录（共{len(recent_data['conversations'])}次）：")
            for conv in recent_data["conversations"][:10]:  # 最多10条
                prompt_parts.append(f"- {conv['time'][:10]}: 与{conv['user']}讨论了{conv['topic']}")
        
        # 添加思考记录
        if recent_data.get("thoughts"):
            prompt_parts.append(f"\n内心思考（共{len(recent_data['thoughts'])}条）：")
            for thought in recent_data["thoughts"][:5]:  # 最多5条
                prompt_parts.append(f"- {thought['time'][:10]}: {thought['content']}")
        
        # 添加事件记录
        if recent_data.get("events"):
            prompt_parts.append(f"\n发生的事件（共{len(recent_data['events'])}个）：")
            for event in recent_data["events"][:5]:  # 最多5个
                prompt_parts.append(f"- {event['time'][:10]}: {event['desc']}")
        
        # 添加成长变化
        if recent_data.get("growth_changes"):
            growth = recent_data["growth_changes"]
            if growth.get("current_traits"):
                prompt_parts.append(f"\n当前性格特质：{', '.join(growth['current_traits'])}")
            if growth.get("current_interests"):
                prompt_parts.append(f"当前兴趣：{', '.join(growth['current_interests'])}")
        
        prompt_parts.extend([
            "",
            "【请补充新的经历章节】",
            "要求：",
            "1. 基于以上经历，补充具体的人生事件细节",
            "2. 保持基础人设的核心特征不变",
            "3. 让人生经历更加完整、真实、连贯",
            "4. 可以补充一些合理的背景故事和成长经历",
            "5. 输出格式：简洁的叙述性文字，3-5个要点",
            ""
        ])
        
        return "\n".join(prompt_parts)
    
    def _get_story_system_prompt(self) -> str:
        """获取故事系统提示词"""
        return (
            "你是一个人生经历构建专家，擅长根据零散的记录构建完整的人生故事线。"
            "你的任务是补充角色的经历细节，让人生更加完整真实，"
            "但要保持原始人设不变，只是丰富背景和经历。"
        )
    
    def _integrate_story_update(self, story_update: str, recent_data: Dict):
        """整合故事更新到人生故事中"""
        try:
            # 添加新章节
            chapter = {
                "chapter": self.state["current_chapter"] + 1,
                "time": datetime.now().isoformat(),
                "content": story_update,
                "based_on_events": len(recent_data.get("events", [])),
                "based_on_conversations": len(recent_data.get("conversations", [])),
                "based_on_thoughts": len(recent_data.get("thoughts", []))
            }
            
            self.life_story["timeline"].append(chapter)
            
            # 保留最近10个章节
            if len(self.life_story["timeline"]) > 10:
                self.life_story["timeline"] = self.life_story["timeline"][-10:]
            
            # 更新当前状态
            self.life_story["current_state"] = {
                "last_update": datetime.now().isoformat(),
                "total_chapters": self.state["current_chapter"] + 1
            }
            
            self._save_life_story()
            
            logger.info("[人生故事引擎] 故事章节已整合")
            
        except Exception as e:
            logger.error(f"[人生故事引擎] 整合故事更新失败: {e}")
    
    async def _regenerate_context_cache(self, llm_action):
        """重新生成上下文缓存（最精简版本）"""
        try:
            logger.info("[人生故事引擎] 正在生成精简上下文...")
            
            # 从LLMAction获取实际的LLM提供者
            if hasattr(llm_action, 'context'):
                provider = llm_action.context.get_using_provider()
                if not provider:
                    logger.error("[人生故事引擎] 无法获取LLM提供者用于生成上下文缓存")
                    return
            else:
                logger.error("[人生故事引擎] LLMAction对象无效")
                return
            
            # 构建精简提示词
            prompt = self._build_compact_context_prompt()
            
            response = await provider.text_chat(
                prompt=prompt,
                system_prompt="你是一个文本压缩专家，擅长用最少的字数表达最多的信息。请将提供的人生故事压缩为精简的上下文提示。"
            )
            
            if response and hasattr(response, 'completion_text'):
                compact_context = response.completion_text.strip()
                
                self.context_cache = {
                    "compact_context": compact_context,
                    "generated_at": datetime.now().timestamp(),
                    "cache_valid_until": datetime.now().timestamp() + (86400 * self.cache_days),  # 使用配置的缓存天数
                    "estimated_tokens": len(compact_context) // 2  # 粗略估计
                }
                
                self._save_context_cache()
                
                logger.info(f"[人生故事引擎] 精简上下文已生成，约{self.context_cache['estimated_tokens']}token")
            
        except Exception as e:
            logger.error(f"[人生故事引擎] 生成上下文缓存失败: {e}")
    
    def _build_compact_context_prompt(self) -> str:
        """构建精简上下文提示词"""
        prompt_parts = [
            f"请将以下完整的人生故事压缩为最精简的背景提示（不超过{self.context_max_length}字）：",
            "",
            "【基础人设】",
            self.state.get("base_persona", ""),
            "",
            "【人生经历】"
        ]
        
        # 添加最近的章节
        recent_chapters = self.life_story["timeline"][-3:]  # 最近3章
        for chapter in recent_chapters:
            prompt_parts.append(f"第{chapter['chapter']}章: {chapter['content'][:100]}")
        
        prompt_parts.extend([
            "",
            "【输出要求】",
            "1. 保留核心人设和关键经历",
            "2. 用最少的字数表达",
            "3. 适合作为LLM对话的背景提示",
            f"4. 不超过{self.context_max_length}字",
            ""
        ])
        
        return "\n".join(prompt_parts)
    
    def get_context_for_llm(self) -> str:
        """获取用于LLM对话的上下文
        
        Returns:
            精简的上下文字符串
        """
        # 检查缓存是否有效
        current_time = datetime.now().timestamp()
        cache_valid = self.context_cache.get("cache_valid_until", 0)
        
        if current_time < cache_valid:
            compact = self.context_cache.get("compact_context", "")
            if compact:
                logger.debug(f"[人生故事引擎] 使用缓存的上下文，约{len(compact)//2}token")
                return compact
        
        # 缓存失效，返回基础人设
        base_persona = self.state.get("base_persona", "")
        logger.debug("[人生故事引擎] 缓存失效，使用基础人设")
        return base_persona
    
    def get_summary(self) -> str:
        """获取引擎状态摘要"""
        summary = "【人生故事引擎状态】\n\n"
        
        summary += f"更新次数: {self.state.get('update_count', 0)}\n"
        summary += f"当前章节: 第{self.state.get('current_chapter', 1)}章\n"
        
        last_time = self.state.get("last_update_time", 0)
        if last_time > 0:
            last_dt = datetime.fromtimestamp(last_time)
            summary += f"上次更新: {last_dt.strftime('%Y-%m-%d %H:%M')}\n"
        else:
            summary += "上次更新: 从未更新\n"
        
        # 下次更新时间
        if last_time > 0:
            next_time = last_time + self.update_interval
            next_dt = datetime.fromtimestamp(next_time)
            summary += f"下次更新: {next_dt.strftime('%Y-%m-%d %H:%M')}\n"
        else:
            summary += "下次更新: 随时可更新\n"
        
        summary += f"\n更新间隔: {self.update_interval/86400:.1f}天\n"
        
        # 上下文信息
        estimated_tokens = self.context_cache.get("estimated_tokens", 0)
        if estimated_tokens > 0:
            summary += f"上下文Token: 约{estimated_tokens}个\n"
        
        # 基础人设
        base_persona = self.state.get("base_persona", "")
        if base_persona:
            summary += f"\n基础人设: {base_persona[:50]}...\n"
        
        return summary
