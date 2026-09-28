#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
LLM调用日志记录器 - 专门记录大模型调用的详细日志
"""

import json
import time
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from config import load_config


@dataclass
class LLMCallRecord:
    """LLM调用记录数据结构"""
    call_id: str                    # 调用唯一ID
    timestamp: str                  # 调用时间戳 (年月日时分秒)
    provider: str                   # 提供商名称
    model: str                      # 模型名称
    prompt_length: int              # 提示词长度
    prompt_preview: str             # 提示词预览(前100字符)
    response_length: int            # 响应长度
    response_preview: str           # 响应预览(前100字符)
    request_start_time: float       # 请求开始时间戳
    first_byte_time: float          # 接收到第一个字符的时间戳
    request_end_time: float         # 请求结束时间戳
    total_duration: float           # 总耗时(秒)
    time_to_first_byte: float       # 首字节时间(秒)
    success: bool                   # 是否成功
    error_message: str              # 错误信息(如果有)
    api_endpoint: str               # API端点
    status_code: int                # HTTP状态码
    context: str                    # 调用上下文(如"生成练习题目"、"AI聊天"等)


class LLMCallLogger:
    """LLM调用日志记录器"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        
        self._initialized = True
        self.logger = logging.getLogger(__name__)
        self.records: List[LLMCallRecord] = []
        self.max_records = 1000  # 最多保存1000条记录
        self._lock = threading.Lock()
        
        # 创建日志目录
        self.log_dir = Path("logs")
        self.log_dir.mkdir(exist_ok=True)
        
        # 设置专门的LLM调用日志文件
        self.log_file = self.log_dir / f"llm_calls_{datetime.now().strftime('%Y%m%d')}.jsonl"
        
        # 加载今天已有的日志记录
        self._load_today_records()
    
    def _load_today_records(self):
        """加载今天的日志记录"""
        if self.log_file.exists():
            try:
                with open(self.log_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.strip():
                            record_data = json.loads(line.strip())
                            record = LLMCallRecord(**record_data)
                            self.records.append(record)
                
                # 只保留最新的记录
                if len(self.records) > self.max_records:
                    self.records = self.records[-self.max_records:]
                    
                self.logger.info(f"加载了 {len(self.records)} 条LLM调用记录")
            except Exception as e:
                self.logger.error(f"加载LLM调用记录失败: {e}")
    
    def is_logging_enabled(self) -> bool:
        """检查是否启用了LLM调用日志记录"""
        config = load_config()
        return config.get("llm_call_logging_enabled", True)  # 默认开启
    
    def start_call(self, provider: str, model: str, prompt: str, context: str = "", api_endpoint: str = "") -> str:
        """开始记录LLM调用"""
        if not self.is_logging_enabled():
            return ""
        
        call_id = f"llm_call_{int(time.time() * 1000)}_{threading.get_ident()}"
        
        # 创建调用记录
        record = LLMCallRecord(
            call_id=call_id,
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            provider=provider,
            model=model,
            prompt_length=len(prompt),
            prompt_preview=prompt[:100] + "..." if len(prompt) > 100 else prompt,
            response_length=0,
            response_preview="",
            request_start_time=time.time(),
            first_byte_time=0,
            request_end_time=0,
            total_duration=0,
            time_to_first_byte=0,
            success=False,
            error_message="",
            api_endpoint=api_endpoint,
            status_code=0,
            context=context
        )
        
        with self._lock:
            self.records.append(record)
            # 保持记录数量限制
            if len(self.records) > self.max_records:
                self.records.pop(0)
        
        self.logger.info(f"🚀 开始LLM调用 [{call_id}] - {provider}({model}) - {context}")
        return call_id
    
    def record_first_byte(self, call_id: str):
        """记录接收到第一个字符的时间"""
        if not self.is_logging_enabled() or not call_id:
            return
        
        with self._lock:
            for record in reversed(self.records):
                if record.call_id == call_id:
                    record.first_byte_time = time.time()
                    record.time_to_first_byte = record.first_byte_time - record.request_start_time
                    self.logger.info(f"📨 首字节接收 [{call_id}] - 耗时: {record.time_to_first_byte:.3f}s")
                    break
    
    def end_call(self, call_id: str, response: str = "", success: bool = True, 
                 error_message: str = "", status_code: int = 200):
        """结束记录LLM调用"""
        if not self.is_logging_enabled() or not call_id:
            return
        
        end_time = time.time()
        
        with self._lock:
            for record in reversed(self.records):
                if record.call_id == call_id:
                    record.request_end_time = end_time
                    record.total_duration = end_time - record.request_start_time
                    record.response_length = len(response)
                    record.response_preview = response[:100] + "..." if len(response) > 100 else response
                    record.success = success
                    record.error_message = error_message
                    record.status_code = status_code
                    
                    # 如果没有记录首字节时间，使用结束时间
                    if record.first_byte_time == 0:
                        record.first_byte_time = end_time
                        record.time_to_first_byte = record.total_duration
                    
                    # 写入日志文件
                    self._write_to_file(record)
                    
                    # 记录日志
                    status = "✅ 成功" if success else "❌ 失败"
                    self.logger.info(f"{status} LLM调用完成 [{call_id}] - 总耗时: {record.total_duration:.3f}s, "
                                   f"首字节: {record.time_to_first_byte:.3f}s, "
                                   f"响应长度: {record.response_length}")
                    
                    if not success and error_message:
                        self.logger.error(f"❌ LLM调用错误 [{call_id}]: {error_message}")
                    
                    break
    
    def _write_to_file(self, record: LLMCallRecord):
        """将记录写入文件"""
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                json.dump(asdict(record), f, ensure_ascii=False)
                f.write('\n')
        except Exception as e:
            self.logger.error(f"写入LLM调用日志失败: {e}")
    
    def get_recent_records(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取最近的调用记录"""
        with self._lock:
            recent_records = self.records[-limit:] if len(self.records) > limit else self.records
            return [asdict(record) for record in reversed(recent_records)]
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取调用统计信息"""
        with self._lock:
            if not self.records:
                return {
                    "total_calls": 0,
                    "success_rate": 0,
                    "avg_duration": 0,
                    "avg_first_byte_time": 0,
                    "provider_stats": {},
                    "model_stats": {}
                }
            
            total_calls = len(self.records)
            successful_calls = sum(1 for r in self.records if r.success)
            success_rate = (successful_calls / total_calls) * 100
            
            # 只统计成功的调用
            successful_records = [r for r in self.records if r.success]
            avg_duration = sum(r.total_duration for r in successful_records) / len(successful_records) if successful_records else 0
            avg_first_byte_time = sum(r.time_to_first_byte for r in successful_records) / len(successful_records) if successful_records else 0
            
            # 提供商统计
            provider_stats = {}
            for record in self.records:
                provider = record.provider
                if provider not in provider_stats:
                    provider_stats[provider] = {"total": 0, "success": 0}
                provider_stats[provider]["total"] += 1
                if record.success:
                    provider_stats[provider]["success"] += 1
            
            # 模型统计
            model_stats = {}
            for record in self.records:
                model = f"{record.provider}:{record.model}"
                if model not in model_stats:
                    model_stats[model] = {"total": 0, "success": 0, "avg_duration": 0}
                model_stats[model]["total"] += 1
                if record.success:
                    model_stats[model]["success"] += 1
                    model_stats[model]["avg_duration"] += record.total_duration
            
            # 计算平均耗时
            for model, stats in model_stats.items():
                if stats["success"] > 0:
                    stats["avg_duration"] = stats["avg_duration"] / stats["success"]
            
            return {
                "total_calls": total_calls,
                "successful_calls": successful_calls,
                "success_rate": success_rate,
                "avg_duration": avg_duration,
                "avg_first_byte_time": avg_first_byte_time,
                "provider_stats": provider_stats,
                "model_stats": model_stats
            }
    
    def clear_records(self):
        """清空记录"""
        with self._lock:
            self.records.clear()
        self.logger.info("已清空LLM调用记录")


# 全局日志记录器实例
llm_call_logger = LLMCallLogger()


def start_llm_call(provider: str, model: str, prompt: str, context: str = "", api_endpoint: str = "") -> str:
    """开始记录LLM调用的便捷函数"""
    return llm_call_logger.start_call(provider, model, prompt, context, api_endpoint)


def record_first_byte(call_id: str):
    """记录首字节时间的便捷函数"""
    llm_call_logger.record_first_byte(call_id)


def end_llm_call(call_id: str, response: str = "", success: bool = True, 
                 error_message: str = "", status_code: int = 200):
    """结束记录LLM调用的便捷函数"""
    llm_call_logger.end_call(call_id, response, success, error_message, status_code)


def get_llm_call_records(limit: int = 50) -> List[Dict[str, Any]]:
    """获取LLM调用记录的便捷函数"""
    return llm_call_logger.get_recent_records(limit)


def get_llm_call_statistics() -> Dict[str, Any]:
    """获取LLM调用统计的便捷函数"""
    return llm_call_logger.get_statistics()
