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
        self.user_answers = ""
        self.mode = "generate"  # "generate" or "evaluate"
    
    def update_config(self, new_config: dict):
        """动态更新配置"""
        self.config = new_config
        print(f"[配置更新] PracticeWorker配置已更新，LLM提供商: {self.config.get('llm_provider', 'Gemini')}")
    
    def generate_questions(self, selected_text: str):
        """Generate practice questions based on selected text"""
        self.selected_text = selected_text
        self.mode = "generate"
        self.start_work()
    
    def evaluate_answers(self, selected_text: str, user_answers: str):
        """Evaluate user answers and provide explanations"""
        self.selected_text = selected_text
        self.user_answers = user_answers
        self.mode = "evaluate"
        self.start_work()
    
    def start_work(self):
        """Start the work based on mode"""
        try:
            if self.mode == "generate":
                self._generate_practice_questions()
            elif self.mode == "evaluate":
                self._evaluate_user_answers()
        except Exception as e:
            self.status.emit(f"处理错误: {e}")
        finally:
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

        # 根据用户配置选择模型
        llm_provider = self.config.get("llm_provider", "Gemini")
        print(f"[模型选择] 练习面板使用的LLM提供商: {llm_provider}")
        
        if llm_provider == "DeepSeek":
            print(f"[模型选择] 使用DeepSeek模型: {self.config.get('deepseek_model', 'deepseek-chat')}")
            try:
                self._generate_with_deepseek(prompt)
            except Exception as deepseek_error:
                print(f"[LLM调用] DeepSeek API失败: {deepseek_error}")
                print(f"[模型选择] DeepSeek失败，尝试Gemini作为备用")
                try:
                    self._generate_with_gemini(prompt)
                except Exception as gemini_error:
                    print(f"[LLM调用] Gemini API也失败: {gemini_error}")
                    print(f"[模型选择] Gemini失败，尝试Ollama作为备用")
                    try:
                        self._generate_with_ollama(prompt)
                    except Exception as ollama_error:
                        print(f"[LLM调用] Ollama API也失败: {ollama_error}")
                        self.status.emit(f"所有API都失败了: DeepSeek({deepseek_error}), Gemini({gemini_error}), Ollama({ollama_error})")
        elif llm_provider == "Gemini":
            print(f"[模型选择] 使用Gemini模型: {self.config.get('gemini_model', 'gemini-1.5-flash-latest')}")
            try:
                self._generate_with_gemini(prompt)
            except Exception as gemini_error:
                print(f"[LLM调用] Gemini API失败: {gemini_error}")
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
            error_msg = f"Ollama API调用失败: {response.status_code}"
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
        
        prompt = f"""请作为专业技术面试官，对以下用户答案进行评估和讲解。

原始学习内容：
{self.selected_text}

用户的答题内容：
{self.user_answers}

请按以下格式提供纯文本评估报告：

**重要要求：**
1. 使用纯文本格式输出，不要使用HTML或Markdown格式
2. 结构清晰，使用适当的分隔线和空行
3. 包含以下部分：
   - 整体评价
   - 逐题分析
   - 知识点掌握程度评估（1-5分制）
   - 改进建议和学习重点

请生成纯文本格式的评估报告："""

        # 根据用户配置选择模型
        llm_provider = self.config.get("llm_provider", "DeepSeek")
        print(f"[模型选择] 练习评估使用的LLM提供商: {llm_provider}")
        
        if llm_provider == "DeepSeek":
            print(f"[模型选择] 使用DeepSeek模型: {self.config.get('deepseek_model', 'deepseek-chat')}")
            try:
                self._evaluate_with_deepseek(prompt)
            except Exception as deepseek_error:
                print(f"[LLM调用] DeepSeek API失败: {deepseek_error}")
                print(f"[模型选择] DeepSeek失败，尝试Gemini作为备用")
                try:
                    self._evaluate_with_gemini(prompt)
                except Exception as gemini_error:
                    print(f"[LLM调用] Gemini API也失败: {gemini_error}")
                    print(f"[模型选择] Gemini失败，尝试Ollama作为备用")
                    try:
                        self._evaluate_with_ollama(prompt)
                    except Exception as ollama_error:
                        print(f"[LLM调用] Ollama API也失败: {ollama_error}")
                        self.status.emit(f"所有API都失败了: DeepSeek({deepseek_error}), Gemini({gemini_error}), Ollama({ollama_error})")
        elif llm_provider == "Gemini":
            print(f"[模型选择] 使用Gemini模型: {self.config.get('gemini_model', 'gemini-1.5-flash-latest')}")
            try:
                self._evaluate_with_gemini(prompt)
            except Exception as gemini_error:
                print(f"[LLM调用] Gemini API失败: {gemini_error}")
                print(f"[模型选择] Gemini失败，尝试Ollama作为备用")
                try:
                    self._evaluate_with_ollama(prompt)
                except Exception as ollama_error:
                    print(f"[LLM调用] Ollama API也失败: {ollama_error}")
                    self.status.emit(f"所有API都失败了: Gemini({gemini_error}), Ollama({ollama_error})")
        else:
            print(f"[模型选择] 使用Ollama模型: {self.config.get('ollama_model', 'deepseek-coder')}")
            try:
                self._evaluate_with_ollama(prompt)
            except Exception as ollama_error:
                print(f"[LLM调用] Ollama API失败: {ollama_error}")
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


class PracticePanel(QWidget):
    """Practice panel for generating and solving practice questions"""
    
    def __init__(self, selected_text: str, insert_position: int, config: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("技术练习面板")
        self.resize(1000, 800)
        
        # Set window flags to make it a proper window (like ChatbotPanel)
        self.setWindowFlags(Qt.WindowType.Window)
        
        # Set background color to avoid transparency
        self.setStyleSheet("QWidget { background-color: #f0f0f0; }")
        
        self.selected_text = selected_text
        self.insert_position = insert_position
        self.config = config
        self.practice_id = self._generate_practice_id()
        self.practice_history = []
        self.evaluation_result = ""
        self.current_questions = ""
        self.current_answers = ""
        self.user_answers_before_evaluation = ""
        
        # Setup UI
        self._setup_ui()
        
        # Only start generating questions if not loading from history
        self._loading_from_history = False
        if not self._loading_from_history and self.selected_text.strip():
            self._generate_questions()
    
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
        self.status_label.setText("正在生成练习题目...")
        self.progress_bar.show()
        self.regenerate_btn.setEnabled(False)
        self.submit_btn.setEnabled(False)
        
        if not self.worker_thread.isRunning():
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
        
        self.status_label.setText("正在评估答案...")
        self.progress_bar.show()
        self.regenerate_btn.setEnabled(False)
        self.submit_btn.setEnabled(False)
        
        if not self.worker_thread.isRunning():
            self.worker.evaluate_answers(self.selected_text, user_answers)
            self.worker_thread.start()
    
    def _on_questions_ready(self, questions: str):
        """Handle generated questions"""
        self.current_questions = questions
        
        # Format plain text for better display
        formatted_text = self._format_plain_text(questions)
        
        # Display formatted plain text questions
        self.practice_display.setPlainText(formatted_text)
        
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
        self.submit_btn.setText("保存评估结果")
        
        # Auto-save the evaluation result
        self._save_practice_with_evaluation()
        
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
        
        if self.worker_thread.isRunning():
            self.worker_thread.quit()
            self.worker_thread.wait()
    
    def _integrate_with_knowledge_system(self):
        """Integrate practice results with knowledge management system"""
        if not KNOWLEDGE_INTEGRATION_AVAILABLE:
            return
        
        try:
            # Get practice content and evaluation
            practice_content = f"学习内容: {self.selected_text}\n\n题目和答案:\n{self.user_answers_before_evaluation}"
            evaluation_result = self.evaluation_result
            
            if not practice_content or not evaluation_result:
                return
            
            # Initialize enhanced practice processor
            processor = EnhancedPracticeProcessor(self.config)
            
            # Process the completed practice with error question slicing and knowledge point matching
            result = processor.process_practice_results(
                practice_content, evaluation_result, self.selected_text, self.parent()
            )
            
            if result["success"]:
                # Update status with integration results
                message = f"练习已保存并集成到知识库 - {result['message']}"
                self.status_label.setText(message)
                
                # Log the integration results
                print(f"知识管理集成成功: {result}")
            else:
                print(f"知识管理集成失败: {result['message']}")
                
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
            self.submit_btn.setText("保存评估结果")
        elif self.current_questions:
            # Show questions in plain text format
            formatted_questions = self._format_plain_text(self.current_questions)
            self.practice_display.setPlainText(formatted_questions)
            if self.current_answers:
                self.answer_editor.setPlainText(self.current_answers)
            self.regenerate_btn.setEnabled(True)
            self.submit_btn.setEnabled(True)
        else:
            # Load practice content as fallback
            practice_content = practice_data.get("practice_content", "")
            formatted_content = self._format_plain_text(practice_content)
            self.practice_display.setPlainText(formatted_content)
        
        self.status_label.setText(f"已加载练习: {self.practice_id}")
    
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
        self.submit_btn.setText("提交练习")
        
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
