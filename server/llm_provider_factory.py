#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
LLM提供商工厂 - 统一管理所有LLM调用
"""

import logging
import requests
import json
import time
from typing import Optional, Dict, Any
import config as _cfg
from config import load_config
from llm_call_logger import start_llm_call, record_first_byte, end_llm_call
import credits_service as credits


class LLMProvider:
    """LLM提供商基类"""

    supports_vision = False  # 子类能真正向 API 发送图片才置 True（防静默丢图，CodeReview A1）
    
    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        
    def call(self, prompt: str, context: str = "", usage_out: Optional[dict] = None,
             images: Optional[list] = None) -> Optional[str]:
        """调用LLM API。usage_out 不为 None 时回写 prompt_tokens/completion_tokens（积分计费采集）。
        images：[{"mime": "image/jpeg", "b64": "…"}] 仅视觉 provider 消费，文字 provider 忽略。"""
        raise NotImplementedError("子类必须实现call方法")
    
    def test_connection(self) -> tuple[bool, str]:
        """测试连接"""
        try:
            result = self.call("请回复'连接测试成功'")
            if result:
                return True, f"✅ 连接测试成功\n回复内容: {result[:100]}{'...' if len(result) > 100 else ''}"
            else:
                return False, "❌ 连接测试失败: 无响应"
        except Exception as e:
            return False, f"❌ 连接测试异常: {str(e)}"


class OllamaProvider(LLMProvider):
    """Ollama提供商"""
    
    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        super().__init__(config, logger)
        self.api_url = config.get("ollama_api_url", "http://localhost:11434/api/generate")
        self.model = config.get("ollama_model", "deepseek-r1:1.5b")
        
    def call(self, prompt: str, context: str = "", usage_out: Optional[dict] = None,
             images: Optional[list] = None) -> Optional[str]:
        """调用Ollama API"""
        # 开始记录调用日志
        call_id = start_llm_call("Ollama", self.model, prompt, context, self.api_url)
        
        self.logger.info(f"调用Ollama API: {self.api_url}, 模型: {self.model}")
        
        try:
            response = requests.post(self.api_url, json={
                "model": self.model,
                "prompt": prompt,
                "stream": False
            }, timeout=120)
            
            # 记录首字节时间
            record_first_byte(call_id)
            
            response.raise_for_status()
            data = response.json()
            ai_response = data.get("response", "").strip()
            
            if ai_response:
                self.logger.info(f"Ollama回复成功，长度: {len(ai_response)}")
                if usage_out is not None:
                    usage_out["prompt_tokens"] = int(data.get("prompt_eval_count") or 0)
                    usage_out["completion_tokens"] = int(data.get("eval_count") or 0)
                # 记录成功调用
                end_llm_call(call_id, ai_response, True, "", response.status_code)
                return ai_response
            else:
                self.logger.warning("Ollama返回空回复")
                # 记录失败调用
                end_llm_call(call_id, "", False, "返回空回复", response.status_code)
                return None
                
        except requests.exceptions.ConnectionError as e:
            error_msg = f"Ollama连接失败: 请检查Ollama服务是否运行在 {self.api_url}"
            self.logger.error(f"Ollama连接失败: {e}")
            end_llm_call(call_id, "", False, error_msg, 0)
            raise Exception(error_msg)
        except requests.exceptions.Timeout as e:
            error_msg = "Ollama请求超时: 请检查网络连接或增加超时时间"
            self.logger.error(f"Ollama请求超时: {e}")
            end_llm_call(call_id, "", False, error_msg, 0)
            raise Exception(error_msg)
        except Exception as e:
            error_msg = f"Ollama调用失败: {str(e)}"
            self.logger.error(error_msg)
            status_code = getattr(e, 'response', {}).get('status_code', 0) if hasattr(e, 'response') else 0
            end_llm_call(call_id, "", False, error_msg, status_code)
            raise Exception(error_msg)


class GeminiProvider(LLMProvider):
    """Gemini提供商"""
    
    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        super().__init__(config, logger)
        self.api_key = config.get("gemini_api_key", "").strip()
        self.model = config.get("gemini_model", "gemini-1.5-flash-002").strip()
        
        if not self.api_key:
            raise ValueError("Gemini API Key未配置，请在设置中配置API Key")
    
    def call(self, prompt: str, context: str = "", usage_out: Optional[dict] = None,
             images: Optional[list] = None) -> Optional[str]:
        """调用Gemini API"""
        # 开始记录调用日志
        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        call_id = start_llm_call("Gemini", self.model, prompt, context, api_url)
        
        self.logger.info(f"调用Gemini API，模型: {self.model}")
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [
                {"parts": [{"text": prompt}]}
            ]
        }
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=60)
            
            # 记录首字节时间
            record_first_byte(call_id)
            
            if not response.ok:
                error_msg = f"Gemini API调用失败: HTTP {response.status_code}"
                if response.status_code == 401:
                    error_msg += " - API Key无效"
                elif response.status_code == 403:
                    error_msg += " - API配额不足或权限不够"
                self.logger.error(error_msg)
                raise Exception(error_msg)
            
            data = response.json()
            candidates = data.get("candidates", [])
            if candidates and "content" in candidates[0]:
                parts = candidates[0]["content"].get("parts", [])
                if parts and "text" in parts[0]:
                    result = parts[0]["text"].strip()
                    self.logger.info(f"Gemini回复成功，长度: {len(result)}")
                    if usage_out is not None:
                        um = data.get("usageMetadata") or {}
                        usage_out["prompt_tokens"] = int(um.get("promptTokenCount") or 0)
                        usage_out["completion_tokens"] = int(um.get("candidatesTokenCount") or 0)
                    end_llm_call(call_id, result, True, "", response.status_code)
                    return result
            
            error_msg = "无法解析Gemini响应格式"
            self.logger.error("无法解析Gemini响应")
            end_llm_call(call_id, "", False, error_msg, response.status_code)
            raise Exception(error_msg)
            
        except requests.exceptions.ConnectionError as e:
            error_msg = "Gemini连接失败: 请检查网络连接"
            self.logger.error(f"Gemini连接失败: {e}")
            end_llm_call(call_id, "", False, error_msg, 0)
            raise Exception(error_msg)
        except requests.exceptions.Timeout as e:
            error_msg = "Gemini请求超时: 请检查网络连接"
            self.logger.error(f"Gemini请求超时: {e}")
            end_llm_call(call_id, "", False, error_msg, 0)
            raise Exception(error_msg)
        except Exception as e:
            if "API" in str(e):
                end_llm_call(call_id, "", False, str(e), 0)
                raise e
            error_msg = f"Gemini请求异常: {str(e)}"
            self.logger.error(error_msg)
            end_llm_call(call_id, "", False, error_msg, 0)
            raise Exception(error_msg)


class DeepSeekProvider(LLMProvider):
    """DeepSeek提供商"""
    
    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        super().__init__(config, logger)
        self.api_key = config.get("deepseek_api_key", "").strip()
        self.model = config.get("deepseek_model", "deepseek-chat").strip()
        self.api_url = config.get("deepseek_api_url", "https://api.deepseek.com/v1/chat/completions").strip()
        
        if not self.api_key:
            raise ValueError("DeepSeek API Key未配置，请在设置中配置API Key")
    
    def call(self, prompt: str, context: str = "", usage_out: Optional[dict] = None,
             images: Optional[list] = None) -> Optional[str]:
        """调用DeepSeek API"""
        # 开始记录调用日志
        call_id = start_llm_call("DeepSeek", self.model, prompt, context, self.api_url)
        
        self.logger.info(f"调用DeepSeek API: {self.api_url}, 模型: {self.model}")
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        payload = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "stream": False
        }
        
        try:
            response = requests.post(self.api_url, headers=headers, json=payload, timeout=60)
            
            if not response.ok:
                error_msg = f"DeepSeek API调用失败: HTTP {response.status_code}"
                if response.status_code == 401:
                    error_msg += " - API Key无效"
                elif response.status_code == 403:
                    error_msg += " - API配额不足或权限不够"
                self.logger.error(error_msg)
                raise Exception(error_msg)
            
            data = response.json()
            
            if "choices" in data and len(data["choices"]) > 0:
                content = data["choices"][0].get("message", {}).get("content", "").strip()
                if content:
                    self.logger.info(f"DeepSeek回复成功，长度: {len(content)}")
                    if usage_out is not None:
                        u = data.get("usage") or {}
                        usage_out["prompt_tokens"] = int(u.get("prompt_tokens") or 0)
                        usage_out["completion_tokens"] = int(u.get("completion_tokens") or 0)
                    end_llm_call(call_id, content, True, "", response.status_code)
                    return content
            
            error_msg = "无法解析DeepSeek响应格式"
            self.logger.error("无法解析DeepSeek响应")
            end_llm_call(call_id, "", False, error_msg, response.status_code)
            raise Exception(error_msg)
            
        except requests.exceptions.ConnectionError as e:
            error_msg = "DeepSeek连接失败: 请检查网络连接"
            self.logger.error(f"DeepSeek连接失败: {e}")
            end_llm_call(call_id, "", False, error_msg, 0)
            raise Exception(error_msg)
        except requests.exceptions.Timeout as e:
            error_msg = "DeepSeek请求超时: 请检查网络连接"
            self.logger.error(f"DeepSeek请求超时: {e}")
            end_llm_call(call_id, "", False, error_msg, 0)
            raise Exception(error_msg)
        except Exception as e:
            if "API" in str(e):
                end_llm_call(call_id, "", False, str(e), 0)
                raise e
            error_msg = f"DeepSeek请求异常: {str(e)}"
            self.logger.error(error_msg)
            end_llm_call(call_id, "", False, error_msg, 0)
            raise Exception(error_msg)


class QwenProvider(LLMProvider):
    """通义千问提供商"""
    
    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        super().__init__(config, logger)
        self.api_key = config.get("qwen_api_key", "").strip()
        self.model = config.get("qwen_model", "qwen-flash").strip()
        self.api_url = config.get("qwen_api_url", "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation").strip()
        
        if not self.api_key:
            raise ValueError("通义千问 API Key未配置，请在设置中配置API Key")
    
    def call(self, prompt: str, context: str = "", usage_out: Optional[dict] = None,
             images: Optional[list] = None) -> Optional[str]:
        """调用通义千问 API"""
        # 开始记录调用日志
        call_id = start_llm_call("Qwen", self.model, prompt, context, self.api_url)
        
        self.logger.info(f"调用通义千问 API: {self.api_url}, 模型: {self.model}")
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        payload = {
            "model": self.model,
            "input": {
                "messages": [
                    {"role": "user", "content": prompt}
                ]
            },
            "parameters": {
                "result_format": "message"
            }
        }
        
        try:
            response = requests.post(self.api_url, headers=headers, json=payload, timeout=60)
            
            # 记录首字节时间
            record_first_byte(call_id)
            
            if not response.ok:
                error_msg = f"通义千问 API调用失败: HTTP {response.status_code}"
                if response.status_code == 401:
                    error_msg += " - API Key无效"
                elif response.status_code == 403:
                    error_msg += " - API配额不足或权限不够"
                self.logger.error(error_msg)
                self.logger.error(f"响应内容: {response.text}")
                end_llm_call(call_id, "", False, error_msg, response.status_code)
                raise Exception(error_msg)
            
            data = response.json()
            
            if "output" in data and "choices" in data["output"] and len(data["output"]["choices"]) > 0:
                content = data["output"]["choices"][0].get("message", {}).get("content", "").strip()
                if content:
                    self.logger.info(f"通义千问回复成功，长度: {len(content)}")
                    if usage_out is not None:
                        u = data.get("usage") or {}
                        usage_out["prompt_tokens"] = int(u.get("input_tokens") or 0)
                        usage_out["completion_tokens"] = int(u.get("output_tokens") or 0)
                    end_llm_call(call_id, content, True, "", response.status_code)
                    return content
            
            error_msg = "无法解析通义千问响应格式"
            self.logger.error("无法解析通义千问响应")
            self.logger.error(f"响应数据: {data}")
            end_llm_call(call_id, "", False, error_msg, response.status_code)
            raise Exception(error_msg)
            
        except requests.exceptions.ConnectionError as e:
            error_msg = "通义千问连接失败: 请检查网络连接"
            self.logger.error(f"通义千问连接失败: {e}")
            end_llm_call(call_id, "", False, error_msg, 0)
            raise Exception(error_msg)
        except requests.exceptions.Timeout as e:
            error_msg = "通义千问请求超时: 请检查网络连接"
            self.logger.error(f"通义千问请求超时: {e}")
            end_llm_call(call_id, "", False, error_msg, 0)
            raise Exception(error_msg)
        except Exception as e:
            if "API" in str(e):
                end_llm_call(call_id, "", False, str(e), 0)
                raise e
            error_msg = f"通义千问请求异常: {str(e)}"
            self.logger.error(error_msg)
            end_llm_call(call_id, "", False, error_msg, 0)
            raise Exception(error_msg)


class SiliconFlowVisionProvider(LLMProvider):
    """视觉大模型 provider（OpenAI 兼容 chat/completions + image_url dataURL）。

    默认指硅基流动 Qwen3-VL（系统级 VL_API_* 配置，key 复用 AIFinFlowX 存量，2026-10-13 实测可用）；
    用户自备 OpenAI 兼容视觉端点时也由本类承载（base/key/model 由调用方 cfg 传入）。
    请求侧 session.trust_env=False：paddle/siliconflow 为国内直连通道，经 V2RAYN 代理会 SSL 握手失败（实测）。
    LLM 日志 prompt 字段只存文本部分，图片体不入日志（防 base64 膨胀，images 数量记入 context）。
    """

    supports_vision = True

    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        super().__init__(config, logger)
        self.api_base = str(config.get("vl_api_base", "https://api.siliconflow.cn/v1")).strip().rstrip("/")
        self.api_key = str(config.get("vl_api_key", "")).strip()
        self.model = str(config.get("vl_model", "Qwen/Qwen3-VL-32B-Instruct")).strip()
        self.max_tokens = int(config.get("vl_max_tokens", 4096) or 4096)
        self.api_url = self.api_base + "/chat/completions"
        if not self.api_key:
            raise ValueError("视觉大模型 API Key 未配置（VL_API_KEY）")

    def call(self, prompt: str, context: str = "", usage_out: Optional[dict] = None,
             images: Optional[list] = None) -> Optional[str]:
        """images: [{"mime": "image/jpeg", "b64": "…"}]；无图时退化为纯文本调用。"""
        n_img = len(images or [])
        call_id = start_llm_call("SiliconFlowVL", self.model, prompt,
                                 f"{context} images={n_img}", self.api_url)
        self.logger.info(f"调用视觉模型: {self.api_url}, 模型: {self.model}, 图数: {n_img}")
        parts = [{"type": "text", "text": prompt}]
        for im in images or []:
            parts.append({"type": "image_url",
                          "image_url": {"url": f"data:{im.get('mime', 'image/jpeg')};base64,{im.get('b64', '')}"}})
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": parts}],
            "max_tokens": self.max_tokens,
            "temperature": 0.2,  # 结构化整理任务：低随机性防幻觉
            "stream": False,
        }
        with requests.Session() as session:  # 评审 Minor4：显式回收连接
            session.trust_env = False  # 国内直连，不吃环境变量代理（实测代理链路 SSL 失败）
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
            # 瞬态错误（5xx/网络异常）最多重试 2 次：这类失败未抵达 charge_llm、不扣分，
            # 重试不违反禁止重复扣分（区别于「JSON 解析失败不重发」——那是已扣分的返回内容失败）。
            # 2026-10-11 实测硅基流动 50507 瞬态失败率约 4 成，2 次尝试仍会整单失败，故 1+2 共 3 次
            max_attempts = 3
            for attempt in range(1, max_attempts + 1):
                try:
                    response = session.post(self.api_url, headers=headers, json=payload, timeout=180)
                    record_first_byte(call_id)
                    if not response.ok:
                        if 500 <= response.status_code < 600 and attempt < max_attempts:
                            self.logger.warning("视觉模型 %s（第 %d 次），自动重试", response.status_code, attempt)
                            time.sleep(3 * attempt)  # 递增退避 3s/6s，避开服务端短时过载
                            continue
                        error_msg = f"视觉模型 API调用失败: HTTP {response.status_code}"
                        if response.status_code == 401:
                            error_msg += " - API Key无效"
                        elif response.status_code == 403:
                            error_msg += " - API配额不足或权限不够"
                        error_msg += f" | 响应: {response.text[:200]}"  # 诊断用：服务端真实报错
                        self.logger.error(error_msg)
                        end_llm_call(call_id, "", False, error_msg, response.status_code)
                        raise Exception(error_msg)
                    data = response.json()
                    choices = data.get("choices") or []
                    content = ""
                    if choices:
                        content = str(choices[0].get("message", {}).get("content") or "").strip()
                    if content:
                        if usage_out is not None:
                            u = data.get("usage") or {}
                            usage_out["prompt_tokens"] = int(u.get("prompt_tokens") or 0)
                            usage_out["completion_tokens"] = int(u.get("completion_tokens") or 0)
                        end_llm_call(call_id, content, True, "", response.status_code)
                        return content
                    error_msg = "视觉模型返回空结果"
                    end_llm_call(call_id, "", False, error_msg, response.status_code)
                    raise Exception(error_msg)
                except requests.exceptions.RequestException as e:
                    if attempt < max_attempts:
                        self.logger.warning("视觉模型请求异常（第 %d 次），自动重试: %s", attempt, str(e)[:120])
                        time.sleep(3 * attempt)  # 递增退避 3s/6s
                        continue
                    error_msg = f"视觉模型请求异常: {str(e)[:200]}"
                    self.logger.error(error_msg)
                    end_llm_call(call_id, "", False, error_msg, 0)
                    raise Exception(error_msg)


class LLMProviderFactory:
    """LLM提供商工厂类"""
    
    _instance = None
    _provider = None
    _config_hash = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def get_provider(self, force_reload: bool = False) -> LLMProvider:
        """获取当前配置的LLM提供商实例"""
        # 加载最新配置
        config = load_config()
        config_hash = hash(json.dumps(config, sort_keys=True))
        
        # 如果配置没有变化且不强制重新加载，返回缓存的提供商
        if not force_reload and self._provider and self._config_hash == config_hash:
            return self._provider
        
        # 获取选中的提供商
        selected_provider = config.get("llm_provider", "Ollama")
        
        self.logger.info(f"创建LLM提供商: {selected_provider}")
        self.logger.info(f"配置信息: {json.dumps({k: v for k, v in config.items() if 'api_key' not in k}, indent=2)}")
        
        try:
            # 根据配置创建对应的提供商
            if selected_provider == "Ollama":
                provider = OllamaProvider(config, self.logger)
            elif selected_provider == "Gemini":
                provider = GeminiProvider(config, self.logger)
            elif selected_provider == "DeepSeek":
                provider = DeepSeekProvider(config, self.logger)
            elif selected_provider == "Qwen":
                provider = QwenProvider(config, self.logger)
            else:
                raise ValueError(f"不支持的LLM提供商: {selected_provider}")
            
            # 缓存提供商和配置哈希
            self._provider = provider
            self._config_hash = config_hash
            
            self.logger.info(f"✅ LLM提供商 {selected_provider} 创建成功")
            return provider
            
        except Exception as e:
            error_msg = f"创建LLM提供商失败 - 当前配置: {selected_provider}\n错误信息: {str(e)}"
            self.logger.error(error_msg)
            raise Exception(error_msg)
    
    def call_llm(self, prompt: str, context: str = "", force_reload: bool = False, scene: str = "") -> str:
        """统一 LLM 调用入口（含积分计费路由，2026-09-28 积分功能）：

        - 请求上下文有登录用户时：
          1) 用户自备 Key → 不扣分（失败回落系统 Key）；
          2) 系统 Key → 余额预检不足则拦截（InsufficientCreditsError），
             调用成功后按 Token 折算扣分；管理员豁免但记流水。
        - 无用户上下文（启动任务/内部脚本）：旧路径不计费。
        计费结果写入线程本地 last_billing，端点用 credits.billing_for_response() 附带返回。
        """
        credits.set_last_billing(None)
        if not scene:
            scene = (context or "")[:60]  # 既有调用约定：context 即场景标签（如 'AI聊天对话'）
        uid = self._current_user_id()
        if uid:
            return self._call_billed(uid, prompt, context, scene)
        return self._call_legacy(prompt, context, force_reload)

    # ------------------------------------------------------------ 计费内部实现
    @staticmethod
    def _current_user_id() -> Optional[str]:
        """从 Flask 请求上下文解析当前登录用户（require_auth 设置的 g.user_id）。"""
        try:
            from flask import has_request_context, g
            if has_request_context():
                return getattr(g, "user_id", None)
        except Exception:  # noqa: BLE001
            pass
        return None

    @staticmethod
    def _provider_from_cfg(cfg: Dict[str, Any], logger) -> LLMProvider:
        name = cfg.get("llm_provider", "Ollama")
        if name == "Ollama":
            return OllamaProvider(cfg, logger)
        if name == "Gemini":
            return GeminiProvider(cfg, logger)
        if name == "DeepSeek":
            return DeepSeekProvider(cfg, logger)
        if name == "Qwen":
            return QwenProvider(cfg, logger)
        if name == "SiliconFlowVision":
            return SiliconFlowVisionProvider(cfg, logger)
        raise ValueError(f"不支持的LLM提供商: {name}")

    @staticmethod
    def _model_supports_vision(model_name: str) -> bool:
        """模型名启发判视觉能力（用户端点适配用，宁严勿宽：误判支持会静默丢图信息）。"""
        n = str(model_name or "").lower()
        return any(h in n for h in ("-vl", "vl-", "vision", "gpt-4o", "4o-"))

    def _vision_provider_for_user(self, ucfg: Dict[str, Any]) -> Optional[LLMProvider]:
        """用户自备 Key 的视觉适配（v1 限定：DeepSeek 槽位即 OpenAI 兼容端点可自定义 base，
        且模型名含视觉标志）；不符合返回 None → 回落系统 VL。不扣用户积分。"""
        if ucfg.get("llm_provider") != "DeepSeek":
            return None
        model = str(ucfg.get("deepseek_model", ""))
        if not self._model_supports_vision(model):
            return None
        url = str(ucfg.get("deepseek_api_url", ""))
        base = url.rsplit("/chat/completions", 1)[0].rstrip("/")
        if not base.startswith("http"):
            return None
        return SiliconFlowVisionProvider({
            "vl_api_base": base,
            "vl_api_key": ucfg.get("deepseek_api_key", ""),
            "vl_model": model,
        }, self.logger)

    def _call_billed(self, uid: str, prompt: str, context: str, scene: str,
                     images: Optional[list] = None) -> str:
        # 1) 用户自备 Key（配置了才走，不扣分）；视觉调用时用户端点须具备视觉能力，
        #    不具备则整体跳过用户分支→系统 VL（禁止拿用户文字模型硬跑视觉任务丢图）
        own = credits.get_user_llm_config(uid)
        if own:
            usage: Dict[str, int] = {}
            provider = None
            try:
                ucfg = credits.effective_llm_config(uid)
                provider = (self._vision_provider_for_user(ucfg) if images
                            else self._provider_from_cfg(ucfg, self.logger))
                if provider is None:
                    self.logger.info("用户自备模型不具备视觉能力，本次改用系统 VL 通道")
            except Exception as e:  # noqa: BLE001 配置组装失败也回落系统
                self.logger.warning("用户自备 Key 构造 provider 失败，回落系统 Key: %s", e)
                provider = None
            if provider is not None:
                try:
                    result = provider.call(prompt, context, usage_out=usage,
                                           images=images if provider.supports_vision else None)
                    if result:
                        # 自备 Key 不扣分，但记流水（delta=0）供管理员审计用量
                        credits.record_own_key_call(
                            uid, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0),
                            scene=scene, provider=str(ucfg.get("llm_provider", "")))
                        credits.set_last_billing({
                            "use_own_key": True, "credits": 0.0,
                            "tokens": int(usage.get("prompt_tokens", 0)) + int(usage.get("completion_tokens", 0)),
                            "balance": credits.get_balance(uid)["balance"],
                        })
                        return result
                    self.logger.warning("用户自备 Key 返回空结果，回落系统 Key")
                except Exception as e:  # noqa: BLE001 用户 Key 不可用→回落系统 Key
                    self.logger.warning("用户自备 Key 调用失败，回落系统 Key: %s", e)
        # 2) 系统 Key：预检 → 调用 → 扣分；带图调用固定走系统 VL 通道（VL_API_* 配置）
        pre = credits.precheck(uid)
        if not pre["allowed"]:
            credits.set_last_billing({"blocked": True, "balance": pre["balance"]})
            raise credits.InsufficientCreditsError(pre["balance"])
        if images:
            scfg = {"llm_provider": "SiliconFlowVision",
                    "vl_api_base": _cfg.VL_API_BASE, "vl_api_key": _cfg.VL_API_KEY,
                    "vl_model": _cfg.VL_MODEL}
        else:
            scfg = credits.effective_llm_config(None)
        s_usage: Dict[str, int] = {}
        provider = self._provider_from_cfg(scfg, self.logger)
        result = provider.call(prompt, context, usage_out=s_usage, images=images)
        if not result:
            raise Exception(f"LLM调用失败 - 当前配置的提供商: {scfg.get('llm_provider', '未知')}，返回了空结果")
        p_tok = int(s_usage.get("prompt_tokens", 0) or 0)
        c_tok = int(s_usage.get("completion_tokens", 0) or 0)
        estimated = False
        if p_tok + c_tok <= 0:
            # provider 未返回 usage（部分网关不支持）：按字符数估算，避免免费调用
            est = max(1, int((len(prompt) + len(result)) / 2.5))
            p_tok, estimated = est, True
        billing = credits.charge_llm(
            uid, p_tok, c_tok,
            scene=scene, provider=str(scfg.get("llm_provider", "")), model=str(getattr(provider, "model", "")),
            tokens_estimated=estimated)
        credits.set_last_billing(billing)
        return result

    def call_llm_vision(self, uid: str, prompt: str, images: list,
                        context: str = "", scene: str = "错题智能分析") -> str:
        """视觉调用统一入口（与 call_llm 同一计费链，CodeReview A1/L7）：

        uid 显式传入——后台 daemon 线程无 Flask 请求上下文，不得走 _current_user_id()。
        路由：用户自备视觉端点（不扣分）→ 否则系统 VL（扣分）。
        """
        credits.set_last_billing(None)
        return self._call_billed(uid, prompt, context, scene, images=images)

    def _call_legacy(self, prompt: str, context: str, force_reload: bool) -> str:
        """旧路径（无用户上下文，不计费）：工厂缓存 provider + load_config。"""
        try:
            provider = self.get_provider(force_reload)
            result = provider.call(prompt, context)
            
            if result:
                return result
            else:
                config = load_config()
                selected_provider = config.get("llm_provider", "未知")
                raise Exception(f"LLM调用失败 - 当前配置的提供商: {selected_provider}，返回了空结果")
                
        except Exception as e:
            config = load_config()
            selected_provider = config.get("llm_provider", "未知")
            
            # 构建详细的错误信息
            error_msg = f"""LLM调用失败详情:
📋 当前配置的提供商: {selected_provider}
❌ 错误信息: {str(e)}
💡 建议: 请检查设置页面中的配置是否正确，或尝试切换到其他可用的提供商"""
            
            self.logger.error(error_msg)
            raise Exception(error_msg)
    
    def test_current_provider(self) -> tuple[bool, str]:
        """测试当前配置的提供商"""
        try:
            provider = self.get_provider(force_reload=True)
            return provider.test_connection()
        except Exception as e:
            config = load_config()
            selected_provider = config.get("llm_provider", "未知")
            error_msg = f"测试失败 - 当前配置: {selected_provider}\n错误: {str(e)}"
            return False, error_msg


# 全局工厂实例
llm_factory = LLMProviderFactory()


def get_llm_provider() -> LLMProvider:
    """获取LLM提供商实例的便捷函数"""
    return llm_factory.get_provider()


def call_llm(prompt: str, context: str = "", force_reload: bool = False, scene: str = "") -> str:
    """调用LLM的便捷函数（scene 用于流水场景标签，如 'AI Chat'/'提炼知识点'）"""
    return llm_factory.call_llm(prompt, context, force_reload, scene=scene)


def call_llm_vision(uid: str, prompt: str, images: list, context: str = "",
                    scene: str = "错题智能分析") -> str:
    """视觉 LLM 调用便捷函数（images: [{"mime", "b64"}]；uid 必传，后台线程计费不丢）"""
    return llm_factory.call_llm_vision(uid, prompt, images, context, scene)


def test_llm_connection() -> tuple[bool, str]:
    """测试LLM连接的便捷函数"""
    return llm_factory.test_current_provider()
