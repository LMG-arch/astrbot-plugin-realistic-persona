# -*- coding: utf-8 -*-
"""
本地数据管理模块
用于管理天气、日程等数据的本地存储与读取
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
from astrbot.api import logger

class LocalDataManager:
    """本地数据管理器"""
    
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # 天气数据文件
        self.weather_file = self.data_dir / "weather_data.json"
        # 日程数据文件
        self.schedule_file = self.data_dir / "schedule_data.json"
        # 新闻数据文件
        self.news_file = self.data_dir / "news_data.json"
        
        # 初始化数据文件
        self._init_data_files()
    
    def _init_data_files(self):
        """初始化数据文件"""
        for file_path in [self.weather_file, self.schedule_file, self.news_file]:
            if not file_path.exists():
                file_path.write_text(json.dumps({}, ensure_ascii=False), encoding='utf-8')
    
    def save_weather_data(self, date: str, weather_data: str):
        """保存天气数据"""
        try:
            data = self._load_json_file(self.weather_file)
            data[date] = {
                "data": weather_data,
                "timestamp": datetime.now().isoformat()
            }
            self._save_json_file(self.weather_file, data)
            logger.debug(f"[LOCAL DATA] 天气数据已保存到本地: {date}")
        except Exception as e:
            logger.error(f"[LOCAL DATA] 保存天气数据失败: {e}")
    
    def get_weather_data(self, date: str) -> Optional[str]:
        """获取天气数据"""
        try:
            data = self._load_json_file(self.weather_file)
            if date in data:
                return data[date]["data"]
            return None
        except Exception as e:
            logger.error(f"[LOCAL DATA] 获取天气数据失败: {e}")
            return None
    
    def save_schedule_data(self, date: str, schedule_data: str):
        """保存日程数据"""
        try:
            data = self._load_json_file(self.schedule_file)
            data[date] = {
                "data": schedule_data,
                "timestamp": datetime.now().isoformat()
            }
            self._save_json_file(self.schedule_file, data)
            logger.debug(f"[LOCAL DATA] 日程数据已保存到本地: {date}")
        except Exception as e:
            logger.error(f"[LOCAL DATA] 保存日程数据失败: {e}")
    
    def get_schedule_data(self, date: str) -> Optional[str]:
        """获取日程数据"""
        try:
            data = self._load_json_file(self.schedule_file)
            if date in data:
                return data[date]["data"]
            return None
        except Exception as e:
            logger.error(f"[LOCAL DATA] 获取日程数据失败: {e}")
            return None
    
    def save_news_data(self, date: str, news_data: str):
        """保存新闻数据"""
        try:
            data = self._load_json_file(self.news_file)
            data[date] = {
                "data": news_data,
                "timestamp": datetime.now().isoformat()
            }
            self._save_json_file(self.news_file, data)
            logger.debug(f"[LOCAL DATA] 新闻数据已保存到本地: {date}")
        except Exception as e:
            logger.error(f"[LOCAL DATA] 保存新闻数据失败: {e}")
    
    def get_news_data(self, date: str) -> Optional[str]:
        """获取新闻数据"""
        try:
            data = self._load_json_file(self.news_file)
            if date in data:
                return data[date]["data"]
            return None
        except Exception as e:
            logger.error(f"[LOCAL DATA] 获取新闻数据失败: {e}")
            return None
    
    def _load_json_file(self, file_path: Path) -> Dict[str, Any]:
        """加载JSON文件"""
        try:
            content = file_path.read_text(encoding='utf-8')
            return json.loads(content) if content.strip() else {}
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
    
    def _save_json_file(self, file_path: Path, data: Dict[str, Any]):
        """保存JSON文件"""
        file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    
    def clear_expired_data(self, days_to_keep: int = 7):
        """清理过期数据"""
        try:
            current_time = datetime.now()
            
            for file_path in [self.weather_file, self.schedule_file, self.news_file]:
                data = self._load_json_file(file_path)
                dates_to_remove = []
                
                for date_str, item_data in data.items():
                    if "timestamp" in item_data:
                        try:
                            item_time = datetime.fromisoformat(item_data["timestamp"])
                            if (current_time - item_time).days > days_to_keep:
                                dates_to_remove.append(date_str)
                        except ValueError:
                            # 时间格式错误，移除该项
                            dates_to_remove.append(date_str)
                
                for date_str in dates_to_remove:
                    del data[date_str]
                
                self._save_json_file(file_path, data)
                
        except Exception as e:
            logger.error(f"[LOCAL DATA] 清理过期数据失败: {e}")