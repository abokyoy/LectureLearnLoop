import sys
import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTextEdit,
    QScrollArea, QSplitter, QMessageBox, QProgressBar, QGroupBox,
    QDialog, QListWidget, QListWidgetItem, QDialogButtonBox, QTextBrowser,
    QTableWidget, QTableWidgetItem, QAbstractItemView
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QObject
import requests
import json
from datetime import datetime

# Import knowledge management integration
try:
    from enhanced_practice_integration import EnhancedPracticeProcessor
    from llm_logger import log_gemini_call, log_ollama_call
    from error_import_dialog import ErrorImportDialog
    KNOWLEDGE_INTEGRATION_AVAILABLE = True
except ImportError:
    KNOWLEDGE_INTEGRATION_AVAILABLE = False
    print("Knowledge management integration not available")


class PracticeWorker(QObject):
    """Worker thread for generating practice questions and evaluating answers"""
    questionsReady = Signal(str)  # Generated questions in markdown format
    evaluationReady = Signal(str)  # Evaluation results in markdown format
    status = Signal(str)
    finished = Signal()
    
    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self.selected_text = ""
        self.questions_text = ""
        self.user_answers = ""
        self.mode = "generate"  # "generate" or "evaluate"
        # 防重入：标识当前是否有任务在运行，避免重复触发
        self.running = False
    
    def update_config(self, new_config: dict):
        """动态更新配置"""
        self.config = new_config
        print(f"[配置更新] PracticeWorker配置已更新，LLM提供商: {self.config.get('llm_provider', 'Gemini')}")
    
    def generate_questions(self, selected_text: str):
        """Generate practice questions based on selected text"""
        self.selected_text = selected_text
        self.mode = "generate"
        # 不在此处直接启动，改由 QThread.started 统一触发，避免双重调用
    
    def evaluate_answers(self, selected_text: str, questions_text: str, user_answers: str):
        """Evaluate user answers and provide explanations"""
        self.selected_text = selected_text
        self.questions_text = questions_text
        self.user_answers = user_answers
        self.mode = "evaluate"
        # 不在此处直接启动，改由 QThread.started 统一触发，避免双重调用
    
    def start_work(self):
        """Start the work based on mode"""
        if self.running:
            # 已有任务在执行，忽略重复启动
            self.status.emit("任务进行中，已忽略重复启动")
            return
        self.running = True
        try:
            if self.mode == "generate":
                self._generate_practice_questions()
            elif self.mode == "evaluate":
                self._evaluate_user_answers()
        except Exception as e:
            self.status.emit(f"处理错误: {e}")
        finally:
            self.running = False
            self.finished.emit()
    
    def _generate_practice_questions(self):
        """Generate practice questions using LLM"""
        self.status.emit("正在生成练习题目...")
        
        prompt = f"""请基于以下内容生成一套技术面试/笔试题目。

**重要要求：**
1. 使用纯文本格式输出，不要使用HTML或Markdown格式
2. 生成5-8道题目，包含不同类型：选择题、填空题、简答题、编程题、案例分析题
3. 题目要有一定难度梯度，从基础到进阶
4. 只提供题目，不要提供答案
5. 每道题目之间用空行分隔
6. 题目编号使用数字格式：1. 2. 3. 等
7. 选择题的选项使用 A) B) C) D) 格式
8. 为每道题目留出足够的答题空间提示

基础内容：
{self.selected_text}

请生成纯文本格式的练习题目："""

        # 根据用户配置选择模型（大小写不敏感）
        llm_provider = str(self.config.get("llm_provider", "Gemini")).strip()
        provider_norm = llm_provider.lower()
        allow_fallback = bool(self.config.get("enable_llm_fallback", False))
        print(f"[模型选择] 练习面板使用的LLM提供商: {llm_provider} (fallback={'on' if allow_fallback else 'off'})")
        
        if provider_norm == "deepseek":
            print(f"[模型选择] 使用DeepSeek模型: {self.config.get('deepseek_model', 'deepseek-chat')}")
            try:
                self._generate_with_deepseek(prompt)
            except Exception as deepseek_error:
                print(f"[LLM调用] DeepSeek API失败: {deepseek_error}")
                if not allow_fallback:
                    raise
                print(f"[模型选择] DeepSeek失败，尝试Gemini作为备用")
                try:
                    self._generate_with_gemini(prompt)
                except Exception as gemini_error:
                    print(f"[LLM调用] Gemini API也失败: {gemini_error}")
                    if not allow_fallback:
                        raise
                    print(f"[模型选择] Gemini失败，尝试Ollama作为备用")
                    try:
                        self._generate_with_ollama(prompt)
                    except Exception as ollama_error:
                        print(f"[LLM调用] Ollama API也失败: {ollama_error}")
                        self.status.emit(f"所有API都失败了: DeepSeek({deepseek_error}), Gemini({gemini_error}), Ollama({ollama_error})")
        elif provider_norm == "gemini":
            print(f"[模型选择] 使用Gemini模型: {self.config.get('gemini_model', 'gemini-1.5-flash-latest')}")
            try:
                self._generate_with_gemini(prompt)
            except Exception as gemini_error:
                print(f"[LLM调用] Gemini API失败: {gemini_error}")
                if not allow_fallback:
                    raise
                print(f"[模型选择] Gemini失败，尝试Ollama作为备用")
                try:
                    self._generate_with_ollama(prompt)
                except Exception as ollama_error:
                    print(f"[LLM调用] Ollama API也失败: {ollama_error}")
                    self.status.emit(f"所有API都失败了: Gemini({gemini_error}), Ollama({ollama_error})")
        else:
            print(f"[模型选择] 使用Ollama模型: {self.config.get('ollama_model', 'deepseek-coder')}")
            try:
                self._generate_with_ollama(prompt)
            except Exception as ollama_error:
                print(f"[LLM调用] Ollama API失败: {ollama_error}")
                if not allow_fallback:
                    raise
                print(f"[模型选择] Ollama失败，尝试Gemini作为备用")
                try:
                    self._generate_with_gemini(prompt)
                except Exception as gemini_error:
                    print(f"[LLM调用] Gemini API也失败: {gemini_error}")
                    self.status.emit(f"所有API都失败了: Ollama({ollama_error}), Gemini({gemini_error})")
    
    def _generate_with_deepseek(self, prompt: str):
        """使用DeepSeek API生成练习题目"""
        import time
        
        api_key = self.config.get("deepseek_api_key", "")
        if not api_key:
            error_msg = "错误: 未配置DeepSeek API密钥"
            self.status.emit(error_msg)
            if KNOWLEDGE_INTEGRATION_AVAILABLE:
                log_ollama_call("generate_practice_questions", "deepseek-chat", prompt, error=error_msg)
            raise Exception(error_msg)
        
        # 使用用户配置的DeepSeek模型
        deepseek_model = self.config.get("deepseek_model", "deepseek-chat")
        deepseek_url = self.config.get("deepseek_api_url", "https://api.deepseek.com/v1/chat/completions")
        print(f"[模型调用] 实际调用的DeepSeek模型: {deepseek_model}")
        
        payload = {
            "model": deepseek_model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 2048,
            "stream": False
        }
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        print(f"[LLM调用] 开始生成练习题目")
        print(f"[LLM调用] 输入prompt长度: {len(prompt)}")
        print(f"[LLM调用] 输入内容: {prompt[:300]}...")
        
        self.status.emit(f"正在调用DeepSeek API生成题目 ({deepseek_model})...")
        start_time = time.time()
        response = requests.post(deepseek_url, json=payload, headers=headers, timeout=60)
        response_time = time.time() - start_time
        
        print(f"[LLM调用] DeepSeek响应状态码: {response.status_code}")
        print(f"[LLM调用] 响应时间: {response_time:.2f}秒")
        
        if response.status_code == 200:
            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            print(f"[LLM调用] DeepSeek原始响应内容: {content[:500]}...")
            
            if KNOWLEDGE_INTEGRATION_AVAILABLE:
                log_ollama_call("generate_practice_questions", deepseek_model, prompt, content, response_time=response_time)
            
            self.questionsReady.emit(content)
            self.status.emit("题目生成完成")
        else:
            error_msg = f"DeepSeek API调用失败: {response.status_code} - {response.text}"
            if KNOWLEDGE_INTEGRATION_AVAILABLE:
                log_ollama_call("generate_practice_questions", deepseek_model, prompt, error=error_msg, response_time=response_time)
            raise Exception(error_msg)

    def _generate_with_gemini(self, prompt: str):
        """使用Gemini API生成练习题目"""
        import time
        
        api_key = self.config.get("gemini_api_key", "")
        if not api_key:
            error_msg = "错误: 未配置Gemini API密钥"
            self.status.emit(error_msg)
            if KNOWLEDGE_INTEGRATION_AVAILABLE:
                log_gemini_call("generate_practice_questions", prompt, error=error_msg)
            raise Exception(error_msg)
        
        # 使用用户配置的Gemini模型
        gemini_model = self.config.get("gemini_model", "gemini-1.5-flash-latest")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:generateContent?key={api_key}"
        print(f"[模型调用] 实际调用的Gemini模型: {gemini_model}")
        
        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "temperature": 0.7,
                "topK": 40,
                "topP": 0.95,
                "maxOutputTokens": 2048,
            }
        }
        
        headers = {"Content-Type": "application/json"}
        
        print(f"[LLM调用] 开始生成练习题目")
        print(f"[LLM调用] 输入prompt长度: {len(prompt)}")
        print(f"[LLM调用] 输入内容: {prompt[:300]}...")
        
        self.status.emit("正在调用Gemini API生成题目...")
        start_time = time.time()
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response_time = time.time() - start_time
        
        print(f"[LLM调用] 题目生成API响应状态码: {response.status_code}")
        print(f"[LLM调用] 响应时间: {response_time:.2f}秒")
        
        if response.status_code == 200:
            data = response.json()
            
            # 检查是否有错误信息
            if "error" in data:
                error_info = data["error"]
                error_msg = f"Gemini API错误: {error_info.get('message', '未知错误')}"
                if "QUOTA_EXCEEDED" in str(error_info):
                    error_msg += " (配额已用完，请检查API使用限制)"
                print(f"[LLM调用] {error_msg}")
                if KNOWLEDGE_INTEGRATION_AVAILABLE:
                    log_gemini_call("generate_practice_questions", prompt, error=error_msg, response_time=response_time)
                raise Exception(error_msg)
            
            if "candidates" in data and len(data["candidates"]) > 0:
                content = data["candidates"][0]["content"]["parts"][0]["text"]
                print(f"[LLM调用] 题目生成成功，内容长度: {len(content)}")
                
                if KNOWLEDGE_INTEGRATION_AVAILABLE:
                    log_gemini_call("generate_practice_questions", prompt, content, 
                                  response_time=response_time, config=payload["generationConfig"])
                
                self.questionsReady.emit(content)
                self.status.emit("题目生成完成")
            else:
                error_msg = f"API返回格式异常: {data}"
                print(f"[LLM调用] {error_msg}")
                if KNOWLEDGE_INTEGRATION_AVAILABLE:
                    log_gemini_call("generate_practice_questions", prompt, error=error_msg, response_time=response_time)
                raise Exception(error_msg)
        else:
            error_msg = f"API调用失败: {response.status_code}, 响应: {response.text[:500]}"
            print(f"[LLM调用] {error_msg}")
            if KNOWLEDGE_INTEGRATION_AVAILABLE:
                log_gemini_call("generate_practice_questions", prompt, error=error_msg, response_time=response_time)
            raise Exception(error_msg)
    
    def _generate_with_ollama(self, prompt: str):
        """使用Ollama API生成练习题目"""
        import time
        
        ollama_url = self.config.get("ollama_api_url", "http://localhost:11434/api/generate")
        model = self.config.get("ollama_model", "deepseek-coder")
        
        print(f"[LLM调用] 尝试使用Ollama API: {ollama_url}")
        print(f"[LLM调用] 使用模型: {model}")
        
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.7,
                "top_p": 0.9
            }
        }
        
        self.status.emit(f"正在调用Ollama API生成题目 ({model})...")
        start_time = time.time()
        response = requests.post(ollama_url, json=payload, timeout=60)
        response_time = time.time() - start_time
        
        print(f"[LLM调用] Ollama响应状态码: {response.status_code}")
        print(f"[LLM调用] 响应时间: {response_time:.2f}秒")
        
        if response.status_code == 200:
            data = response.json()
            content = data.get("response", "")
            print(f"[LLM调用] Ollama原始响应内容: {content[:500]}...")
            
            # 处理DeepSeek特有的think标签
            content = self._filter_deepseek_think_content(content)
            print(f"[LLM调用] 过滤think后的内容: {content[:300]}...")
            
            if KNOWLEDGE_INTEGRATION_AVAILABLE:
                log_ollama_call("generate_practice_questions", model, prompt, content, response_time=response_time)
            
            self.questionsReady.emit(content)
            self.status.emit("题目生成完成")
        else:
            # 打印更多上下文帮助定位为何回退到Gemini
            error_msg = f"Ollama API调用失败: {response.status_code}, 响应: {response.text[:500]}"
            if KNOWLEDGE_INTEGRATION_AVAILABLE:
                log_ollama_call("generate_practice_questions", model, prompt, error=error_msg, response_time=response_time)
            raise Exception(error_msg)
    
    def _filter_deepseek_think_content(self, content: str) -> str:
        """过滤DeepSeek模型返回的think标签内容"""
        import re
        
        # 特殊处理：如果内容以<think>开头，直接查找第一个</think>后的内容
        if content.strip().startswith('<think>'):
            think_end = content.find('</think>')
            if think_end != -1:
                filtered_content = content[think_end + 8:].strip()
                print(f"[内容过滤] 检测到内容以<think>开头，直接截取</think>后的内容")
                return filtered_content
        
        # DeepSeek模型会返回<think>...</think>标签，需要过滤掉
        think_patterns = [
            r'<think>.*?</think>',  # 标准think标签
            r'<thinking>.*?</thinking>',  # thinking标签
        ]
        
        filtered_content = content
        for pattern in think_patterns:
            filtered_content = re.sub(pattern, '', filtered_content, flags=re.DOTALL | re.IGNORECASE)
        
        # 清理多余的空行和空格
        filtered_content = re.sub(r'\n\s*\n\s*\n', '\n\n', filtered_content)
        filtered_content = filtered_content.strip()
        
        return filtered_content
    
    def _evaluate_user_answers(self):
        """Evaluate user answers using LLM"""
        self.status.emit("正在评估答案...")
        
        # 评估时要求先罗列原题，再给出用户答案与判定、分析，便于后续错题切片精确抓取原题
        prompt = f"""请作为专业技术面试官，对以下“技术练习答卷”进行严格的逐题评估，并务必按规定的结构化纯文本格式输出。

【背景学习内容】
{self.selected_text}

【试卷原题（严格按原文逐条列出）】
{self.questions_text}

【用户作答（按题号或题目前缀对应）】
{self.user_answers}

【重要的输出要求——务必完全遵守】
1) 全部输出使用纯文本，不要使用任何HTML或Markdown标记。
2) 严格按“逐题报告”结构列出每一道题，且每题包含以下小节，并使用这些准确的小节标题：
   - 原题：
   - 用户答案：
   - 判定：（只能是“正确”/“错误”/“无法判断”三选一）
   - 分析与要点：
3) 每题之间使用一行仅包含“----”的分隔线。
4) 在所有题目之后，给出“整体评价”与“知识点掌握程度评估”，掌握程度评估需包含：
   基础概念理解、实际应用能力、深度思考能力、综合运用能力 四项，各用1-5分表示，并给出一句简要说明。

【请输出】
先输出逐题报告（每题按照“原题/用户答案/判定/分析与要点”的顺序完整展示原题文本），然后输出整体评价与知识点掌握程度评估。
"""
        
        # 根据用户配置选择模型（大小写不敏感），并控制是否允许回退
        llm_provider = str(self.config.get("llm_provider", "Gemini")).strip()
        provider_norm = llm_provider.lower()
        allow_fallback = bool(self.config.get("enable_llm_fallback", False))
        print(f"[模型选择] 评估使用的LLM提供商: {llm_provider} (fallback={'on' if allow_fallback else 'off'})")

        if provider_norm == "deepseek":
            try:
                self._evaluate_with_deepseek(prompt)
            except Exception as deepseek_error:
                print(f"[LLM调用] DeepSeek API失败: {deepseek_error}")
                if not allow_fallback:
                    raise
                print(f"[模型选择] DeepSeek失败，尝试Gemini作为备用")
                try:
                    self._evaluate_with_gemini(prompt)
                except Exception as gemini_error:
                    print(f"[LLM调用] Gemini API也失败: {gemini_error}")
                    if not allow_fallback:
                        raise
                    print(f"[模型选择] Gemini失败，尝试Ollama作为备用")
                    try:
                        self._evaluate_with_ollama(prompt)
                    except Exception as ollama_error:
                        print(f"[LLM调用] Ollama API也失败: {ollama_error}")
                        self.status.emit(f"所有API都失败了: DeepSeek({deepseek_error}), Gemini({gemini_error}), Ollama({ollama_error})")
        elif provider_norm == "gemini":
            try:
                self._evaluate_with_gemini(prompt)
            except Exception as gemini_error:
                print(f"[LLM调用] Gemini API失败: {gemini_error}")
                if not allow_fallback:
                    raise
                print(f"[模型选择] Gemini失败，尝试Ollama作为备用")
                try:
                    self._evaluate_with_ollama(prompt)
                except Exception as ollama_error:
                    print(f"[LLM调用] Ollama API也失败: {ollama_error}")
                    self.status.emit(f"所有API都失败了: Gemini({gemini_error}), Ollama({ollama_error})")
        else:
            # 默认：Ollama
            try:
                self._evaluate_with_ollama(prompt)
            except Exception as ollama_error:
                print(f"[LLM调用] Ollama API失败: {ollama_error}")
                if not allow_fallback:
                    raise
                print(f"[模型选择] Ollama失败，尝试Gemini作为备用")
                try:
                    self._evaluate_with_gemini(prompt)
                except Exception as gemini_error:
                    print(f"[LLM调用] Gemini API也失败: {gemini_error}")
                    self.status.emit(f"所有API都失败了: Ollama({ollama_error}), Gemini({gemini_error})")
    
    def _evaluate_with_deepseek(self, prompt: str):
        """使用DeepSeek API评估答案"""
        import time
        
        api_key = self.config.get("deepseek_api_key", "")
        if not api_key:
            error_msg = "错误: 未配置DeepSeek API密钥"
            self.status.emit(error_msg)
            if KNOWLEDGE_INTEGRATION_AVAILABLE:
                log_ollama_call("evaluate_practice_answers", "deepseek-chat", prompt, error=error_msg)
            raise Exception(error_msg)
        
        # 使用用户配置的DeepSeek模型
        deepseek_model = self.config.get("deepseek_model", "deepseek-chat")
        deepseek_url = self.config.get("deepseek_api_url", "https://api.deepseek.com/v1/chat/completions")
        print(f"[模型调用] 实际调用的DeepSeek模型: {deepseek_model}")
        
        payload = {
            "model": deepseek_model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 3072,
            "stream": False
        }
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        self.status.emit(f"正在调用DeepSeek API评估答案 ({deepseek_model})...")
        start_time = time.time()
        response = requests.post(deepseek_url, json=payload, headers=headers, timeout=60)
        response_time = time.time() - start_time
        
        print(f"[LLM调用] DeepSeek响应状态码: {response.status_code}")
        print(f"[LLM调用] 响应时间: {response_time:.2f}秒")
        
        if response.status_code == 200:
            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            print(f"[LLM调用] DeepSeek原始响应内容: {content[:500]}...")
            
            if KNOWLEDGE_INTEGRATION_AVAILABLE:
                log_ollama_call("evaluate_practice_answers", deepseek_model, prompt, content, response_time=response_time)
            
            self.evaluationReady.emit(content)
            self.status.emit("答案评估完成")
        else:
            error_msg = f"DeepSeek API调用失败: {response.status_code} - {response.text}"
            if KNOWLEDGE_INTEGRATION_AVAILABLE:
                log_ollama_call("evaluate_practice_answers", deepseek_model, prompt, error=error_msg, response_time=response_time)
            raise Exception(error_msg)

    def _evaluate_with_gemini(self, prompt: str):
        """使用Gemini API评估答案"""
        import time
        
        api_key = self.config.get("gemini_api_key", "")
        if not api_key:
            error_msg = "错误: 未配置Gemini API密钥"
            self.status.emit(error_msg)
            if KNOWLEDGE_INTEGRATION_AVAILABLE:
                log_gemini_call("evaluate_practice_answers", prompt, error=error_msg)
            raise Exception(error_msg)
        
        # 使用用户配置的Gemini模型
        gemini_model = self.config.get("gemini_model", "gemini-1.5-flash-latest")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:generateContent?key={api_key}"
        print(f"[模型调用] 实际调用的Gemini模型: {gemini_model}")
        
        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "temperature": 0.3,
                "topK": 40,
                "topP": 0.95,
                "maxOutputTokens": 3072,
            }
        }
        
        headers = {"Content-Type": "application/json"}
        
        self.status.emit("正在调用Gemini API评估答案...")
        start_time = time.time()
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response_time = time.time() - start_time
        
        if response.status_code == 200:
            data = response.json()
            
            # 检查是否有错误信息
            if "error" in data:
                error_info = data["error"]
                error_msg = f"Gemini API错误: {error_info.get('message', '未知错误')}"
                if "QUOTA_EXCEEDED" in str(error_info):
                    error_msg += " (配额已用完，请检查API使用限制)"
                print(f"[LLM调用] {error_msg}")
                if KNOWLEDGE_INTEGRATION_AVAILABLE:
                    log_gemini_call("evaluate_practice_answers", prompt, error=error_msg, response_time=response_time)
                raise Exception(error_msg)
            
            if "candidates" in data and len(data["candidates"]) > 0:
                content = data["candidates"][0]["content"]["parts"][0]["text"]
                
                if KNOWLEDGE_INTEGRATION_AVAILABLE:
                    log_gemini_call("evaluate_practice_answers", prompt, content, 
                                  response_time=response_time, config=payload["generationConfig"])
                
                self.evaluationReady.emit(content)
                self.status.emit("答案评估完成")
            else:
                error_msg = f"API返回格式异常: {data}"
                if KNOWLEDGE_INTEGRATION_AVAILABLE:
                    log_gemini_call("evaluate_practice_answers", prompt, error=error_msg, response_time=response_time)
                raise Exception(error_msg)
        else:
            error_msg = f"API调用失败: {response.status_code}, 响应: {response.text[:500]}"
            if KNOWLEDGE_INTEGRATION_AVAILABLE:
                log_gemini_call("evaluate_practice_answers", prompt, error=error_msg, response_time=response_time)
            raise Exception(error_msg)
    
    def _evaluate_with_ollama(self, prompt: str):
        """使用Ollama API评估答案"""
        import time
        
        ollama_url = self.config.get("ollama_api_url", "http://localhost:11434/api/generate")
        model = self.config.get("ollama_model", "deepseek-coder")
        
        print(f"[LLM调用] 尝试使用Ollama API: {ollama_url}")
        print(f"[LLM调用] 使用模型: {model}")
        
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.3,
                "top_p": 0.9
            }
        }
        
        self.status.emit(f"正在调用Ollama API评估答案 ({model})...")
        start_time = time.time()
        response = requests.post(ollama_url, json=payload, timeout=60)
        response_time = time.time() - start_time
        
        if response.status_code == 200:
            data = response.json()
            content = data.get("response", "")
            
            # 处理DeepSeek特有的think标签
            content = self._filter_deepseek_think_content(content)
            
            if KNOWLEDGE_INTEGRATION_AVAILABLE:
                log_ollama_call("evaluate_practice_answers", model, prompt, content, response_time=response_time)
            
            self.evaluationReady.emit(content)
            self.status.emit("答案评估完成")
        else:
            error_msg = f"Ollama API调用失败: {response.status_code}"
            if KNOWLEDGE_INTEGRATION_AVAILABLE:
                log_ollama_call("evaluate_practice_answers", model, prompt, error=error_msg, response_time=response_time)
            raise Exception(error_msg)


class PracticeHistoryDialog(QDialog):
    """Dialog for managing practice history"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("练习历史")
        self.resize(800, 600)
        self.selected_practice = None
        
        self._setup_ui()
        self._load_practice_history()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Title
        title_label = QLabel("选择要加载的练习历史:")
        title_label.setFont(QFont("微软雅黑", 12, QFont.Weight.Bold))
        layout.addWidget(title_label)
        
        # Practice list
        self.practice_list = QListWidget()
        self.practice_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.practice_list)
        
        # Preview area
        preview_group = QGroupBox("预览")
        preview_layout = QVBoxLayout(preview_group)
        
        self.preview_browser = QTextBrowser()
        self.preview_browser.setMaximumHeight(200)
        preview_layout.addWidget(self.preview_browser)
        
        layout.addWidget(preview_group)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.load_button = QPushButton("加载练习")
        self.load_button.clicked.connect(self._load_selected_practice)
        self.load_button.setEnabled(False)
        
        self.delete_button = QPushButton("删除练习")
        self.delete_button.clicked.connect(self._delete_selected_practice)
        self.delete_button.setEnabled(False)
        
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        
        button_layout.addWidget(self.load_button)
        button_layout.addWidget(self.delete_button)
        button_layout.addStretch()
        button_layout.addWidget(cancel_button)
        
        layout.addLayout(button_layout)
        
        # Connect list selection
        self.practice_list.itemSelectionChanged.connect(self._on_selection_changed)
    
    def _load_practice_history(self):
        """Load practice history from files"""
        try:
            practice_dir = "practice_sessions"
            if not os.path.exists(practice_dir):
                return
            
            practice_files = [f for f in os.listdir(practice_dir) if f.startswith("practice_") and f.endswith(".json")]
            practice_files.sort(reverse=True)  # Most recent first
            
            for filename in practice_files:
                filepath = os.path.join(practice_dir, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        practice_data = json.load(f)
                    
                    # Create list item
                    timestamp = practice_data.get("timestamp", "")
                    practice_id = practice_data.get("practice_id", "")
                    status = practice_data.get("status", "unknown")
                    
                    # Format display text
                    if timestamp:
                        try:
                            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                            time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                        except:
                            time_str = timestamp
                    else:
                        time_str = "未知时间"
                    
                    status_text = {"completed": "已完成", "in_progress": "进行中", "evaluated": "已评估"}.get(status, status)
                    
                    display_text = f"[{status_text}] {time_str} - ID: {practice_id}"
                    
                    item = QListWidgetItem(display_text)
                    item.setData(Qt.ItemDataRole.UserRole, practice_data)
                    self.practice_list.addItem(item)
                    
                except Exception as e:
                    print(f"加载练习文件失败 {filename}: {e}")
                    
        except Exception as e:
            print(f"加载练习历史失败: {e}")
    
    def _on_selection_changed(self):
        """Handle list selection change"""
        current_item = self.practice_list.currentItem()
        if current_item:
            practice_data = current_item.data(Qt.ItemDataRole.UserRole)
            self._show_preview(practice_data)
            self.load_button.setEnabled(True)
            self.delete_button.setEnabled(True)
        else:
            self.preview_browser.clear()
            self.load_button.setEnabled(False)
            self.delete_button.setEnabled(False)
    
    def _show_preview(self, practice_data):
        """Show preview of selected practice"""
        if not practice_data:
            return
        
        selected_text = practice_data.get("selected_text", "")[:200]
        user_answers = practice_data.get("user_answers", practice_data.get("answers", ""))[:300]
        evaluation_result = practice_data.get("evaluation_result", "")[:300]
        
        preview_html = f"""
        <h3>学习内容预览:</h3>
        <p>{selected_text}...</p>
        <h3>用户答案预览:</h3>
        <p>{user_answers}...</p>
        """
        
        if evaluation_result:
            preview_html += f"""
            <h3>评估结果预览:</h3>
            <p>{evaluation_result}...</p>
            """
        
        self.preview_browser.setHtml(preview_html)
    
    def _on_item_double_clicked(self, item):
        """Handle double click on item"""
        self._load_selected_practice()
    
    def _load_selected_practice(self):
        """Load selected practice"""
        current_item = self.practice_list.currentItem()
        if current_item:
            self.selected_practice = current_item.data(Qt.ItemDataRole.UserRole)
            self.accept()
    
    def _delete_selected_practice(self):
        """Delete selected practice"""
        current_item = self.practice_list.currentItem()
        if not current_item:
            return
        
        practice_data = current_item.data(Qt.ItemDataRole.UserRole)
        practice_id = practice_data.get("practice_id", "")
        
        reply = QMessageBox.question(
            self, "确认删除", 
            f"确定要删除练习 {practice_id} 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                # Delete file
                filename = f"practice_{practice_id}.json"
                filepath = os.path.join("practice_sessions", filename)
                if os.path.exists(filepath):
                    os.remove(filepath)
                
                # Remove from list
                row = self.practice_list.row(current_item)
                self.practice_list.takeItem(row)
                
            except Exception as e:
                QMessageBox.warning(self, "删除失败", f"删除练习失败: {e}")
    
    def get_selected_practice(self):
        """Get selected practice data"""
        return self.selected_practice


class PracticePanel(QDialog):
    """Practice panel for generating and solving practice questions"""
    
    def __init__(self, selected_text: str, insert_position: int, config: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("技术练习面板")
        self.resize(1000, 800)
        
        # Set window flags to make it a proper window (like ChatbotPanel)
        # 初始短暂置顶，确保从对话框/其他面板打开时也能在最前显示；
        # 启用标准标题栏按钮（包含关闭按钮）
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        
        # Set background color to avoid transparency
        self.setStyleSheet("QWidget { background-color: #f0f0f0; }")
        
        self.selected_text = selected_text
        self.insert_position = insert_position
        self.config = config
        self.practice_id = self._generate_practice_id()
        self.practice_history = []
        self.evaluation_result = ""
        # 标记当前是否处于“初始置顶期”，用于在首个交互后撤销置顶
        self._initial_aot_active = True
        self.current_questions = ""
        self.current_answers = ""
        self.user_answers_before_evaluation = ""
        # Track submit button mode to avoid redundant disconnect warnings
        self._submit_mode = None

        # Setup UI
        self._setup_ui()
        
        # Only start generating questions if not loading from history
        self._loading_from_history = False
        if not self._loading_from_history and self.selected_text.strip():
            self._generate_questions()

        # 显示后将窗口前置；在用户首次交互前保持置顶，防止被上一窗口立即遮挡
        try:
            # 多次尝试前置，增强稳健性（应对不同平台/窗口管理器）
            QTimer.singleShot(0, self._bring_to_front)
            QTimer.singleShot(300, self._bring_to_front)
            QTimer.singleShot(1000, self._bring_to_front)
            # 安全超时：最长 15 秒后自动撤销置顶，防止极端情况下一直置顶
            QTimer.singleShot(15000, self._drop_always_on_top)
        except Exception:
            pass

    def _bring_to_front(self):
        try:
            self.raise_()
            self.activateWindow()
        except Exception:
            pass

    def _drop_always_on_top(self):
        try:
            if not getattr(self, "_initial_aot_active", False):
                return
            if self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint:
                self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowStaysOnTopHint)
                # 变更窗口标志后需要调用 show() 使其生效
                self.show()
            # 标记初始置顶期结束
            self._initial_aot_active = False
        except Exception:
            pass

    # 用户第一次点击或键盘输入后，短延迟撤销置顶，保证先拿到焦点
    def mousePressEvent(self, event):  # type: ignore[override]
        try:
            if getattr(self, "_initial_aot_active", False):
                QTimer.singleShot(200, self._drop_always_on_top)
        except Exception:
            pass
        super().mousePressEvent(event)

    def keyPressEvent(self, event):  # type: ignore[override]
        try:
            if getattr(self, "_initial_aot_active", False):
                QTimer.singleShot(200, self._drop_always_on_top)
        except Exception:
            pass
        super().keyPressEvent(event)

    def showEvent(self, event):  # type: ignore[override]
        """Ensure the panel gets focus and the answer editor is ready for input."""
        try:
            QTimer.singleShot(0, self._ensure_focus_ready)
        except Exception:
            pass
        super().showEvent(event)

    def _ensure_focus_ready(self):
        try:
            self.raise_()
            self.activateWindow()
            if hasattr(self, 'answer_editor') and self.answer_editor:
                self.answer_editor.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        except Exception:
            pass
    
    def _generate_practice_id(self):
        """Generate unique practice ID"""
        return datetime.now().strftime('%Y%m%d_%H%M%S')
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Toolbar with controls (similar to ChatbotPanel)
        toolbar_layout = QHBoxLayout()
        
        self.history_button = QPushButton("练习历史")
        self.history_button.clicked.connect(self._show_history)
        toolbar_layout.addWidget(self.history_button)
        
        self.new_practice_button = QPushButton("新练习")
        self.new_practice_button.clicked.connect(self._start_new_practice)
        toolbar_layout.addWidget(self.new_practice_button)
        
        self.regenerate_btn = QPushButton("重新生成题目")
        self.regenerate_btn.clicked.connect(self._regenerate_questions)
        self.regenerate_btn.setEnabled(False)
        toolbar_layout.addWidget(self.regenerate_btn)
        
        self.submit_btn = QPushButton("提交练习")
        self.submit_btn.clicked.connect(self._submit_practice)
        self.submit_btn.setEnabled(False)
        toolbar_layout.addWidget(self.submit_btn)

        # 错题入库按钮（仅当有评估结果时可用）
        self.error_import_btn = QPushButton("错题入库")
        self.error_import_btn.setEnabled(False)
        self.error_import_btn.clicked.connect(self._open_error_import_dialog)
        toolbar_layout.addWidget(self.error_import_btn)
        
        toolbar_layout.addStretch()
        
        self.practice_label = QLabel(f"练习ID: {self.practice_id}")
        self.practice_label.setStyleSheet("color: #666; font-size: 10px;")
        toolbar_layout.addWidget(self.practice_label)
        
        layout.addLayout(toolbar_layout)
        
        # Status bar
        self.status_label = QLabel("正在生成练习题目...")
        self.status_label.setStyleSheet("color: #666; padding: 5px;")
        layout.addWidget(self.status_label)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminate progress
        layout.addWidget(self.progress_bar)
        
        # Main practice area (similar to ChatbotPanel's chat area)
        practice_group = QGroupBox("技术练习")
        practice_layout = QVBoxLayout(practice_group)
        
        # Practice display using text browser for better plain text formatting
        self.practice_display = QTextBrowser()
        self.practice_display.setFont(QFont("微软雅黑", 11))
        self.practice_display.setStyleSheet("""
            QTextBrowser {
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 8px;
                padding: 15px;
                line-height: 1.6;
            }
        """)
        practice_layout.addWidget(self.practice_display)
        
        # Answer editor for user input
        answer_group = QGroupBox("答题区域")
        answer_layout = QVBoxLayout(answer_group)
        
        self.answer_editor = QTextEdit()
        self.answer_editor.setPlaceholderText("请在此处填写您的答案...\n\n提示：\n- 选择题请写明题号和选项，如：1. A\n- 填空题请写明题号和答案，如：2. 答案内容\n- 简答题请详细作答")
        self.answer_editor.setFont(QFont("微软雅黑", 11))
        self.answer_editor.setMaximumHeight(250)
        self.answer_editor.setStyleSheet("""
            QTextEdit {
                border: 1px solid #ced4da;
                border-radius: 6px;
                padding: 10px;
                background-color: white;
            }
        """)
        answer_layout.addWidget(self.answer_editor)
        
        practice_layout.addWidget(answer_group)
        
        layout.addWidget(practice_group)
        
        # Original content display (collapsible, collapsed by default)
        self.content_group = QGroupBox("学习内容 (点击展开/收缩)")
        self.content_group.setCheckable(True)
        self.content_group.setChecked(False)  # Collapsed by default
        content_layout = QVBoxLayout(self.content_group)
        
        self.content_display = QTextEdit()
        self.content_display.setReadOnly(True)
        self.content_display.setPlainText(self.selected_text)
        self.content_display.setMaximumHeight(150)  # Limit height when expanded
        self.content_display.setFont(QFont("微软雅黑", 9))
        content_layout.addWidget(self.content_display)
        
        # Connect toggle signal
        self.content_group.toggled.connect(self._toggle_content_display)
        
        layout.addWidget(self.content_group)
        
        # Bottom buttons (similar to ChatbotPanel)
        bottom_layout = QHBoxLayout()
        
        save_button = QPushButton("保存练习")
        save_button.clicked.connect(self._save_practice)
        bottom_layout.addWidget(save_button)
        
        bottom_layout.addStretch()
        
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.close)
        bottom_layout.addWidget(close_button)
        
        layout.addLayout(bottom_layout)
        
        # Setup worker thread
        self.worker_thread = QThread()
        self.worker = PracticeWorker(self.config)
        self.worker.moveToThread(self.worker_thread)
        
        # Connect signals
        self.worker.questionsReady.connect(self._on_questions_ready)
        self.worker.evaluationReady.connect(self._on_evaluation_ready)
        self.worker.status.connect(self._on_status_update)
        self.worker.finished.connect(self._on_worker_finished)
        
        self.worker_thread.started.connect(self.worker.start_work)
    
    def update_config(self, new_config: dict):
        """动态更新配置，确保练习面板感知模型切换"""
        self.config = new_config
        if hasattr(self, 'worker') and self.worker:
            self.worker.update_config(new_config)
        print(f"[配置更新] PracticePanel配置已更新，LLM提供商: {self.config.get('llm_provider', 'Gemini')}")
    
    def _toggle_content_display(self, checked):
        """Toggle the visibility of content display"""
        self.content_display.setVisible(checked)
        if checked:
            self.content_group.setTitle("学习内容 (点击收缩)")
        else:
            self.content_group.setTitle("学习内容 (点击展开)")
    
    def _generate_questions(self):
        """Generate practice questions"""
        # 确保读取到最新配置（例如模型切换）
        try:
            with open('app_config.json', 'r', encoding='utf-8') as f:
                latest = json.load(f)
                self.update_config(latest)
        except Exception as e:
            print(f"[配置] 加载最新配置失败，继续使用内存配置: {e}")
        self.status_label.setText("正在生成练习题目...")
        self.progress_bar.show()
        self.regenerate_btn.setEnabled(False)
        self.submit_btn.setEnabled(False)
        
        # 防重复启动：若线程或任务仍在运行，直接忽略
        if self.worker_thread.isRunning() or getattr(self.worker, "running", False):
            self.status_label.setText("已有任务在进行中，请稍候…")
            return
        # 额外打印当前提供商用于排查
        try:
            print(f"[模型选择] 生成题目前的提供商: {self.config.get('llm_provider')}")
        except Exception:
            pass
        self.worker.generate_questions(self.selected_text)
        self.worker_thread.start()
    
    def _regenerate_questions(self):
        """Regenerate practice questions"""
        self._generate_questions()
    
    def _submit_practice(self):
        """Submit practice for evaluation"""
        user_answers = self.answer_editor.toPlainText().strip()
        if not user_answers:
            QMessageBox.warning(self, "提示", "请先完成练习题目再提交。")
            return
        
        # Save user answers before evaluation
        self.user_answers_before_evaluation = user_answers
        self._start_evaluation(user_answers)

    def _save_only(self):
        """只保存当前评估结果与练习内容，不触发二次评估"""
        # 直接走保存与知识库集成
        self._save_practice_with_evaluation()
        self.status_label.setText("评估结果已保存")

    def _disconnect_submit(self):
        """安全断开 submit 按钮所有已知连接，避免重复绑定"""
        # 仅按当前模式断开，减少 PySide 的 RuntimeWarning 噪音
        mode = getattr(self, "_submit_mode", None)
        # 首次未设置模式时，不进行任何断开操作，避免 Qt 发出 Failed to disconnect 警告
        if mode is None:
            return
        if mode == "evaluate":
            try:
                self.submit_btn.clicked.disconnect(self._submit_practice)
            except Exception:
                pass
        elif mode == "save":
            try:
                self.submit_btn.clicked.disconnect(self._save_only)
            except Exception:
                pass
        else:
            # 未知状态（理论不出现），稳妥返回
            return

    def _set_submit_mode_evaluate(self):
        """设置提交按钮为‘提交练习’模式：触发一次评估"""
        self._disconnect_submit()
        self.submit_btn.setText("提交练习")
        self.submit_btn.setEnabled(True)
        self.submit_btn.clicked.connect(self._submit_practice)
        self._submit_mode = "evaluate"

    def _set_submit_mode_save(self):
        """设置提交按钮为‘保存评估结果’模式：仅保存不评估"""
        self._disconnect_submit()
        self.submit_btn.setText("保存评估结果")
        self.submit_btn.setEnabled(True)
        self.submit_btn.clicked.connect(self._save_only)
        self._submit_mode = "save"
    
    def _extract_answers_from_html(self):
        """Extract answers from HTML form using JavaScript"""
        js_code = """
        function collectAnswers() {
            var answers = {};
            
            // Collect radio button answers
            var radios = document.querySelectorAll('input[type="radio"]:checked');
            radios.forEach(function(radio) {
                answers[radio.name] = radio.value;
            });
            
            // Collect checkbox answers
            var checkboxes = document.querySelectorAll('input[type="checkbox"]:checked');
            checkboxes.forEach(function(checkbox) {
                if (!answers[checkbox.name]) {
                    answers[checkbox.name] = [];
                }
                answers[checkbox.name].push(checkbox.value);
            });
            
            // Collect text input answers
            var textInputs = document.querySelectorAll('input[type="text"]');
            textInputs.forEach(function(input) {
                if (input.value.trim()) {
                    answers[input.name] = input.value.trim();
                }
            });
            
            // Collect textarea answers
            var textareas = document.querySelectorAll('textarea');
            textareas.forEach(function(textarea) {
                if (textarea.value.trim()) {
                    answers[textarea.name] = textarea.value.trim();
                }
            });
            
            return JSON.stringify(answers);
        }
        collectAnswers();
        """
        
        self.practice_display.page().runJavaScript(js_code, self._on_answers_extracted)
    
    def _on_answers_extracted(self, answers_json):
        """Handle extracted answers from JavaScript"""
        try:
            import json
            answers_dict = json.loads(answers_json) if answers_json else {}
            
            if not answers_dict:
                QMessageBox.warning(self, "提示", "请先完成练习题目再提交。")
                return
            
            # Format answers for evaluation
            user_answers = ""
            for question_name, answer in answers_dict.items():
                if isinstance(answer, list):
                    user_answers += f"{question_name}: {', '.join(answer)}\n"
                else:
                    user_answers += f"{question_name}: {answer}\n"
            
            self.user_answers_before_evaluation = user_answers
            self._start_evaluation(user_answers)
            
        except Exception as e:
            QMessageBox.warning(self, "错误", f"提取答案时出错: {e}")
    
    def _start_evaluation(self, user_answers):
        """Start the evaluation process"""
        # 确保读取到最新配置（例如模型切换）
        try:
            with open('app_config.json', 'r', encoding='utf-8') as f:
                latest = json.load(f)
                self.update_config(latest)
        except Exception as e:
            print(f"[配置] 加载最新配置失败，继续使用内存配置: {e}")
        self.status_label.setText("正在评估答案...")
        self.progress_bar.show()
        self.regenerate_btn.setEnabled(False)
        self.submit_btn.setEnabled(False)
        
        # 防重复启动：若线程或任务仍在运行，直接忽略
        if self.worker_thread.isRunning() or getattr(self.worker, "running", False):
            self.status_label.setText("已有任务在进行中，请稍候…")
            return
        # 传入完整题目文本，评估报告可按“原题/用户答案/判定/分析”结构输出
        self.worker.evaluate_answers(self.selected_text, self.current_questions, user_answers)
        self.worker_thread.start()
    
    def _on_questions_ready(self, questions: str):
        """Handle generated questions"""
        self.current_questions = questions
        
        # Format plain text for better display
        formatted_text = self._format_plain_text(questions)
        
        # Display formatted plain text questions
        self.practice_display.setPlainText(formatted_text)
        # 题目就绪 -> 按钮应处于“提交评估”模式
        self._set_submit_mode_evaluate()
        
    def _format_plain_text(self, content: str) -> str:
        """Format plain text content for better readability"""
        import re
        
        # Remove common LLM response prefixes and suffixes
        prefixes_to_remove = [
            r'好的！以下是.*?：\s*',
            r'以下是.*?：\s*',
            r'这是.*?：\s*',
            r'根据.*?，以下是.*?：\s*'
        ]
        
        for prefix in prefixes_to_remove:
            content = re.sub(prefix, '', content, flags=re.IGNORECASE | re.DOTALL)
        
        # Remove trailing explanations
        suffixes_to_remove = [
            r'\s*这个设计包含：.*',
            r'\s*如果你需要.*',
            r'\s*请告诉我.*'
        ]
        
        for suffix in suffixes_to_remove:
            content = re.sub(suffix, '', content, flags=re.IGNORECASE | re.DOTALL)
        
        # Clean up extra whitespace and ensure proper spacing
        content = re.sub(r'\n\s*\n\s*\n', '\n\n', content)  # Remove excessive blank lines
        content = content.strip()
        
        # Add some formatting improvements
        lines = content.split('\n')
        formatted_lines = []
        
        for line in lines:
            line = line.strip()
            if line:
                # Add extra spacing after question numbers
                if re.match(r'^\d+\.', line):
                    if formatted_lines and formatted_lines[-1]:  # Add blank line before new question
                        formatted_lines.append('')
                    formatted_lines.append(line)
                # Add indentation for options
                elif re.match(r'^[A-D]\)', line):
                    formatted_lines.append('    ' + line)
                else:
                    formatted_lines.append(line)
            else:
                formatted_lines.append('')
        
        return '\n'.join(formatted_lines)
        
    def _clean_html_content(self, content: str) -> str:
        """Clean HTML content by removing markdown code blocks and extra text"""
        import re
        
        # Remove markdown code blocks
        content = re.sub(r'```html\s*', '', content, flags=re.IGNORECASE)
        content = re.sub(r'```\s*', '', content)
        
        # Remove common LLM response prefixes
        prefixes_to_remove = [
            r'好的！以下是.*?：\s*',
            r'以下是.*?：\s*',
            r'这是.*?：\s*',
            r'根据.*?，以下是.*?：\s*'
        ]
        
        for prefix in prefixes_to_remove:
            content = re.sub(prefix, '', content, flags=re.IGNORECASE | re.DOTALL)
        
        # Remove trailing explanations
        suffixes_to_remove = [
            r'\s*这个设计包含：.*',
            r'\s*如果你需要.*',
            r'\s*请告诉我.*'
        ]
        
        for suffix in suffixes_to_remove:
            content = re.sub(suffix, '', content, flags=re.IGNORECASE | re.DOTALL)
        
        # Ensure it starts with <!DOCTYPE html> or <html>
        content = content.strip()
        if not content.lower().startswith(('<!doctype html>', '<html>')):
            # If it doesn't start properly, try to find the HTML start
            html_match = re.search(r'<!DOCTYPE html>|<html[^>]*>', content, re.IGNORECASE)
            if html_match:
                content = content[html_match.start():]
        
        return content.strip()
        
    def _on_evaluation_ready(self, evaluation: str):
        """Handle evaluation results"""
        self.evaluation_result = evaluation
        
        # Format and show evaluation in plain text
        formatted_evaluation = self._format_plain_text(evaluation)
        self.practice_display.setPlainText(formatted_evaluation)
        
        # Add option to start new practice
        self.regenerate_btn.setText("开始新练习")
        # 评估完成 -> 提交按钮切换为“保存评估结果”且仅保存不二次评估
        self.submit_btn.setText("保存评估结果")
        self._set_submit_mode_save()
        
        # Auto-save the evaluation result
        self._save_practice_with_evaluation()

        # 启用“错题入库”按钮
        if hasattr(self, 'error_import_btn'):
            self.error_import_btn.setEnabled(True)
        
    def _save_practice(self):
        """Save practice content"""
        try:
            import os
            import json
            from datetime import datetime
            
            # Create practice directory if it doesn't exist
            practice_dir = "practice_sessions"
            os.makedirs(practice_dir, exist_ok=True)
            
            # Determine status and current answers
            current_content = self.answer_editor.toPlainText()
            status = "in_progress"
            current_answers = ""
            
            if self.evaluation_result:
                status = "evaluated"
                # Use the saved user answers from before evaluation
                current_answers = self.user_answers_before_evaluation or self.current_answers
            elif self.current_questions and current_content != self.current_questions:
                status = "completed"
                current_answers = current_content
            else:
                current_answers = current_content if current_content != self.current_questions else ""
            
            # Save practice data with both user answers and evaluation results
            practice_data = {
                "practice_id": self.practice_id,
                "timestamp": datetime.now().isoformat(),
                "selected_text": self.selected_text,
                "questions": self.current_questions,
                "user_answers": current_answers,  # Always save user's original answers
                "evaluation_result": self.evaluation_result,  # Always save evaluation if exists
                "practice_content": current_content,  # Current display content
                "status": status
            }
            
            filename = os.path.join(practice_dir, f"practice_{self.practice_id}.json")
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(practice_data, f, ensure_ascii=False, indent=2)
            
            self.status_label.setText(f"练习已保存: {filename}")
            
        except Exception as e:
            self.status_label.setText(f"保存失败: {e}")
    
    def _save_practice_with_evaluation(self):
        """Save practice with evaluation results"""
        # Keep the user answers that were submitted for evaluation
        self.current_answers = self.user_answers_before_evaluation
        self._save_practice()
        
        # Integrate with knowledge management system
        self._integrate_with_knowledge_system()
    
    def _on_status_update(self, status: str):
        """Handle status updates"""
        self.status_label.setText(status)
    
    def _on_worker_finished(self):
        """Handle worker finished"""
        self.progress_bar.hide()
        self.regenerate_btn.setEnabled(True)
        self.submit_btn.setEnabled(True)
        # 确保线程在本次任务结束后正确停止，避免后续操作被 isRunning() 阻塞
        try:
            if self.worker_thread.isRunning():
                self.worker_thread.quit()
                self.worker_thread.wait()
        except Exception:
            pass

    def _integrate_with_knowledge_system(self):
        """Integrate practice results with knowledge management system"""
        if not KNOWLEDGE_INTEGRATION_AVAILABLE:
            return

        try:
            # Compose practice content including full questions and user answers for robust slicing
            questions_block = (self.current_questions or "").strip()
            practice_content = (
                f"学习内容: {self.selected_text}\n\n"
                f"题目:\n{questions_block}\n\n"
                f"题目和答案:\n{self.user_answers_before_evaluation}"
            )
            evaluation_result = self.evaluation_result

            if not practice_content or not evaluation_result:
                return

            processor = EnhancedPracticeProcessor(self.config)
            result = processor.process_practice_results(
                practice_content, evaluation_result, self.selected_text, self.parent()
            )

            if result.get("success"):
                message = f"练习已保存并集成到知识库 - {result['message']}"
                self.status_label.setText(message)
                print(f"知识管理集成成功: {result}")
            else:
                print(f"知识管理集成失败: {result.get('message')}")
        except Exception as e:
            print(f"知识管理集成异常: {e}")
    
    def _show_history(self):
        """Show practice history dialog"""
        dialog = PracticeHistoryDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected_practice = dialog.get_selected_practice()
            if selected_practice:
                self._load_practice(selected_practice)
    
    def _load_practice(self, practice_data):
        """Load a practice from history"""
        self._loading_from_history = True
        
        # Update practice data
        self.practice_id = practice_data.get("practice_id", self._generate_practice_id())
        self.selected_text = practice_data.get("selected_text", "")
        self.current_questions = practice_data.get("questions", "")
        self.current_answers = practice_data.get("user_answers", practice_data.get("answers", ""))  # Support both old and new format
        self.evaluation_result = practice_data.get("evaluation_result", "")
        self.user_answers_before_evaluation = self.current_answers
        
        # Update UI
        self.practice_label.setText(f"练习ID: {self.practice_id}")
        self.content_display.setPlainText(self.selected_text)
        
        # Load appropriate content based on status
        status = practice_data.get("status", "")
        if status == "evaluated" and self.evaluation_result:
            formatted_evaluation = self._format_plain_text(self.evaluation_result)
            self.practice_display.setPlainText(formatted_evaluation)
            self.regenerate_btn.setText("开始新练习")
            # 已评估的历史记录 -> 提交按钮应为保存模式
            self.submit_btn.setText("保存评估结果")
            self._set_submit_mode_save()
            if hasattr(self, 'error_import_btn'):
                self.error_import_btn.setEnabled(True)
        elif self.current_questions:
            # Show questions in plain text format
            formatted_questions = self._format_plain_text(self.current_questions)
            self.practice_display.setPlainText(formatted_questions)
            if self.current_answers:
                self.answer_editor.setPlainText(self.current_answers)
            self.regenerate_btn.setEnabled(True)
            self.submit_btn.setEnabled(True)
            self._set_submit_mode_evaluate()
        else:
            # Load practice content as fallback
            practice_content = practice_data.get("practice_content", "")
            formatted_content = self._format_plain_text(practice_content)
            self.practice_display.setPlainText(formatted_content)
        
        self.status_label.setText(f"已加载练习: {self.practice_id}")

    def _open_error_import_dialog(self):
        """打开错题入库面板：从当前评估报告中切片并允许调整后入库"""
        if not self.evaluation_result:
            QMessageBox.information(self, "提示", "请先完成评估后再入库错题。")
            return
        # 组装用于切片的 practice_content：包含学习内容与用户答案
        questions_block = (self.current_questions or "").strip()
        practice_content = (
            f"学习内容: {self.selected_text}\n\n"
            f"题目:\n{questions_block}\n\n"
            f"题目和答案:\n{self.user_answers_before_evaluation}"
        )
        try:
            dlg = ErrorImportDialog(self.config, practice_content, self.evaluation_result, self.selected_text, self)
            dlg.exec()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"打开错题入库面板失败：{e}")
    
    def _start_new_practice(self):
        """Start a new practice session"""
        # Save current practice if it has content
        if self.answer_editor.toPlainText().strip():
            self._save_practice()
        
        # Reset practice state
        self.practice_id = self._generate_practice_id()
        self.practice_label.setText(f"练习ID: {self.practice_id}")
        self.current_questions = ""
        self.current_answers = ""
        self.evaluation_result = ""
        self.user_answers_before_evaluation = ""
        
        # Clear display
        self.answer_editor.clear()
        self.practice_display.clear()
        
        # Reset buttons
        self.regenerate_btn.setText("重新生成题目")
        self._set_submit_mode_evaluate()
        
        # Start new practice with selected text - questions will be generated automatically
    
    def closeEvent(self, event):
        """Handle window close event"""
        # Auto-save before closing if there's content
        if self.answer_editor.toPlainText().strip():
            self._save_practice()
        
        if self.worker_thread.isRunning():
            self.worker_thread.quit()
            self.worker_thread.wait()
        super().closeEvent(event)
