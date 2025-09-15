"""
LLM API调用日志记录器
记录所有大语言模型API的输入输出，方便调试和问题定位
"""

import logging
import json
import os
from datetime import datetime
from typing import Dict, Any, Optional


class LLMLogger:
    """LLM API调用日志记录器"""
    
    def __init__(self, log_file: str = "llm_api_calls.log"):
        self.log_file = log_file
        self.logger = self._setup_logger()
    
    def _setup_logger(self) -> logging.Logger:
        """设置日志记录器"""
        logger = logging.getLogger("LLM_API")
        logger.setLevel(logging.INFO)
        
        # 避免重复添加处理器
        if not logger.handlers:
            # 文件处理器
            file_handler = logging.FileHandler(self.log_file, encoding='utf-8')
            file_handler.setLevel(logging.INFO)
            
            # 控制台处理器
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            
            # 格式化器
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            
            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)
            
            logger.addHandler(file_handler)
            logger.addHandler(console_handler)
        
        return logger
    
    def log_api_call(self, 
                     api_type: str,  # "gemini", "ollama", "deepseek"
                     function_name: str,  # 调用的函数名
                     input_data: Dict[str, Any],  # 输入数据
                     output_data: Optional[Dict[str, Any]] = None,  # 输出数据
                     error: Optional[str] = None,  # 错误信息
                     response_time: Optional[float] = None  # 响应时间（秒）
                     ):
        """记录API调用"""
        
        timestamp = datetime.now().isoformat()
        
        log_entry = {
            "timestamp": timestamp,
            "api_type": api_type,
            "function_name": function_name,
            "input": input_data,
            "output": output_data,
            "error": error,
            "response_time_seconds": response_time,
            "success": error is None
        }
        
        # 记录到日志文件
        log_message = f"API调用 [{api_type}] {function_name}"
        if error:
            log_message += f" - 失败: {error}"
        else:
            log_message += " - 成功"
        
        if response_time:
            log_message += f" (耗时: {response_time:.2f}s)"
        
        self.logger.info(log_message)
        
        # 详细信息记录到单独的JSON文件
        json_log_file = self.log_file.replace('.log', '_detailed.jsonl')
        try:
            with open(json_log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
        except Exception as e:
            self.logger.error(f"写入详细日志失败: {e}")
    
    def log_gemini_call(self, 
                       function_name: str,
                       prompt: str,
                       response: Optional[str] = None,
                       error: Optional[str] = None,
                       response_time: Optional[float] = None,
                       model: str = "gemini-1.5-flash-latest",
                       config: Optional[Dict] = None):
        """记录Gemini API调用"""
        
        input_data = {
            "model": model,
            "prompt": prompt,
            "config": config or {}
        }
        
        output_data = None
        if response:
            output_data = {
                "response": response,
                "response_length": len(response)
            }
        
        self.log_api_call("gemini", function_name, input_data, output_data, error, response_time)
    
    def log_ollama_call(self,
                       function_name: str,
                       model: str,
                       prompt: str,
                       response: Optional[str] = None,
                       error: Optional[str] = None,
                       response_time: Optional[float] = None,
                       config: Optional[Dict] = None):
        """记录Ollama API调用"""
        
        input_data = {
            "model": model,
            "prompt": prompt,
            "config": config or {}
        }
        
        output_data = None
        if response:
            output_data = {
                "response": response,
                "response_length": len(response)
            }
        
        self.log_api_call("ollama", function_name, input_data, output_data, error, response_time)


# 全局日志记录器实例
_llm_logger = None

def get_llm_logger() -> LLMLogger:
    """获取全局LLM日志记录器实例"""
    global _llm_logger
    if _llm_logger is None:
        _llm_logger = LLMLogger()
    return _llm_logger


def log_gemini_call(function_name: str, prompt: str, response: str = None, 
                   error: str = None, response_time: float = None, **kwargs):
    """便捷函数：记录Gemini调用"""
    logger = get_llm_logger()
    logger.log_gemini_call(function_name, prompt, response, error, response_time, **kwargs)


def log_ollama_call(function_name: str, model: str, prompt: str, response: str = None,
                   error: str = None, response_time: float = None, **kwargs):
    """便捷函数：记录Ollama调用"""
    logger = get_llm_logger()
    logger.log_ollama_call(function_name, model, prompt, response, error, response_time, **kwargs)
