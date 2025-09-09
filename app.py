import tkinter as tk
from tkinter import scrolledtext, messagebox, filedialog
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

# 导入配置文件
from config import SUMMARY_PROMPT

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
MODEL_SIZE = "large-v2" # large-v2, medium, small, base, tiny
LANGUAGE = "zh" # 中文

# --- Ollama 配置 ---
OLLAMA_API_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "deepseek-r1:1.5b"
TRANSCRIPTION_LOG_FILE = "transcription.txt"

# --- 总结配置 ---
SUMMARY_CHECK_INTERVAL = 60 # 每60秒检查一次
MIN_TEXT_FOR_SUMMARY = 50 # 降低门槛，至少有50字新增文本才触发总结
# SUMMARY_PROMPT 在 config.py 中定义
# --------------------------------------------------------------------

class TranscriptionApp:
    def __init__(self, root):
        self.root = root
        self.root.title("实时语音转写及总结工具")
        self.root.geometry("800x600")

        self.is_recording = False
        self.whisper_model = None
        self.recorder_thread = None
        self.transcriber_thread = None
        self.summary_thread = None
        self.stop_event = None
        
        self.audio_queue = queue.Queue()
        self.transcription_queue = queue.Queue()
        self.summarized_text = ""
        self.transcription_history = ""

        self.setup_ui()
        self.check_transcription_queue()

    def setup_ui(self):
        # --- 控件框架 ---
        self.status_label = tk.Label(self.root, text="就绪", bd=1, relief=tk.SUNKEN, anchor=tk.W)
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X)

        self.button_frame = tk.Frame(self.root)
        self.button_frame.pack(side=tk.TOP, fill=tk.X, pady=5)

        self.start_button = tk.Button(self.button_frame, text="开始录制", command=self.start_recording)
        self.start_button.pack(side=tk.LEFT, padx=5)

        self.stop_button = tk.Button(self.button_frame, text="停止录制", command=self.stop_recording)
        self.stop_button.pack(side=tk.LEFT, padx=5)
        self.stop_button["state"] = "disabled"

        self.text_area = scrolledtext.ScrolledText(self.root, wrap=tk.WORD, font=("微软雅黑", 12))
        self.text_area.pack(expand=True, fill="both", padx=10, pady=10)
        
        # 定义摘要的标签样式
        self.text_area.tag_configure("summary", foreground="#007bff", font=("微软雅黑", 12, "bold"))
        self.text_area.tag_configure("original", foreground="black")

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

    def call_ollama(self, prompt):
        """调用 Ollama API，处理结构化 JSON 返回"""
        payload = {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
        }
        try:
            print("\n--- 发送给大模型的提示词（用于调试） ---")
            print(prompt)
            print("-------------------------------------------\n")

            response = requests.post(OLLAMA_API_URL, json=payload, timeout=90)
            response.raise_for_status()
            
            response_text = response.text.strip()

            print("\n--- 大模型原始响应（用于调试） ---")
            print(response_text)
            print("---------------------------------------\n")
            
            # Ollama的原始响应可能包含多个JSON对象，只需要最后一个
            last_response_line = response_text.strip().split('\n')[-1]
            try:
                data = json.loads(last_response_line)
                raw_response = data['response']
                
                # 新增：使用正则表达式移除 <think> 标签及其内容
                clean_response = re.sub(r'<think>.*?</think>', '', raw_response, flags=re.DOTALL)
                return clean_response
            except (json.JSONDecodeError, IndexError, KeyError):
                print("警告：无法解析大模型响应，返回原始文本。")
                return response_text
        except requests.exceptions.RequestException as e:
            print(f"Ollama API调用错误: {e}")
            self.update_status("Ollama API调用失败，请检查服务。")
            return prompt

    def summary_loop(self):
        """定期检查和总结文本"""
        while not self.stop_event.is_set():
            time.sleep(SUMMARY_CHECK_INTERVAL)
            self.process_summary()

    def process_summary(self):
        # 提取上次总结后的新文本
        text_to_analyze = self.transcription_history[len(self.summarized_text):]
        
        if not text_to_analyze or len(text_to_analyze) < MIN_TEXT_FOR_SUMMARY:
            print("新增文本过短，不进行总结。")
            return

        self.update_status("正在检查是否需要总结...")
        prompt = SUMMARY_PROMPT.format(text_to_analyze)
        
        raw_response = self.call_ollama(prompt)
        
        # 使用分隔符拆分响应
        parts = raw_response.split("[SPLIT_POINT]")
        summary_content = parts[0].strip()
        remaining_text = parts[1].strip() if len(parts) > 1 else ""

        # 只有当大模型返回了有效的总结内容时才进行更新
        if summary_content:
            self.update_status("意群结束，生成阶段性总结...")
            
            # 找到需要被替换的原文
            text_to_be_replaced = text_to_analyze.replace(remaining_text, "", 1)
            
            # 更新显示区域
            # 先删除旧的、未总结的文本
            self.text_area.delete(f"end-{len(text_to_analyze)}c", tk.END)
            
            # 插入新的、带标签的总结
            self.text_area.insert(tk.END, summary_content + "\n", "summary")
            
            # 插入未被总结的剩余文本
            if remaining_text:
                self.text_area.insert(tk.END, remaining_text, "original")
            
            self.text_area.see(tk.END)
            
            # 更新已总结的文本历史
            self.summarized_text += text_to_be_replaced
            
            self.update_status("总结完成。")
        else:
            print("大模型未返回有效的总结，继续积累文本。")

    def check_transcription_queue(self):
        """定期检查转写队列并更新UI"""
        while not self.transcription_queue.empty():
            new_text = self.transcription_queue.get_nowait()
            self.text_area.insert(tk.END, new_text, "original")
            self.text_area.see(tk.END)
            self.transcription_history += new_text
            with open(TRANSCRIPTION_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(new_text)

        self.root.after(100, self.check_transcription_queue)

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