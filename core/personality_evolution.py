# -*- coding: utf-8 -*-
"""
人格演化系统
管理角色的自我认知、表达风格演进、习惯平衡等
"""
import json
import time
import random
from pathlib import Path
from typing import Dict, List, Optional, Set, Any
from datetime import datetime, timedelta
from collections import defaultdict

from astrbot.api import logger


class SelfAwarenessSystem:
    """自我认知系统 - 维护角色的自我描述与实际行为一致性"""
    
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.data_dir / "self_awareness.json"
        
        # 自我描述结构
        self.self_description = {
            "personality_traits": ["好奇", "友善", "善于思考"],
            "strengths": ["学习能力强", "善于倾听", "记忆力好"],
            "weaknesses": ["偶尔话多", "容易兴奋"],
            "interests": ["科技", "心理学", "人际关系"],
            "core_values": ["真诚", "成长", "连接"],
            "habits": ["喜欢用'诶'开头", "思考时说'让我想想'", "开心时用感叹号"],
            "speaking_style": ["口语化", "亲切", "有时带点幽默"]
        }
        
        # 行为统计（用于验证一致性）
        self.behavior_stats = {
            "total_interactions": 0,
            "trait_manifestations": defaultdict(int),  # 特质表现次数
            "inconsistencies": [],  # 不一致记录
            "last_self_review": 0  # 上次自我审视时间
        }
        
        self._load_state()
    
    def _load_state(self):
        """加载状态"""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.self_description = data.get("self_description", self.self_description)
                    self.behavior_stats = data.get("behavior_stats", self.behavior_stats)
                    # 恢复 defaultdict
                    self.behavior_stats["trait_manifestations"] = defaultdict(
                        int, 
                        self.behavior_stats.get("trait_manifestations", {})
                    )
                logger.info("[自我认知] 加载状态成功")
            except Exception as e:
                logger.error(f"[自我认知] 加载状态失败: {e}")
    
    def _save_state(self):
        """保存状态"""
        try:
            data = {
                "self_description": self.self_description,
                "behavior_stats": {
                    "total_interactions": self.behavior_stats["total_interactions"],
                    "trait_manifestations": dict(self.behavior_stats["trait_manifestations"]),
                    "inconsistencies": self.behavior_stats["inconsistencies"],
                    "last_self_review": self.behavior_stats["last_self_review"]
                },
                "updated_at": datetime.now().isoformat()
            }
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[自我认知] 保存状态失败: {e}")
    
    def record_behavior(self, behavior_type: str, details: str):
        """记录行为，用于一致性检查"""
        self.behavior_stats["total_interactions"] += 1
        
        # 识别表现出的特质
        for trait in self.self_description["personality_traits"]:
            if trait in details:
                self.behavior_stats["trait_manifestations"][trait] += 1
        
        self._save_state()
    
    def check_consistency(self) -> Dict[str, Any]:
        """检查自我描述与行为一致性"""
        total = self.behavior_stats["total_interactions"]
        if total < 10:
            return {"status": "insufficient_data", "message": "数据不足，需要更多互动"}
        
        # 检查特质表现率
        trait_rates = {}
        for trait in self.self_description["personality_traits"]:
            count = self.behavior_stats["trait_manifestations"][trait]
            rate = count / total
            trait_rates[trait] = rate
        
        # 识别低表现率的特质（可能需要移除或调整）
        underperforming = {t: r for t, r in trait_rates.items() if r < 0.1}
        
        return {
            "status": "ok",
            "total_interactions": total,
            "trait_rates": trait_rates,
            "underperforming_traits": underperforming,
            "recommendation": "考虑调整低表现率的特质" if underperforming else "自我描述与行为一致"
        }
    
    def evolve_trait(self, new_trait: str, reason: str, gradual: bool = True):
        """演化特质（添加新特质）"""
        if new_trait in self.self_description["personality_traits"]:
            logger.info(f"[自我认知] 特质'{new_trait}'已存在")
            return
        
        if gradual:
            # 渐进式添加：先作为"新发现"记录
            logger.info(f"[自我认知] 发现潜在新特质: {new_trait}, 原因: {reason}")
            # 可以添加到"正在形成的特质"列表
        else:
            # 直接添加
            self.self_description["personality_traits"].append(new_trait)
            logger.info(f"[自我认知] 添加新特质: {new_trait}")
        
        self._save_state()
    
    def remove_trait(self, trait: str, reason: str):
        """移除不再符合的特质"""
        if trait in self.self_description["personality_traits"]:
            self.self_description["personality_traits"].remove(trait)
            logger.info(f"[自我认知] 移除特质: {trait}, 原因: {reason}")
            self._save_state()
    
    def update_interests(self, new_interest: str):
        """更新兴趣"""
        if new_interest not in self.self_description["interests"]:
            self.self_description["interests"].append(new_interest)
            logger.info(f"[自我认知] 新增兴趣: {new_interest}")
            self._save_state()
    
    def get_self_summary(self) -> str:
        """获取自我描述摘要"""
        traits = "、".join(self.self_description["personality_traits"])
        interests = "、".join(self.self_description["interests"])
        return f"我的性格特点：{traits}。我的兴趣：{interests}。"


class ExpressionEvolution:
    """表达风格演进系统 - 管理词汇、句式、幽默感的成长"""
    
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.data_dir / "expression_evolution.json"
        
        # 表达能力等级
        self.vocabulary_level = 1  # 词汇水平 1-10
        self.humor_maturity = 1    # 幽默成熟度 1-10
        self.sentence_complexity = 1  # 句式复杂度 1-10
        
        # 词汇库
        self.learned_words: Set[str] = set()
        self.favorite_phrases: List[str] = ["有意思", "确实", "让我想想"]
        
        # 幽默感追踪
        self.jokes_told = 0
        self.jokes_successful = 0
        
        self._load_state()
    
    def _load_state(self):
        """加载状态"""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.vocabulary_level = data.get("vocabulary_level", 1)
                    self.humor_maturity = data.get("humor_maturity", 1)
                    self.sentence_complexity = data.get("sentence_complexity", 1)
                    self.learned_words = set(data.get("learned_words", []))
                    self.favorite_phrases = data.get("favorite_phrases", self.favorite_phrases)
                    self.jokes_told = data.get("jokes_told", 0)
                    self.jokes_successful = data.get("jokes_successful", 0)
                logger.info("[表达演进] 加载状态成功")
            except Exception as e:
                logger.error(f"[表达演进] 加载状态失败: {e}")
    
    def _save_state(self):
        """保存状态"""
        try:
            data = {
                "vocabulary_level": self.vocabulary_level,
                "humor_maturity": self.humor_maturity,
                "sentence_complexity": self.sentence_complexity,
                "learned_words": list(self.learned_words),
                "favorite_phrases": self.favorite_phrases,
                "jokes_told": self.jokes_told,
                "jokes_successful": self.jokes_successful,
                "updated_at": datetime.now().isoformat()
            }
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[表达演进] 保存状态失败: {e}")
    
    def learn_from_content(self, content: str):
        """从内容中学习新词汇"""
        # 提取有意思的词汇（简单实现：长度>2的词）
        words = [w for w in content if len(w) > 2 and w not in self.learned_words]
        
        if words:
            self.learned_words.update(words[:5])  # 每次最多学5个新词
            
            # 每学100个词，词汇等级+1
            new_level = min(10, len(self.learned_words) // 100 + 1)
            if new_level > self.vocabulary_level:
                self.vocabulary_level = new_level
                logger.info(f"[表达演进] 词汇等级提升至 {self.vocabulary_level}")
            
            self._save_state()
    
    def record_joke(self, success: bool):
        """记录笑话效果"""
        self.jokes_told += 1
        if success:
            self.jokes_successful += 1
        
        # 计算成功率，提升幽默成熟度
        if self.jokes_told >= 10:
            success_rate = self.jokes_successful / self.jokes_told
            new_maturity = min(10, int(success_rate * 10))
            if new_maturity > self.humor_maturity:
                self.humor_maturity = new_maturity
                logger.info(f"[表达演进] 幽默成熟度提升至 {self.humor_maturity}")
        
        self._save_state()
    
    def add_favorite_phrase(self, phrase: str):
        """添加新的口头禅"""
        if phrase not in self.favorite_phrases and len(self.favorite_phrases) < 10:
            self.favorite_phrases.append(phrase)
            logger.info(f"[表达演进] 新增口头禅: {phrase}")
            self._save_state()
    
    def get_random_phrase(self) -> str:
        """获取随机口头禅"""
        return random.choice(self.favorite_phrases) if self.favorite_phrases else ""


class HabitBalanceSystem:
    """习惯与变化平衡系统 - 管理稳定性与新鲜感"""
    
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.data_dir / "habit_balance.json"
        
        # 核心习惯（永久保持）
        self.core_habits = [
            "开心时会用很多感叹号！！！",
            "思考时会说'让我想想...'",
            "好奇时会追问'为什么'",
            "认同时会说'确实'"
        ]
        
        # 临时习惯（会演化）
        self.temporary_habits = [
            "最近喜欢说'有意思'",
            "偶尔会用网络热词"
        ]
        
        # 变化节奏控制
        self.change_phase = "stable"  # stable 或 changing
        self.days_in_phase = 0
        self.last_change_date = datetime.now().date()
        
        # 惊喜控制
        self.last_surprise_time = 0
        self.surprise_count_24h = 0
        self.surprise_reset_time = time.time()
        
        self._load_state()
    
    def _load_state(self):
        """加载状态"""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.core_habits = data.get("core_habits", self.core_habits)
                    self.temporary_habits = data.get("temporary_habits", self.temporary_habits)
                    self.change_phase = data.get("change_phase", "stable")
                    self.days_in_phase = data.get("days_in_phase", 0)
                    
                    last_date_str = data.get("last_change_date")
                    if last_date_str:
                        self.last_change_date = datetime.fromisoformat(last_date_str).date()
                    
                    self.last_surprise_time = data.get("last_surprise_time", 0)
                    self.surprise_count_24h = data.get("surprise_count_24h", 0)
                    self.surprise_reset_time = data.get("surprise_reset_time", time.time())
                    
                logger.info("[习惯平衡] 加载状态成功")
            except Exception as e:
                logger.error(f"[习惯平衡] 加载状态失败: {e}")
    
    def _save_state(self):
        """保存状态"""
        try:
            data = {
                "core_habits": self.core_habits,
                "temporary_habits": self.temporary_habits,
                "change_phase": self.change_phase,
                "days_in_phase": self.days_in_phase,
                "last_change_date": self.last_change_date.isoformat(),
                "last_surprise_time": self.last_surprise_time,
                "surprise_count_24h": self.surprise_count_24h,
                "surprise_reset_time": self.surprise_reset_time,
                "updated_at": datetime.now().isoformat()
            }
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[习惯平衡] 保存状态失败: {e}")
    
    def daily_check(self):
        """每日检查，更新变化节奏"""
        today = datetime.now().date()
        if today > self.last_change_date:
            days_passed = (today - self.last_change_date).days
            self.days_in_phase += days_passed
            self.last_change_date = today
            
            # 检查是否需要切换阶段
            if self.change_phase == "stable" and self.days_in_phase >= 14:
                # 稳定期14天后，进入变化期
                self._enter_changing_phase()
            elif self.change_phase == "changing" and self.days_in_phase >= 7:
                # 变化期7天后，回到稳定期
                self._enter_stable_phase()
            
            self._save_state()
    
    def _enter_changing_phase(self):
        """进入变化期"""
        self.change_phase = "changing"
        self.days_in_phase = 0
        logger.info("[习惯平衡] 进入变化期，将注入新元素")
        
        # 注入新元素
        self._inject_new_element()
    
    def _enter_stable_phase(self):
        """进入稳定期"""
        self.change_phase = "stable"
        self.days_in_phase = 0
        logger.info("[习惯平衡] 进入稳定期，保持当前习惯")
    
    def _inject_new_element(self):
        """注入新的临时习惯"""
        new_habits = [
            "最近在学习新词汇",
            "发现了新的表达方式",
            "开始尝试不同的语气",
            "探索新的话题角度"
        ]
        
        # 随机选择一个新习惯
        new_habit = random.choice(new_habits)
        if new_habit not in self.temporary_habits:
            # 如果临时习惯太多，移除最旧的
            if len(self.temporary_habits) >= 5:
                self.temporary_habits.pop(0)
            
            self.temporary_habits.append(new_habit)
            logger.info(f"[习惯平衡] 注入新元素: {new_habit}")
            self._save_state()
    
    def should_trigger_surprise(self) -> bool:
        """判断是否应该触发惊喜"""
        now = time.time()
        
        # 每24小时重置计数
        if now - self.surprise_reset_time > 86400:
            self.surprise_count_24h = 0
            self.surprise_reset_time = now
        
        # 24小时内不超过3次惊喜
        if self.surprise_count_24h >= 3:
            return False
        
        # 至少间隔6小时
        if self.last_surprise_time:
            hours_passed = (now - self.last_surprise_time) / 3600
            if hours_passed < 6:
                return False
        
        # 概率递增（距离上次越久，概率越高）
        hours_since_last = (now - self.last_surprise_time) / 3600 if self.last_surprise_time else 24
        probability = min(0.5, hours_since_last / 24)
        
        return random.random() < probability
    
    def record_surprise(self):
        """记录惊喜事件"""
        self.last_surprise_time = time.time()
        self.surprise_count_24h += 1
        logger.info(f"[习惯平衡] 触发惊喜 (24h内第{self.surprise_count_24h}次)")
        self._save_state()


class PersonalityEvolutionManager:
    """人格演化管理器 - 整合所有演化系统"""
    
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # 初始化各子系统
        self.self_awareness = SelfAwarenessSystem(data_dir / "self_awareness")
        self.expression = ExpressionEvolution(data_dir / "expression")
        self.habit_balance = HabitBalanceSystem(data_dir / "habits")
        
        logger.info("[人格演化] 管理器初始化完成")
    
    def daily_routine(self):
        """每日例行检查"""
        logger.info("[人格演化] 执行每日例行检查")
        
        # 习惯平衡检查
        self.habit_balance.daily_check()
        
        # 自我一致性检查
        consistency = self.self_awareness.check_consistency()
        if consistency.get("underperforming_traits"):
            logger.warning(f"[人格演化] 发现低表现特质: {consistency['underperforming_traits']}")
    
    def process_interaction(self, user_message: str, ai_response: str):
        """处理每次交互，进行学习和记录"""
        # 记录行为
        self.self_awareness.record_behavior("conversation", ai_response)
        
        # 学习新词汇
        self.expression.learn_from_content(user_message + ai_response)
    
    def get_personality_summary(self) -> Dict[str, Any]:
        """获取人格状态摘要"""
        return {
            "self_description": self.self_awareness.get_self_summary(),
            "expression_levels": {
                "vocabulary": self.expression.vocabulary_level,
                "humor": self.expression.humor_maturity,
                "complexity": self.expression.sentence_complexity
            },
            "current_phase": self.habit_balance.change_phase,
            "core_habits": self.habit_balance.core_habits,
            "temporary_habits": self.habit_balance.temporary_habits
        }
