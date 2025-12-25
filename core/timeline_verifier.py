# -*- coding: utf-8 -*-
"""
时间线验证引擎：确保经历的时间一致性和逻辑连贯性
支持时间线检验、经历关联分析、冲突检测等功能
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple
from collections import defaultdict
from astrbot.api import logger


class TimelineVerifier:
    """时间线验证系统 - 确保经历的时间一致性和逻辑连贯性"""
    
    def __init__(self, data_dir: Path):
        """初始化时间线验证器"""
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # 经历时间线档案
        self.timeline_file = self.data_dir / "experience_timeline.json"
        # 时间冲突检测日志
        self.conflict_log_file = self.data_dir / "timeline_conflicts.jsonl"
        # 经历关联图
        self.experience_graph_file = self.data_dir / "experience_graph.json"
        
        self._init_data_files()
    
    def _init_data_files(self):
        """初始化数据文件"""
        if not self.timeline_file.exists():
            self.timeline_file.write_text(json.dumps({
                "experiences": {},  # 按日期组织的经历
                "sequences": [],     # 时间序列
                "last_verified": datetime.now().isoformat()
            }, ensure_ascii=False, indent=2), encoding='utf-8')
        
        if not self.experience_graph_file.exists():
            self.experience_graph_file.write_text(json.dumps({
                "nodes": {},         # 经历节点
                "edges": [],         # 经历之间的关联
                "last_updated": datetime.now().isoformat()
            }, ensure_ascii=False, indent=2), encoding='utf-8')
        
        for file_path in [self.conflict_log_file]:
            if not file_path.exists():
                file_path.write_text("", encoding='utf-8')
    
    # ========== 时间线管理 ==========
    
    def add_experience(self,
                      experience_id: str,
                      content: str,
                      event_date: str,  # "YYYY-MM-DD" 或 "YYYY-MM" 或 "YYYY"
                      event_type: str = "general",
                      duration: Optional[str] = None,
                      related_experiences: Optional[List[str]] = None) -> bool:
        """
        添加经历到时间线
        
        Args:
            experience_id: 经历唯一ID
            content: 经历内容描述
            event_date: 事件日期（支持多种精度）
            event_type: 事件类型（achievement/emotional/routine/milestone/decision）
            duration: 持续时间（如"2周"、"3个月"）
            related_experiences: 相关经历列表
        
        Returns:
            是否成功添加
        """
        try:
            with open(self.timeline_file, 'r', encoding='utf-8') as f:
                timeline_data = json.load(f)
            
            # 规范化日期
            normalized_date = self._normalize_date(event_date)
            if not normalized_date:
                logger.warning(f"[时间线] 日期格式错误: {event_date}")
                return False
            
            # 创建经历记录
            experience = {
                "id": experience_id,
                "content": content,
                "event_date": normalized_date,
                "original_date_input": event_date,
                "event_type": event_type,
                "duration": duration,
                "added_at": datetime.now().isoformat(),
                "related_experiences": related_experiences or []
            }
            
            # 检查时间一致性
            consistency_check = self._check_consistency(experience, timeline_data)
            if not consistency_check["valid"]:
                logger.warning(f"[时间线] 时间一致性检查失败: {consistency_check['reason']}")
                self._log_conflict(experience, consistency_check)
                # 不中断，继续添加但标记为有问题
                experience["consistency_warning"] = consistency_check["reason"]
            
            # 添加到时间线
            timeline_data["experiences"][experience_id] = experience
            timeline_data["sequences"].append({
                "id": experience_id,
                "date": normalized_date,
                "type": event_type
            })
            
            # 排序序列
            timeline_data["sequences"].sort(
                key=lambda x: self._date_to_sortable(x["date"])
            )
            
            timeline_data["last_verified"] = datetime.now().isoformat()
            
            with open(self.timeline_file, 'w', encoding='utf-8') as f:
                json.dump(timeline_data, f, ensure_ascii=False, indent=2)
            
            # 更新关联图
            self._update_experience_graph(experience, timeline_data.get("experiences", {}))
            
            logger.info(f"[时间线] 经历已添加: {experience_id} ({normalized_date})")
            return True
            
        except Exception as e:
            logger.error(f"[时间线] 添加经历失败: {e}")
            return False
    
    def _normalize_date(self, date_input: str) -> Optional[str]:
        """
        规范化日期格式
        
        支持格式:
        - YYYY-MM-DD (精确日期)
        - YYYY-MM (月份)
        - YYYY (年份)
        - "上周" "上月" "去年" (相对日期)
        """
        try:
            # 精确日期
            if len(date_input) == 10 and date_input[4] == '-' and date_input[7] == '-':
                datetime.strptime(date_input, "%Y-%m-%d")
                return date_input
            
            # 月份
            elif len(date_input) == 7 and date_input[4] == '-':
                datetime.strptime(date_input, "%Y-%m")
                return date_input
            
            # 年份
            elif len(date_input) == 4:
                datetime.strptime(date_input, "%Y")
                return date_input
            
            # 相对日期转换
            elif "上周" in date_input:
                last_week = datetime.now() - timedelta(days=7)
                return last_week.strftime("%Y-%m-%d")
            elif "上月" in date_input:
                last_month = datetime.now() - timedelta(days=30)
                return last_month.strftime("%Y-%m")
            elif "去年" in date_input:
                last_year = datetime.now() - timedelta(days=365)
                return last_year.strftime("%Y")
            elif "今天" in date_input or "昨天" in date_input:
                today = datetime.now().strftime("%Y-%m-%d")
                return today
            
            return None
            
        except (ValueError, TypeError):
            return None
    
    def _date_to_sortable(self, date_str: str) -> float:
        """将日期字符串转换为可排序的数值"""
        try:
            if len(date_str) == 10:  # YYYY-MM-DD
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                return dt.timestamp()
            elif len(date_str) == 7:  # YYYY-MM
                dt = datetime.strptime(date_str + "-01", "%Y-%m-%d")
                return dt.timestamp()
            elif len(date_str) == 4:  # YYYY
                dt = datetime.strptime(date_str + "-01-01", "%Y-%m-%d")
                return dt.timestamp()
            else:
                return 0
        except:
            return 0
    
    def _check_consistency(self, 
                          new_experience: Dict[str, Any],
                          timeline_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        检查新经历的时间一致性
        
        Returns:
            {
                "valid": bool,
                "reason": str,
                "conflicts": List[str]
            }
        """
        new_date = self._date_to_sortable(new_experience["event_date"])
        conflicts = []
        
        # 检查1: 是否在未来（除非明确表示计划）
        now = datetime.now().timestamp()
        if new_date > now and new_experience["event_type"] != "planned":
            conflicts.append("事件日期在未来")
        
        # 检查2: 检查与相关经历的时间逻辑
        for related_id in new_experience.get("related_experiences", []):
            if related_id in timeline_data.get("experiences", {}):
                related_exp = timeline_data["experiences"][related_id]
                related_date = self._date_to_sortable(related_exp["event_date"])
                
                # 如果声称是"之后"的事，但日期更早
                if "之后" in new_experience.get("content", ""):
                    if new_date < related_date:
                        conflicts.append(f"时间逻辑错误：声称在'{related_id}'之后，但日期更早")
                
                # 如果声称是"之前"的事，但日期更晚
                if "之前" in new_experience.get("content", ""):
                    if new_date > related_date:
                        conflicts.append(f"时间逻辑错误：声称在'{related_id}'之前，但日期更晚")
        
        # 检查3: 检查持续时间逻辑
        if new_experience.get("duration"):
            duration_text = new_experience["duration"]
            if "周" in duration_text or "月" in duration_text or "年" in duration_text:
                # 简单验证持续时间不超过5年
                if "年" in duration_text:
                    try:
                        years = int(duration_text.split("年")[0])
                        if years > 5:
                            conflicts.append(f"持续时间过长：{years}年")
                    except:
                        pass
        
        valid = len(conflicts) == 0
        
        return {
            "valid": valid,
            "reason": conflicts[0] if conflicts else "通过检查",
            "conflicts": conflicts
        }
    
    def _log_conflict(self, experience: Dict[str, Any], conflict: Dict[str, Any]) -> None:
        """记录时间线冲突"""
        try:
            conflict_record = {
                "timestamp": datetime.now().isoformat(),
                "experience_id": experience.get("id"),
                "event_date": experience.get("event_date"),
                "reason": conflict.get("reason"),
                "conflicts": conflict.get("conflicts", [])
            }
            
            with open(self.conflict_log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(conflict_record, ensure_ascii=False) + "\n")
            
        except Exception as e:
            logger.error(f"[时间线] 记录冲突失败: {e}")
    
    # ========== 经历关联管理 ==========
    
    def _update_experience_graph(self, 
                                 experience: Dict[str, Any],
                                 all_experiences: Dict[str, Any]) -> None:
        """更新经历关联图"""
        try:
            with open(self.experience_graph_file, 'r', encoding='utf-8') as f:
                graph_data = json.load(f)
            
            # 添加节点
            exp_id = experience["id"]
            graph_data["nodes"][exp_id] = {
                "id": exp_id,
                "type": experience.get("event_type", "general"),
                "date": experience.get("event_date"),
                "content_preview": experience.get("content", "")[:100]
            }
            
            # 添加边（关联）
            for related_id in experience.get("related_experiences", []):
                if related_id in all_experiences:
                    edge = {
                        "source": exp_id,
                        "target": related_id,
                        "relationship": self._infer_relationship(experience, all_experiences.get(related_id, {}))
                    }
                    graph_data["edges"].append(edge)
            
            graph_data["last_updated"] = datetime.now().isoformat()
            
            with open(self.experience_graph_file, 'w', encoding='utf-8') as f:
                json.dump(graph_data, f, ensure_ascii=False, indent=2)
            
        except Exception as e:
            logger.error(f"[时间线] 更新关联图失败: {e}")
    
    def _infer_relationship(self, 
                           new_exp: Dict[str, Any],
                           related_exp: Dict[str, Any]) -> str:
        """
        推断两个经历之间的关系类型
        
        关系类型：
        - cause_effect: 因果关系
        - consequence: 结果
        - foundation: 基础
        - milestone: 里程碑
        - parallel: 并行事件
        """
        new_date = self._date_to_sortable(new_exp.get("event_date", ""))
        related_date = self._date_to_sortable(related_exp.get("event_date", ""))
        
        # 时间顺序
        if new_date > related_date:
            # 新经历在之后，可能是结果或后续
            if any(kw in new_exp.get("content", "") for kw in ["因为", "由于", "所以"]):
                return "consequence"
            else:
                return "follow_up"
        elif new_date < related_date:
            # 新经历在之前，可能是基础
            if any(kw in new_exp.get("content", "") for kw in ["奠定", "打下", "基础"]):
                return "foundation"
            else:
                return "precursor"
        else:
            # 同时发生
            return "parallel"
    
    def analyze_experience_coherence(self, user_experiences: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        分析用户经历的整体连贯性
        
        Args:
            user_experiences: 用户的所有经历列表
        
        Returns:
            连贯性分析结果
        """
        try:
            with open(self.timeline_file, 'r', encoding='utf-8') as f:
                timeline_data = json.load(f)
            
            all_experiences = timeline_data.get("experiences", {})
            
            # 分析1: 时间跨度
            dates = [self._date_to_sortable(exp.get("event_date", "")) for exp in all_experiences.values()]
            time_span = (max(dates) - min(dates)) / (365.25 * 24 * 3600) if dates else 0  # 年数
            
            # 分析2: 事件类型分布
            type_distribution = defaultdict(int)
            for exp in all_experiences.values():
                type_distribution[exp.get("event_type", "general")] += 1
            
            # 分析3: 关联密度
            with open(self.experience_graph_file, 'r', encoding='utf-8') as f:
                graph_data = json.load(f)
            
            edges = graph_data.get("edges", [])
            nodes_count = len(graph_data.get("nodes", {}))
            relationship_density = len(edges) / max(nodes_count - 1, 1) if nodes_count > 1 else 0
            
            # 分析4: 冲突统计
            conflicts = []
            if self.conflict_log_file.exists():
                with open(self.conflict_log_file, 'r', encoding='utf-8') as f:
                    conflicts = [json.loads(line) for line in f if line.strip()]
            
            # 分析5: 连贯性评分
            coherence_score = self._calculate_coherence_score(
                time_span,
                dict(type_distribution),
                relationship_density,
                len(conflicts)
            )
            
            return {
                "coherence_score": coherence_score,
                "time_span_years": round(time_span, 1),
                "total_experiences": len(all_experiences),
                "type_distribution": dict(type_distribution),
                "relationship_density": round(relationship_density, 2),
                "conflict_count": len(conflicts),
                "has_timeline_issues": len(conflicts) > 0,
                "assessment": self._assess_coherence(coherence_score)
            }
            
        except Exception as e:
            logger.error(f"[时间线] 分析连贯性失败: {e}")
            return {}
    
    def _calculate_coherence_score(self,
                                   time_span: float,
                                   type_dist: Dict[str, int],
                                   relationship_density: float,
                                   conflict_count: int) -> float:
        """
        计算连贯性评分 (0-1)
        
        考虑因素:
        - 时间分布的连贯性
        - 事件类型的多样性
        - 经历之间的关联强度
        - 时间冲突数量
        """
        score = 0.7  # 基础分
        
        # 时间分布 (0.1)
        if 1 <= time_span <= 10:
            score += 0.1  # 理想的时间跨度
        elif time_span > 20:
            score -= 0.05  # 跨度太大可能不够详细
        
        # 事件多样性 (0.1)
        type_count = len(type_dist)
        if type_count >= 3:
            score += 0.1
        elif type_count == 2:
            score += 0.05
        
        # 关联密度 (0.1)
        if relationship_density >= 0.5:
            score += 0.1
        elif relationship_density >= 0.2:
            score += 0.05
        
        # 冲突惩罚 (最多-0.3)
        score -= min(conflict_count * 0.05, 0.3)
        
        return max(min(score, 1.0), 0.0)
    
    def _assess_coherence(self, score: float) -> str:
        """根据评分给出评价"""
        if score >= 0.85:
            return "高度连贯 - 经历发展逻辑清晰，时间线完整"
        elif score >= 0.70:
            return "连贯 - 大部分经历合理，有轻微时间不对齐"
        elif score >= 0.50:
            return "基本连贯 - 存在多个时间逻辑问题，需要调整"
        else:
            return "低连贯 - 时间线混乱，需要重新梳理"
    
    def get_timeline_summary(self) -> Dict[str, Any]:
        """获取时间线摘要"""
        try:
            with open(self.timeline_file, 'r', encoding='utf-8') as f:
                timeline_data = json.load(f)
            
            experiences = timeline_data.get("experiences", {})
            sequences = timeline_data.get("sequences", [])
            
            # 按类型分组
            by_type = defaultdict(list)
            for exp in experiences.values():
                by_type[exp.get("event_type", "general")].append(exp)
            
            return {
                "total_experiences": len(experiences),
                "experiences_by_type": {k: len(v) for k, v in by_type.items()},
                "timeline_sequence": sequences[:10],  # 最近10个事件
                "date_range": {
                    "earliest": min([exp.get("event_date") for exp in experiences.values()]) if experiences else None,
                    "latest": max([exp.get("event_date") for exp in experiences.values()]) if experiences else None
                }
            }
            
        except Exception as e:
            logger.error(f"[时间线] 获取摘要失败: {e}")
            return {}
    
    def suggest_experience_improvements(self, experience_id: str) -> List[str]:
        """
        为单条经历提供改进建议
        
        Returns:
            改进建议列表
        """
        try:
            with open(self.timeline_file, 'r', encoding='utf-8') as f:
                timeline_data = json.load(f)
            
            experience = timeline_data.get("experiences", {}).get(experience_id)
            if not experience:
                return []
            
            suggestions = []
            
            # 建议1: 检查是否有关联
            if not experience.get("related_experiences"):
                suggestions.append("建议：添加相关经历的关联，增强连贯性")
            
            # 建议2: 检查时间精度
            date_input = experience.get("original_date_input", "")
            if len(date_input) == 4:  # 仅年份
                suggestions.append("建议：提高日期精度（月份或具体日期），便于时间线排序")
            
            # 建议3: 检查是否有时间冲突
            if experience.get("consistency_warning"):
                suggestions.append(f"改进：{experience.get('consistency_warning')}")
            
            # 建议4: 检查内容详细度
            content = experience.get("content", "")
            if len(content) < 50:
                suggestions.append("建议：补充更多细节，使经历更生动")
            
            # 建议5: 检查事件类型
            if experience.get("event_type") == "general":
                suggestions.append("建议：指定更具体的事件类型（成就、情感、里程碑等）")
            
            return suggestions
            
        except Exception as e:
            logger.error(f"[时间线] 生成改进建议失败: {e}")
            return []
