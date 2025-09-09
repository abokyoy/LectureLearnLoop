import tkinter as tk
from tkinter import scrolledtext, messagebox
import threading
import queue
import os
import time
import wave
import pyaudio
import numpy as np
import torch
import whisper

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

# --------------------------------------------------------------------

class TranscriptionApp:
    def __init__(self, root):
        self.root = root
        self.root.title("实时语音转写工具")
        self.root.geometry("800x600")

        self.is_recording = False
        self.whisper_model = None
        self.recorder_thread = None
        self.transcriber_thread = None
        self.stop_event = None
        self.audio_queue = queue.Queue()
        self.transcription_queue = queue.Queue()

        self.setup_ui()
        self.check_transcription_queue()

    def setup_ui(self):
        # --- 控件框架 ---
        control_frame = tk.Frame(self.root, padx=10, pady=10)
        control_frame.pack(fill=tk.X)

        self.start_button = tk.Button(control_frame, text="开始录制", command=self.start_recording, font=("Arial", 12), width=15)
        self.start_button.pack(side=tk.LEFT, padx=5)

        self.stop_button = tk.Button(control_frame, text="停止录制", command=self.stop_recording, font=("Arial", 12), width=15, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=5)

        # --- 状态栏 ---
        self.status_label = tk.Label(self.root, text="状态: 空闲", bd=1, relief=tk.SUNKEN, anchor=tk.W)
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X)

        # --- 文本显示框 ---
        self.transcription_display = scrolledtext.ScrolledText(self.root, wrap=tk.WORD, font=("Arial", 14))
        self.transcription_display.pack(expand=True, fill=tk.BOTH, padx=10, pady=5)
        self.transcription_display.config(state=tk.DISABLED)

    def update_status(self, message):
        self.status_label.config(text=f"状态: {message}")
        self.root.update_idletasks()

    def start_recording(self):
        self.is_recording = True
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        
        self.clear_transcription_display()
        self.update_status("正在初始化...")

        self.stop_event = threading.Event()
        
        # 启动录音和转写线程
        self.recorder_thread = threading.Thread(target=self.record_audio_worker)
        self.transcriber_thread = threading.Thread(target=self.transcribe_audio_worker)
        
        self.recorder_thread.start()
        self.transcriber_thread.start()

    def stop_recording(self):
        if self.is_recording:
            self.update_status("正在停止...")
            self.stop_event.set()
            
            # 等待线程结束
            if self.recorder_thread:
                self.recorder_thread.join()
            if self.transcriber_thread:
                self.transcriber_thread.join()

            self.is_recording = False
            self.start_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED)
            self.update_status("空闲")

    def check_transcription_queue(self):
        """定时检查转写结果队列，并更新UI"""
        try:
            while not self.transcription_queue.empty():
                text = self.transcription_queue.get_nowait()
                self.append_to_transcription_display(text)
        finally:
            self.root.after(200, self.check_transcription_queue)

    def append_to_transcription_display(self, text):
        self.transcription_display.config(state=tk.NORMAL)
        self.transcription_display.insert(tk.END, text + "\n\n")
        self.transcription_display.see(tk.END) # 滚动到底部
        self.transcription_display.config(state=tk.DISABLED)
        
    def clear_transcription_display(self):
        self.transcription_display.config(state=tk.NORMAL)
        self.transcription_display.delete(1.0, tk.END)
        self.transcription_display.config(state=tk.DISABLED)

    def find_device_index(self, p, device_name_keyword):
        for i in range(p.get_device_count()):
            dev_info = p.get_device_info_by_index(i)
            if device_name_keyword.lower() in dev_info['name'].lower() and dev_info['maxInputChannels'] > 0:
                return i
        return None

    def record_audio_worker(self):
        p = pyaudio.PyAudio()
        if not os.path.exists(OUTPUT_DIR):
            os.makedirs(OUTPUT_DIR)

        device_index = self.find_device_index(p, DEVICE_INDEX_KEYWORD)
        if device_index is None:
            messagebox.showerror("错误", f"未找到包含关键字 '{DEVICE_INDEX_KEYWORD}' 的音频输入设备。请检查设备连接和配置。")
            self.stop_recording()
            return

        try:
            stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True,
                            frames_per_buffer=CHUNK, input_device_index=device_index)
        except Exception as e:
            messagebox.showerror("错误", f"无法打开音频流: {e}")
            self.stop_recording()
            return
            
        self.update_status("正在录制...")
        
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
                    if is_recording_segment and silence_frames >= int(SILENCE_SECONDS * RATE / CHUNK) and len(frames) > 10:
                        self.save_segment(p, frames)
                        frames, is_recording_segment, silence_frames = [], False, 0
                else:
                    is_recording_segment = True
                    silence_frames = 0
                    frames.append(data)

                if len(frames) >= int(MAX_RECORD_SECONDS * RATE / CHUNK):
                    self.save_segment(p, frames)
                    frames, is_recording_segment, silence_frames = [], False, 0
            except Exception as e:
                print(f"录制循环中发生错误: {e}") # 在控制台打印错误
                break

        if frames:
            self.save_segment(p, frames)

        stream.stop_stream()
        stream.close()
        p.terminate()
        self.audio_queue.put(None) # 发送结束信号给转写线程

    def save_segment(self, p, frames):
        filename = os.path.join(OUTPUT_DIR, f"segment_{int(time.time())}.wav")
        with wave.open(filename, 'wb') as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(p.get_sample_size(FORMAT))
            wf.setframerate(RATE)
            wf.writeframes(b''.join(frames))
        self.audio_queue.put(filename)

    def transcribe_audio_worker(self):
        # --- 加载模型 ---
        if self.whisper_model is None:
            self.update_status(f"正在加载 Whisper '{MODEL_SIZE}' 模型...")
            try:
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
                if filepath is None: # 收到结束信号
                    break
                
                self.update_status(f"正在转写: {os.path.basename(filepath)}")
                
                # 使用模型进行转写
                result = self.whisper_model.transcribe(filepath, language=LANGUAGE, fp16=torch.cuda.is_available())
                text = result["text"].strip()
                
                if text:
                    self.transcription_queue.put(text)
                
                self.update_status("正在录制...") # 转写完一个片段后，状态切回录制中
                
            except queue.Empty:
                continue # 队列为空，继续等待
            except Exception as e:
                print(f"转写文件时发生错误: {e}") # 在控制台打印错误

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
