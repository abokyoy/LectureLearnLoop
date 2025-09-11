import tkinter as tk
from tkinter import scrolledtext, messagebox, filedialog, ttk
import threading
import queue
import os
import time
import wave
import pyaudio
import numpy as np
import torch
import whisper
import requests
import json
import re
import random

# 导入配置文件

# 导入配置文件
from config import SUMMARY_PROMPT, load_config, save_config

# ----- 从 audio_recorder.py 和 batch_transcribe.py 整合的配置 -----
# 音频录制配置
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100
DEVICE_INDEX_KEYWORD = "CABLE Output"  # 确保你的虚拟音频设备包含这个关键字
OUTPUT_DIR = "recorded_audio_segments"
SILENCE_THRESHOLD = 0.005
SILENCE_SECONDS = 1.5
MAX_RECORD_SECONDS = 30

# Whisper 转写配置
MODEL_SIZE = "large-v2"  # 可选：large-v2, medium, small, base, tiny
LANGUAGE = "zh"  # 默认中文

# --- 总结配置 ---
SUMMARY_CHECK_INTERVAL = 300 # 每300秒（5分钟）检查一次
MIN_TEXT_FOR_SUMMARY = 50 # 降低门槛，至少有50字新增文本才触发总结
TRANSCRIPTION_LOG_FILE = "transcription.txt"
# SUMMARY_PROMPT 在 config.py 中定义
# 限制每次发送到LLM的最大字符数，避免请求过大导致连接被重置/503
MAX_SUMMARY_CHARS = 8000

# --- 请求重试与稳定性参数 ---
RETRY_MAX_ATTEMPTS = 5
RETRY_BASE_DELAY = 2.0
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
JITTER_SECONDS = 0.5
# --------------------------------------------------------------------

class TranscriptionApp:
    def __init__(self, root):
        self.root = root
        self.root.title("实时语音转写及总结工具")
        self.root.geometry("1200x700") # 增大了初始窗口尺寸

        self.is_recording = False
        self.whisper_model = None
        self.recorder_thread = None
        self.transcriber_thread = None
        self.summary_thread = None
        self.stop_event = None
        
        self.audio_queue = queue.Queue()
        self.transcription_queue = queue.Queue()
        self.last_summary_text_len = 0 # 用于记录上次总结时转录文本的长度
        self.transcription_history = ""
        
        # 加载配置
        self.config = load_config()

        self.setup_ui()
        self.check_transcription_queue()

    def setup_ui(self):
        # --- 控件框架 ---
        self.status_label = tk.Label(self.root, text="就绪", bd=1, relief=tk.SUNKEN, anchor=tk.W)
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X)

        self.button_frame = tk.Frame(self.root)
        self.button_frame.pack(side=tk.TOP, fill=tk.X, pady=5, padx=10)

        self.start_button = tk.Button(self.button_frame, text="开始录制", command=self.start_recording)
        self.start_button.pack(side=tk.LEFT, padx=5)

        self.stop_button = tk.Button(self.button_frame, text="停止录制", command=self.stop_recording)
        self.stop_button.pack(side=tk.LEFT, padx=5)
        self.stop_button["state"] = "disabled"
        
        self.config_button = tk.Button(self.button_frame, text="配置模型", command=self.open_config_dialog)
        self.config_button.pack(side=tk.LEFT, padx=5)
        
        self.save_button = tk.Button(self.button_frame, text="保存为 Markdown", command=self.save_as_markdown)
        self.save_button.pack(side=tk.LEFT, padx=5)

        # --- 可拖拽的双面板 ---
        self.paned_window = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, sashrelief=tk.RAISED)
        self.paned_window.pack(expand=True, fill="both", padx=10, pady=10)

        # --- 左侧：笔记总结 ---
        self.summary_frame = tk.Frame(self.paned_window)
        self.summary_label = tk.Label(self.summary_frame, text="笔记总结", font=("微软雅黑", 12, "bold"))
        self.summary_label.pack(anchor=tk.W, pady=(0, 5))
        self.summary_area = scrolledtext.ScrolledText(self.summary_frame, wrap=tk.WORD, font=("微软雅黑", 12))
        self.summary_area.pack(expand=True, fill="both")
        self.paned_window.add(self.summary_frame, width=500) # 设置初始宽度

        # --- 右侧：原始语音转文字 ---
        self.transcription_frame = tk.Frame(self.paned_window)
        self.transcription_label = tk.Label(self.transcription_frame, text="原始语音转文字", font=("微软雅黑", 12, "bold"))
        self.transcription_label.pack(anchor=tk.W, pady=(0, 5))
        self.transcription_area = scrolledtext.ScrolledText(self.transcription_frame, wrap=tk.WORD, font=("微软雅黑", 12))
        self.transcription_area.pack(expand=True, fill="both")
        self.paned_window.add(self.transcription_frame, width=700) # 设置初始宽度

    def update_status(self, message):
        self.status_label.config(text=message)
        self.root.update_idletasks()

    def find_device_index(self, p, keyword):
        for i in range(p.get_device_count()):
            dev_info = p.get_device_info_by_index(i)
            if keyword.lower() in dev_info['name'].lower() and dev_info['maxInputChannels'] > 0:
                return i
        return None

    def record_audio(self):
        p = pyaudio.PyAudio()
        if not os.path.exists(OUTPUT_DIR):
            os.makedirs(OUTPUT_DIR)
        
        self.update_status("正在寻找音频设备...")
        device_index = self.find_device_index(p, DEVICE_INDEX_KEYWORD)
        if device_index is None:
            messagebox.showerror("设备错误", f"未找到音频输入设备 '{DEVICE_INDEX_KEYWORD}'")
            self.stop_recording()
            return

        self.update_status(f"准备监听设备: '{p.get_device_info_by_index(device_index)['name']}'")
        stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True,
                        frames_per_buffer=CHUNK, input_device_index=device_index)

        frames = []
        silence_frames = 0
        is_recording_segment = False

        while not self.stop_event.is_set():
            try:
                data = stream.read(CHUNK, exception_on_overflow=False)
                audio_np = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                is_silent = np.max(np.abs(audio_np)) < SILENCE_THRESHOLD

                if is_silent:
                    if is_recording_segment:
                        silence_frames += 1
                    
                    if is_recording_segment and silence_frames >= int(SILENCE_SECONDS * RATE / CHUNK) and len(frames) > 0:
                        filename = os.path.join(OUTPUT_DIR, f"segment_{int(time.time())}.wav")
                        with wave.open(filename, 'wb') as wf:
                            wf.setnchannels(CHANNELS)
                            wf.setsampwidth(p.get_sample_size(FORMAT))
                            wf.setframerate(RATE)
                            wf.writeframes(b''.join(frames))
                        self.audio_queue.put(filename)
                        frames = []
                        is_recording_segment = False
                        silence_frames = 0
                else:
                    is_recording_segment = True
                    silence_frames = 0
                    frames.append(data)

                if len(frames) >= int(MAX_RECORD_SECONDS * RATE / CHUNK):
                    filename = os.path.join(OUTPUT_DIR, f"segment_force_{int(time.time())}.wav")
                    with wave.open(filename, 'wb') as wf:
                        wf.setnchannels(CHANNELS)
                        wf.setsampwidth(p.get_sample_size(FORMAT))
                        wf.setframerate(RATE)
                        wf.writeframes(b''.join(frames))
                    self.audio_queue.put(filename)
                    frames = []
                    is_recording_segment = False
                    silence_frames = 0
            except Exception as e:
                print(f"音频录制错误: {e}")
                self.stop_event.set()
                break

    def transcribe_audio(self):
        try:
            self.update_status(f"正在加载 Whisper '{MODEL_SIZE}' 模型...")
            device = "cuda" if torch.cuda.is_available() else "cpu"
            self.whisper_model = whisper.load_model(MODEL_SIZE, device=device)
            self.update_status("模型加载完成。等待音频...")
        except Exception as e:
            messagebox.showerror("模型加载失败", f"加载 Whisper 模型时出错: {e}")
            self.stop_recording()
            return
        
        while not self.stop_event.is_set():
            try:
                filepath = self.audio_queue.get(timeout=1)
                if filepath is None:
                    break
                
                self.update_status(f"正在转写: {os.path.basename(filepath)}")
                
                result = self.whisper_model.transcribe(filepath, language=LANGUAGE, fp16=torch.cuda.is_available())
                text = result["text"].strip()
                
                if text:
                    self.transcription_queue.put(text)
                
                self.update_status("正在录制...")
                
            except queue.Empty:
                continue
            except Exception as e:
                print(f"转写文件时发生错误: {e}")

    def call_llm(self, prompt):
        """调用大语言模型API"""
        if self.config["llm_provider"] == "Ollama":
            return self.call_ollama(prompt)
        elif self.config["llm_provider"] == "Gemini":
            return self.call_gemini(prompt)
        else:
            print(f"未知的LLM提供商: {self.config["llm_provider"]}")
            return None

    def call_ollama(self, prompt):
        """调用 Ollama API，处理结构化 JSON 返回"""
        payload = {
            "model": self.config["ollama_model"],
            "prompt": prompt,
            "stream": False,
        }
        try:
            print("\n--- 发送给大模型的提示词（用于调试） ---")
            print((prompt[:2000] + ("...[truncated]" if len(prompt) > 2000 else "")))
            print("-------------------------------------------\n")

            response = requests.post(self.config["ollama_api_url"], json=payload, timeout=90)
            response.raise_for_status()
            
            response_text = response.text.strip()

            print("\n--- 大模型原始响应（用于调试） ---")
            print(response_text[:4000])
            print("---------------------------------------\n")
            
            # Ollama的原始响应可能包含多个JSON对象，只需要最后一个
            last_response_line = response_text.strip().split('\n')[-1]
            try:
                data = json.loads(last_response_line)
                raw_response = data.get('response', '')
                
                # 使用正则表达式移除 <think> 标签及其内容
                clean_response = re.sub(r'<think>.*?</think>', '', raw_response, flags=re.DOTALL).strip()
                return clean_response or None
            except (json.JSONDecodeError, IndexError, KeyError):
                print("警告：无法解析大模型响应，返回原始文本。")
                return (response_text or None)
        except requests.exceptions.RequestException as e:
            print(f"Ollama API调用错误: {e}")
            self.update_status("Ollama API调用失败，请检查服务。")
            return None

    def summary_loop(self):
        """定期检查和总结文本"""
        while not self.stop_event.is_set():
            time.sleep(SUMMARY_CHECK_INTERVAL)
            self.process_summary()

    def call_llm_with_retries(self, prompt, retries=RETRY_MAX_ATTEMPTS, base_delay=RETRY_BASE_DELAY):
        """带重试的LLM调用（指数退避 + 抖动）"""
        last_err = None
        for attempt in range(1, retries + 1):
            content = self.call_llm(prompt)
            if content:
                return content
            delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, JITTER_SECONDS)
            self.update_status(f"总结调用失败，{attempt}/{retries} 次尝试。{('稍后重试...' if attempt < retries else '放弃。')}")
            if attempt < retries:
                try:
                    time.sleep(delay)
                except Exception:
                    pass
        return None

    def _resolve_gemini_models(self):
        """根据配置解析 Gemini 备选模型名称列表，并提供稳定回退项。"""
        raw = (self.config.get("gemini_model") or "gemini-2.5-flash").strip()
        candidates = []
        if raw.endswith("-latest"):
            base = raw[:-7]
            if base:
                candidates.extend([f"{base}-002", f"{base}-001", base])
            else:
                candidates.append("gemini-2.5-flash")
        else:
            candidates.append(raw)
            # 常见后缀组合
            if not re.search(r"-(\d+)$", raw):
                candidates.append(f"{raw}-001")
                candidates.append(f"{raw}-002")
            else:
                # 同时加入去掉后缀的版本
                candidates.append(re.sub(r"-(\d+)$", "", raw))
        # 追加常见稳定可用模型（1.5 作为回退）
        candidates += [
            "gemini-2.5-flash-001",
            "gemini-2.5-flash",
            "gemini-1.5-flash-002",
            "gemini-1.5-flash",
            "gemini-1.5-pro-002",
            "gemini-1.5-pro",
            "gemini-1.5-flash-8b",
        ]
        # 去重并保持顺序
        seen = set()
        ordered = []
        for name in candidates:
            if name and name not in seen:
                seen.add(name)
                ordered.append(name)
        return ordered

    def process_summary(self):
        """获取新增文本并生成总结"""
        # 提取上次总结后的新文本
        text_to_analyze = self.transcription_history[self.last_summary_text_len:]
        
        if not text_to_analyze or len(text_to_analyze) < MIN_TEXT_FOR_SUMMARY:
            print(f"新增文本过短 ({len(text_to_analyze)}字)，不进行总结。")
            return

        # 限制提交给模型的文本长度（取最近的内容，更利于上下文连贯）
        bounded_text = text_to_analyze[-MAX_SUMMARY_CHARS:]

        self.update_status("正在生成总结...")
        prompt = SUMMARY_PROMPT.format(bounded_text)
        
        summary_content = self.call_llm_with_retries(prompt, retries=RETRY_MAX_ATTEMPTS, base_delay=RETRY_BASE_DELAY)
        
        # 只有当大模型返回了有效的总结内容时才进行更新
        if summary_content:
            summary_content = summary_content.strip()
        if summary_content:
            self.update_status("总结完成。")
            
            # 将新总结追加到总结面板
            self.summary_area.insert(tk.END, summary_content + "\n\n")
            self.summary_area.see(tk.END)
            
            # 更新已总结文本的长度记录（仅在成功时推进游标）
            self.last_summary_text_len = len(self.transcription_history)
            
        else:
            self.update_status("大模型未返回有效总结，继续监听...")
            print("大模型未返回有效的总结，继续积累文本。")

    def check_transcription_queue(self):
        """定期检查转写队列并更新UI"""
        while not self.transcription_queue.empty():
            new_text = self.transcription_queue.get_nowait()
            
            # 更新原始语音转文字面板
            self.transcription_area.insert(tk.END, new_text + " ")
            self.transcription_area.see(tk.END)
            
            # 更新完整的转录历史
            self.transcription_history += (new_text + " ")
            
            # 写入日志文件
            with open(TRANSCRIPTION_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(new_text + " ")

        self.root.after(100, self.check_transcription_queue)

    def save_as_markdown(self):
        """将两个面板的内容合并保存为Markdown文件"""
        file_path = filedialog.asksaveasfilename(
            defaultextension=".md",
            filetypes=[("Markdown files", "*.md"), ("All files", "*.*")])
        if file_path:
            try:
                summary_content = self.summary_area.get("1.0", tk.END).strip()
                transcription_content = self.transcription_area.get("1.0", tk.END).strip()
                
                # 构建Markdown内容
                markdown_content = f"# 笔记总结\n\n{summary_content}\n\n---\n\n# 原始语音转文字\n\n{transcription_content}"
                
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(markdown_content)
                messagebox.showinfo("保存成功", f"文件已成功保存到: {file_path}")
            except Exception as e:
                messagebox.showerror("保存失败", f"保存文件时发生错误: {e}")

    def start_recording(self):
        self.is_recording = True
        self.start_button["state"] = "disabled"
        self.stop_button["state"] = "normal"
        self.stop_event = threading.Event()
        
        self.recorder_thread = threading.Thread(target=self.record_audio, daemon=True)
        self.transcriber_thread = threading.Thread(target=self.transcribe_audio, daemon=True)
        self.summary_thread = threading.Thread(target=self.summary_loop, daemon=True)
        
        self.recorder_thread.start()
        self.transcriber_thread.start()
        self.summary_thread.start()
        
        self.update_status("正在录制...")

    def stop_recording(self):
        self.is_recording = False
        self.start_button["state"] = "normal"
        self.stop_button["state"] = "disabled"
        if self.stop_event:
            self.stop_event.set()
        
        self.audio_queue.put(None)
        
        if self.recorder_thread and self.recorder_thread.is_alive():
            self.recorder_thread.join()
        if self.transcriber_thread and self.transcriber_thread.is_alive():
            self.transcriber_thread.join()
        if self.summary_thread and self.summary_thread.is_alive():
            self.summary_thread.join()
        
        self.update_status("录制已停止")
        print("所有线程已停止。")
        
    def call_gemini(self, prompt):
        """调用 Gemini API（带状态码感知重试 + 404 模型回退 + v1beta 兜底）"""
        if not self.config["gemini_api_key"]:
            print("错误：Gemini API Key未配置")
            self.update_status("Gemini API Key未配置")
            return None
            
        headers = {
            "Content-Type": "application/json",
            "Connection": "close"
        }

        model_candidates = self._resolve_gemini_models()
        last_error = None
        for model_name in model_candidates:
            api_versions = ["v1", "v1beta"]
            tried_versions = []
            for api_version in api_versions:
                url = f"https://generativelanguage.googleapis.com/{api_version}/models/{model_name}:generateContent?key={self.config['gemini_api_key']}"
                payload = {
                    "contents": [{
                        "role": "user",
                        "parts": [{"text": prompt}]
                    }]
                }
                for attempt in range(1, RETRY_MAX_ATTEMPTS + 1):
                    try:
                        print("\n--- 发送给Gemini的提示词（用于调试） ---")
                        print(prompt[:2000] + ("...[truncated]" if len(prompt) > 2000 else ""))
                        print(f"使用模型: {model_name} | API: {api_version}")
                        print("-------------------------------------------\n")

                        response = requests.post(url, headers=headers, json=payload, timeout=30)

                        # 404：如果是 v1，切换 v1beta；若 v1beta 也 404，换下一个模型
                        if response.status_code == 404:
                            print(f"{api_version} 上的模型 {model_name} 返回 404。")
                            last_error = requests.HTTPError("404 Not Found")
                            tried_versions.append(api_version)
                            # 切换到下一个 API 版本
                            break

                        if response.status_code in RETRY_STATUS_CODES:
                            retry_after = response.headers.get("Retry-After")
                            if retry_after:
                                try:
                                    delay = float(retry_after)
                                except ValueError:
                                    delay = RETRY_BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0, JITTER_SECONDS)
                            else:
                                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0, JITTER_SECONDS)
                            print(f"Gemini返回 {response.status_code}，第 {attempt}/{RETRY_MAX_ATTEMPTS} 次重试，{delay:.2f}s 后重试。")
                            if attempt < RETRY_MAX_ATTEMPTS:
                                time.sleep(delay)
                                continue
                            response.raise_for_status()

                        response.raise_for_status()
                        data = response.json()
                        
                        print("\n--- Gemini原始响应（用于调试） ---")
                        print(json.dumps(data, ensure_ascii=False, indent=2)[:4000])
                        print("---------------------------------------\n")
                        
                        if "candidates" in data and len(data["candidates"]) > 0:
                            parts = data["candidates"][0].get("content", {}).get("parts", [])
                            if parts and "text" in parts[0]:
                                content = parts[0]["text"].strip()
                                # 记住可用模型，便于下次直接使用
                                if self.config.get("gemini_model") != model_name:
                                    self.config["gemini_model"] = model_name
                                    try:
                                        save_config(self.config)
                                    except Exception:
                                        pass
                                return content or None
                        print("警告：Gemini响应格式异常")
                        return None
                            
                    except requests.exceptions.RequestException as e:
                        delay = RETRY_BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0, JITTER_SECONDS)
                        print(f"Gemini API调用错误: {e}，第 {attempt}/{RETRY_MAX_ATTEMPTS} 次重试。")
                        last_error = e
                        if attempt < RETRY_MAX_ATTEMPTS:
                            time.sleep(delay)
                            continue
                        else:
                            # 用尽当前 API 版本的重试，尝试下一个 API 版本或下一个模型
                            break
                    except (KeyError, IndexError, ValueError, json.JSONDecodeError) as e:
                        print(f"Gemini 响应解析错误: {e}")
                        last_error = e
                        # 避免无限循环，切换 API 版本/模型
                        break
                # 如果当前版本为 v1 且刚才因 404 跳出循环，则继续尝试 v1beta
                if tried_versions and tried_versions[-1] == api_version and api_version == "v1":
                    continue
                # 如果不是 404 场景或 v1beta 也失败，则跳出到下一个模型
                # 由外层 for model_name 控制
            # 尝试完所有 API 版本后，进入下一个模型
            continue

        if last_error:
            print(f"Gemini 最终失败: {last_error}")
            self.update_status("Gemini 多模型尝试后仍失败，请检查模型名或权限。")
        return None

    def open_config_dialog(self):
        """打开配置对话框"""
        config_window = tk.Toplevel(self.root)
        config_window.title("模型配置")
        config_window.geometry("500x400")
        config_window.resizable(False, False)
        
        # 使配置窗口居中
        config_window.transient(self.root)
        config_window.grab_set()
        
        # 主框架
        main_frame = tk.Frame(config_window)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # LLM提供商选择
        provider_frame = tk.Frame(main_frame)
        provider_frame.pack(fill=tk.X, pady=(0, 15))
        
        tk.Label(provider_frame, text="大语言模型提供商:", font=("微软雅黑", 10, "bold")).pack(anchor=tk.W)
        
        self.provider_var = tk.StringVar(value=self.config["llm_provider"])
        provider_radio_frame = tk.Frame(provider_frame)
        provider_radio_frame.pack(anchor=tk.W, pady=(5, 0))
        
        tk.Radiobutton(provider_radio_frame, text="Ollama (本地)", variable=self.provider_var, 
                      value="Ollama", command=self.on_provider_change).pack(side=tk.LEFT, padx=(0, 20))
        tk.Radiobutton(provider_radio_frame, text="Gemini (云端)", variable=self.provider_var, 
                      value="Gemini", command=self.on_provider_change).pack(side=tk.LEFT)
        
        # Ollama配置框架
        self.ollama_frame = tk.LabelFrame(main_frame, text="Ollama 配置", font=("微软雅黑", 9))
        self.ollama_frame.pack(fill=tk.X, pady=(0, 15))
        
        # API URL
        tk.Label(self.ollama_frame, text="API URL:").pack(anchor=tk.W, padx=10, pady=(10, 0))
        self.ollama_url_var = tk.StringVar(value=self.config["ollama_api_url"])
        ollama_url_entry = tk.Entry(self.ollama_frame, textvariable=self.ollama_url_var, width=50)
        ollama_url_entry.pack(fill=tk.X, padx=10, pady=(5, 10))
        
        # 模型名称
        tk.Label(self.ollama_frame, text="模型名称:").pack(anchor=tk.W, padx=10)
        self.ollama_model_var = tk.StringVar(value=self.config["ollama_model"])
        ollama_model_entry = tk.Entry(self.ollama_frame, textvariable=self.ollama_model_var, width=50)
        ollama_model_entry.pack(fill=tk.X, padx=10, pady=(5, 10))
        
        # Gemini配置框架
        self.gemini_frame = tk.LabelFrame(main_frame, text="Gemini 配置", font=("微软雅黑", 9))
        self.gemini_frame.pack(fill=tk.X, pady=(0, 15))
        
        # API Key
        tk.Label(self.gemini_frame, text="API Key:").pack(anchor=tk.W, padx=10, pady=(10, 0))
        self.gemini_key_var = tk.StringVar(value=self.config["gemini_api_key"])
        gemini_key_entry = tk.Entry(self.gemini_frame, textvariable=self.gemini_key_var, width=50, show="*")
        gemini_key_entry.pack(fill=tk.X, padx=10, pady=(5, 10))
        
        # 模型名称
        tk.Label(self.gemini_frame, text="模型名称:").pack(anchor=tk.W, padx=10)
        self.gemini_model_var = tk.StringVar(value=self.config["gemini_model"])
        gemini_model_entry = tk.Entry(self.gemini_frame, textvariable=self.gemini_model_var, width=50)
        gemini_model_entry.pack(fill=tk.X, padx=10, pady=(5, 10))
        
        # 按钮框架
        button_frame = tk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))
        
        tk.Button(button_frame, text="保存配置", command=lambda: self.save_config_and_close(config_window)).pack(side=tk.RIGHT, padx=(5, 0))
        tk.Button(button_frame, text="取消", command=config_window.destroy).pack(side=tk.RIGHT)
        
        # 初始化显示状态
        self.on_provider_change()
        
        # 绑定关闭事件
        config_window.protocol("WM_DELETE_WINDOW", config_window.destroy)
    
    def on_provider_change(self):
        """当提供商选择改变时更新界面"""
        if self.provider_var.get() == "Ollama":
            self.ollama_frame.pack(fill=tk.X, pady=(0, 15))
            self.gemini_frame.pack_forget()
        else:
            self.ollama_frame.pack_forget()
            self.gemini_frame.pack(fill=tk.X, pady=(0, 15))
    
    def save_config_and_close(self, config_window):
        """保存配置并关闭对话框"""
        # 更新配置
        self.config["llm_provider"] = self.provider_var.get()
        self.config["ollama_api_url"] = self.ollama_url_var.get()
        self.config["ollama_model"] = self.ollama_model_var.get()
        self.config["gemini_api_key"] = self.gemini_key_var.get()
        self.config["gemini_model"] = self.gemini_model_var.get()
        
        # 保存到文件
        if save_config(self.config):
            messagebox.showinfo("配置保存", "配置已成功保存！")
            config_window.destroy()
        else:
            messagebox.showerror("配置保存失败", "无法保存配置文件，请检查文件权限。")

    def on_closing(self):
        if self.is_recording:
            if messagebox.askokcancel("退出", "录制仍在进行中。确定要退出吗？"):
                self.stop_recording()
                self.root.destroy()
        else:
            self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = TranscriptionApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
