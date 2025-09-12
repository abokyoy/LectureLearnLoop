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
from PIL import Image, ImageTk, ImageGrab
import io
import base64
from datetime import datetime

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
LANGUAGE = None  # 设置为None让Whisper自动检测语言，或者使用"auto"

# --- 总结配置 ---
SUMMARY_CHECK_INTERVAL = 300 # 每300秒（5分钟）检查一次
MIN_TEXT_FOR_SUMMARY = 50 # 降低门槛，至少有50字新增文本才触发总结
TRANSCRIPTION_LOG_FILE = "transcription.txt"
# SUMMARY_PROMPT 在 config.py 中定义
# 限制每次发送到LLM的最大字符数，避免请求过大导致连接被重置/503
MAX_SUMMARY_CHARS = 8000  # 这个变量保留用于向后兼容，但会被配置覆盖

# --- 请求重试与稳定性参数 ---
RETRY_MAX_ATTEMPTS = 5
RETRY_BASE_DELAY = 2.0
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
JITTER_SECONDS = 0.5
# --------------------------------------------------------------------

class ScreenshotTool:
    """截图工具，类似微信截图功能"""
    
    def __init__(self, callback=None):
        self.callback = callback  # 截图完成后的回调函数
        self.root = None
        self.canvas = None
        self.start_x = 0
        self.start_y = 0
        self.rect_id = None
        self.is_selecting = False
        
    def take_screenshot(self):
        """开始截图流程"""
        try:
            # 截取整个屏幕
            self.screenshot = ImageGrab.grab()
            
            # 创建全屏窗口
            self.create_screenshot_window()
            
        except Exception as e:
            messagebox.showerror("截图错误", f"截图失败: {e}")
    
    def create_screenshot_window(self):
        """创建全屏截图选择窗口"""
        # 创建顶级窗口
        self.root = tk.Toplevel()
        self.root.title("截图选择")
        
        # 设置全屏
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        self.root.geometry(f"{screen_width}x{screen_height}+0+0")
        self.root.attributes("-topmost", True)
        self.root.attributes("-fullscreen", True)
        self.root.configure(cursor="crosshair")
        
        # 创建画布
        self.canvas = tk.Canvas(self.root, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
        # 将截图显示在画布上
        self.screenshot_tk = ImageTk.PhotoImage(self.screenshot)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.screenshot_tk)
        
        # 添加半透明遮罩
        self.canvas.create_rectangle(0, 0, screen_width, screen_height, 
                                   fill="black", stipple="gray50", tags="mask")
        
        # 绑定事件
        self.canvas.bind("<Button-1>", self.start_selection)
        self.canvas.bind("<B1-Motion>", self.update_selection)
        self.canvas.bind("<ButtonRelease-1>", self.end_selection)
        self.root.bind("<Escape>", self.cancel_screenshot)
        self.root.bind("<Return>", self.confirm_screenshot)
        
        # 添加提示文本
        self.canvas.create_text(screen_width//2, 50, 
                              text="拖拽鼠标选择区域，按Enter确认，按Esc取消", 
                              fill="white", font=("微软雅黑", 14), tags="help")
        
        self.root.focus_set()
    
    def start_selection(self, event):
        """开始选择区域"""
        self.start_x = event.x
        self.start_y = event.y
        self.is_selecting = True
        
        # 删除之前的选择框
        if self.rect_id:
            self.canvas.delete(self.rect_id)
            self.canvas.delete("selection_area")
    
    def update_selection(self, event):
        """更新选择区域"""
        if not self.is_selecting:
            return
            
        # 删除之前的选择框
        if self.rect_id:
            self.canvas.delete(self.rect_id)
            self.canvas.delete("selection_area")
        
        # 绘制新的选择框
        self.rect_id = self.canvas.create_rectangle(
            self.start_x, self.start_y, event.x, event.y,
            outline="red", width=2, tags="selection"
        )
        
        # 清除选择区域内的遮罩
        self.canvas.create_rectangle(
            self.start_x, self.start_y, event.x, event.y,
            fill="", outline="", tags="selection_area"
        )
    
    def end_selection(self, event):
        """结束选择"""
        self.is_selecting = False
        self.end_x = event.x
        self.end_y = event.y
    
    def confirm_screenshot(self, event=None):
        """确认截图"""
        if hasattr(self, 'end_x') and hasattr(self, 'end_y'):
            # 计算选择区域
            x1 = min(self.start_x, self.end_x)
            y1 = min(self.start_y, self.end_y)
            x2 = max(self.start_x, self.end_x)
            y2 = max(self.start_y, self.end_y)
            
            # 确保选择区域有效
            if abs(x2 - x1) > 10 and abs(y2 - y1) > 10:
                # 裁剪截图
                cropped = self.screenshot.crop((x1, y1, x2, y2))
                
                # 保存到临时文件
                temp_path = os.path.join(os.getcwd(), f"screenshot_{int(time.time())}.png")
                cropped.save(temp_path)
                
                # 调用回调函数
                if self.callback:
                    self.callback(temp_path)
                
                self.close_screenshot_window()
            else:
                messagebox.showwarning("选择区域太小", "请选择更大的区域")
        else:
            messagebox.showwarning("未选择区域", "请先拖拽选择截图区域")
    
    def cancel_screenshot(self, event=None):
        """取消截图"""
        self.close_screenshot_window()
    
    def close_screenshot_window(self):
        """关闭截图窗口"""
        if self.root:
            self.root.destroy()
            self.root = None

class RichTextEditor:
    """富文本编辑器，支持图片粘贴和基本格式化"""
    
    def __init__(self, parent, on_change=None, **kwargs):
        self.parent = parent
        self.text_widget = tk.Text(parent, **kwargs)
        self.setup_bindings()
        self.image_counter = 0
        self.on_change = on_change
        # 保存图片对象与原图
        self.images = {}
        self.images_pil = {}
        
    def setup_bindings(self):
        """设置键盘绑定"""
        self.text_widget.bind("<Control-v>", self.paste_image)
        self.text_widget.bind("<Button-3>", self.show_context_menu)  # 右键菜单
        self.text_widget.bind("<Control-Button-1>", self.insert_image_dialog)
        # 文本改动监听，触发自动保存
        self.text_widget.bind('<<Modified>>', self._on_modified)
        
    def paste_image(self, event=None):
        """处理Ctrl+V粘贴图片"""
        try:
            # 尝试从剪贴板获取图片
            if self.parent.winfo_toplevel().clipboard_get():
                # 这里可以添加从剪贴板获取图片的逻辑
                pass
        except:
            pass
        return "break"
    
    def _on_modified(self, event=None):
        try:
            if self.on_change:
                self.on_change()
        finally:
            # 重置 modified 标志
            self.text_widget.edit_modified(False)
    
    def insert_image_dialog(self, event=None):
        """插入图片对话框"""
        file_path = filedialog.askopenfilename(
            title="选择图片",
            filetypes=[
                ("图片文件", "*.png *.jpg *.jpeg *.gif *.bmp"),
                ("所有文件", "*.*")
            ]
        )
        if file_path:
            self.insert_image(file_path)
    
    def insert_image(self, image_path):
        """在当前位置插入图片"""
        try:
            # 打开并调整图片大小
            img = Image.open(image_path)
            # 限制图片最大宽度为400像素
            if img.width > 400:
                ratio = 400 / img.width
                new_height = int(img.height * ratio)
                img = img.resize((400, new_height), Image.Resampling.LANCZOS)
            
            # 转换为PhotoImage
            photo = ImageTk.PhotoImage(img)
            
            # 在文本中插入图片
            self.image_counter += 1
            image_name = f"image_{self.image_counter}"
            
            # 保存图片引用，防止被垃圾回收，并记录PIL图像用于导出
            self.images[image_name] = photo
            self.images_pil[image_name] = img
            
            # 插入图片到文本中
            self.text_widget.image_create(tk.END, image=photo, name=image_name)
            self.text_widget.insert(tk.END, "\n")  # 图片后换行
            if self.on_change:
                self.on_change()
            
        except Exception as e:
            messagebox.showerror("错误", f"插入图片失败: {e}")
    
    def show_context_menu(self, event):
        """显示右键菜单"""
        context_menu = tk.Menu(self.parent, tearoff=0)
        context_menu.add_command(label="📸 截图", command=self.take_screenshot)
        context_menu.add_command(label="插入图片", command=self.insert_image_dialog)
        context_menu.add_separator()
        context_menu.add_command(label="粗体", command=lambda: self.apply_format("bold"))
        context_menu.add_command(label="斜体", command=lambda: self.apply_format("italic"))
        context_menu.add_command(label="下划线", command=lambda: self.apply_format("underline"))
        context_menu.add_separator()
        context_menu.add_command(label="清除格式", command=self.clear_format)
        
        try:
            context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            context_menu.grab_release()
    
    def apply_format(self, format_type):
        """应用文本格式"""
        try:
            if self.text_widget.tag_ranges(tk.SEL):
                # 如果有选中文本
                start, end = self.text_widget.tag_ranges(tk.SEL)[0], self.text_widget.tag_ranges(tk.SEL)[1]
                
                if format_type == "bold":
                    self.text_widget.tag_add("bold", start, end)
                    self.text_widget.tag_configure("bold", font=("微软雅黑", 12, "bold"))
                elif format_type == "italic":
                    self.text_widget.tag_add("italic", start, end)
                    self.text_widget.tag_configure("italic", font=("微软雅黑", 12, "italic"))
                elif format_type == "underline":
                    self.text_widget.tag_add("underline", start, end)
                    self.text_widget.tag_configure("underline", underline=True)
                if self.on_change:
                    self.on_change()
        except:
            pass
    
    def clear_format(self):
        """清除选中文本的格式"""
        try:
            if self.text_widget.tag_ranges(tk.SEL):
                start, end = self.text_widget.tag_ranges(tk.SEL)[0], self.text_widget.tag_ranges(tk.SEL)[1]
                self.text_widget.tag_remove("bold", start, end)
                self.text_widget.tag_remove("italic", start, end)
                self.text_widget.tag_remove("underline", start, end)
                if self.on_change:
                    self.on_change()
        except:
            pass
    
    def get(self, *args, **kwargs):
        """获取文本内容"""
        return self.text_widget.get(*args, **kwargs)
    
    def insert(self, *args, **kwargs):
        """插入文本"""
        result = self.text_widget.insert(*args, **kwargs)
        if self.on_change:
            self.on_change()
        return result
    
    def see(self, *args, **kwargs):
        """滚动到指定位置"""
        return self.text_widget.see(*args, **kwargs)
    
    def pack(self, *args, **kwargs):
        """打包组件"""
        return self.text_widget.pack(*args, **kwargs)
    
    def configure(self, *args, **kwargs):
        """配置组件"""
        return self.text_widget.configure(*args, **kwargs)
    
    def bind(self, *args, **kwargs):
        """绑定事件"""
        return self.text_widget.bind(*args, **kwargs)

    def take_screenshot(self):
        """调用截图工具"""
        screenshot_tool = ScreenshotTool(callback=self.insert_screenshot)
        screenshot_tool.take_screenshot()
    
    def insert_screenshot(self, image_path):
        """插入截图到文本中"""
        try:
            self.insert_image(image_path)
            # 删除临时文件
            if os.path.exists(image_path):
                os.remove(image_path)
        except Exception as e:
            messagebox.showerror("插入截图失败", f"无法插入截图: {e}")

    def export_markdown_with_images(self, attachments_dir):
        """将编辑器内容导出为Markdown，图片保存到指定目录并以 Obsidian 占位符形式输出。
        返回 (markdown_text, image_name_to_file_map)
        """
        if not os.path.isdir(attachments_dir):
            os.makedirs(attachments_dir, exist_ok=True)
        dump = self.text_widget.dump('1.0', tk.END, image=True, text=True)
        parts = []
        image_map = {}
        for item in dump:
            kind = item[0]
            if kind == 'text':
                text = item[1]
                parts.append(text)
            elif kind == 'image':
                img_name = item[1]
                pil_img = self.images_pil.get(img_name)
                if pil_img is None:
                    continue
                # 生成文件名
                timestamp = datetime.now().strftime('%Y%m%d%H%M%S%f')[:-3]
                filename = f"Pasted image {timestamp}.png"
                out_path = os.path.join(attachments_dir, filename)
                try:
                    pil_img.save(out_path, format='PNG')
                except Exception:
                    # 回退到RGB再存
                    try:
                        pil_img.convert('RGB').save(out_path, format='PNG')
                    except Exception:
                        continue
                image_map[img_name] = filename
                parts.append(f"![[{filename}]]")
        return ("".join(parts).strip(), image_map)

class SimpleTextEditor:
    """简单文本编辑器，基于 tk.Text，支持基本操作"""
    
    def __init__(self, parent, on_change=None, **kwargs):
        self.parent = parent
        self.text_widget = tk.Text(parent, **kwargs)
        self.setup_bindings()
        self.on_change = on_change
        
    def setup_bindings(self):
        """设置键盘绑定"""
        self.text_widget.bind('<<Modified>>', self._on_modified)
        
    def _on_modified(self, event=None):
        try:
            if self.on_change:
                self.on_change()
        finally:
            # 重置 modified 标志
            self.text_widget.edit_modified(False)
    
    def get(self, *args, **kwargs):
        """获取文本内容"""
        return self.text_widget.get(*args, **kwargs)
    
    def insert(self, *args, **kwargs):
        """插入文本"""
        result = self.text_widget.insert(*args, **kwargs)
        if self.on_change:
            self.on_change()
        return result
    
    def see(self, *args, **kwargs):
        """滚动到指定位置"""
        return self.text_widget.see(*args, **kwargs)
    
    def pack(self, *args, **kwargs):
        """打包组件"""
        return self.text_widget.pack(*args, **kwargs)
    
    def configure(self, *args, **kwargs):
        """配置组件"""
        return self.text_widget.configure(*args, **kwargs)
    
    def bind(self, *args, **kwargs):
        """绑定事件"""
        return self.text_widget.bind(*args, **kwargs)
    
    def delete(self, *args, **kwargs):
        """删除文本"""
        return self.text_widget.delete(*args, **kwargs)

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
        # 文档保存状态
        self.current_md_path = None
        self.attachments_dir = None
        self._autosave_after_id = None
        
        # 加载配置
        self.config = load_config()

        self.setup_ui()
        # 启动时加载上次文档
        self.load_last_document_if_any()
        self.check_transcription_queue()

    def update_status(self, message):
        self.status_label.config(text=message)
        self.root.update_idletasks()

    def check_transcription_queue(self):
        """定期检查转写队列并更新UI（优化版）"""
        try:
            # 1. 从队列中批量获取所有待处理的文本
            texts_to_add = []
            while not self.transcription_queue.empty():
                texts_to_add.append(self.transcription_queue.get_nowait())

            # 2. 如果有新文本，则进行一次性UI更新
            if texts_to_add:
                full_text_chunk = " ".join(texts_to_add) + " "
                
                # --- 深度优化：在插入大量文本时临时禁用小部件 --- #
                # 这可以防止在插入过程中进行昂贵的布局计算，从而使UI保持响应
                self.transcription_area.text_widget.configure(state='disabled')
                self.transcription_area.insert(tk.END, full_text_chunk)
                self.transcription_area.text_widget.configure(state='normal')
                self.transcription_area.see(tk.END)
                # ---------------------------------------------------- #
                
                # 更新转录历史和日志文件
                self.transcription_history += full_text_chunk
                try:
                    with open(TRANSCRIPTION_LOG_FILE, "a", encoding="utf-8") as f:
                        f.write(full_text_chunk)
                except Exception as e:
                    print(f"写入转录日志失败: {e}")
                
                # 触发自动保存
                self.schedule_autosave()

        finally:
            # 3. 安排下一次检查
            self.root.after(100, self.check_transcription_queue)

    def save_as_markdown(self):
        """将两个面板的内容合并保存为Markdown文件"""
        # 第一次选择路径，否则使用当前文档路径
        if not self.current_md_path:
            file_path = filedialog.asksaveasfilename(
                defaultextension=".md",
                filetypes=[("Markdown files", "*.md"), ("All files", "*.*")])
            if not file_path:
                return
            self.set_current_document(file_path)
        # 执行保存
        self.save_document()
        messagebox.showinfo("保存成功", f"文件已成功保存到: {self.current_md_path}")

    def set_current_document(self, md_path):
        print(f"\n=== 设置当前文档 ===")
        print(f"文档路径: {md_path}")
        self.current_md_path = md_path
        base_dir = os.path.dirname(md_path)
        self.attachments_dir = os.path.join(base_dir, "attachments")
        print(f"附件目录: {self.attachments_dir}")
        os.makedirs(self.attachments_dir, exist_ok=True)
        print(f"附件目录存在: {os.path.exists(self.attachments_dir)}")
        # 记录到配置
        self.config["last_document_path"] = self.current_md_path
        try:
            save_config(self.config)
        except Exception:
            pass

    def build_markdown(self):
        # 导出富文本为Markdown并保存图片
        summary_md, _ = self.summary_area.export_markdown_with_images(self.attachments_dir or os.getcwd())
        transcription_content = self.transcription_area.get("1.0", tk.END).strip()
        markdown_content = f"# 笔记总结\n\n{summary_md}\n\n---\n\n# 原始语音转文字\n\n{transcription_content}"
        return markdown_content

    def save_document(self):
        # 若无路径，默认保存到程序目录
        if not self.current_md_path:
            default_path = os.path.join(os.getcwd(), "notes.md")
            self.set_current_document(default_path)
        # 确保附件目录存在
        if not self.attachments_dir:
            self.attachments_dir = os.path.join(os.path.dirname(self.current_md_path), "attachments")
        os.makedirs(self.attachments_dir, exist_ok=True)
        content = self.build_markdown()
        try:
            with open(self.current_md_path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            print(f"自动保存失败: {e}")

    def schedule_autosave(self, delay_ms=800):
        # 防抖自动保存
        if self._autosave_after_id is not None:
            try:
                self.root.after_cancel(self._autosave_after_id)
            except Exception:
                pass
        self._autosave_after_id = self.root.after(delay_ms, self.save_document)

    def on_editor_changed(self):
        self.schedule_autosave()

    def load_last_document_if_any(self):
        """异步加载上次的文档"""
        print("\n=== 开始加载上次的文档 ===")
        path = self.config.get("last_document_path")
        print(f"配置中的上次文档路径: {path}")
        if not path or not os.path.isfile(path):
            print(f"警告: 未找到上次的文档或路径无效: {path}")
            return

        # 先设置当前文档
        self.set_current_document(path)

        self.update_status("正在加载文档...")
        self.root.update()

        def load_document():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = f.read()
                summary_text = ""
                transcript_text = ""
                if "# 原始语音转文字" in data:
                    parts = data.partition("# 原始语音转文字")
                    summary_text = parts[0].strip()
                    transcript_text = parts[2].strip()
                    if summary_text.startswith("# 笔记总结"):
                        summary_text = summary_text[summary_text.find('\n')+1:].lstrip()
                    summary_text = summary_text.replace('---', '').strip()
                else:
                    summary_text = data.strip()
                self.root.after(0, lambda: self._update_ui_after_loading(summary_text, transcript_text, path))
            except Exception as e:
                error_msg = f"加载文档失败: {str(e)}"
                print(error_msg)
                self.root.after(0, lambda: self.update_status(error_msg))

        threading.Thread(target=load_document, daemon=True).start()
    
    def _update_ui_after_loading(self, summary_text, transcript_text, path):
        """在UI线程中更新界面"""
        try:
            # 先更新状态
            self.update_status("正在渲染内容...")
            self.root.update()
            
            # 渲染摘要
            self.render_markdown_to_summary(summary_text)
            
            # 更新转写区域
            if transcript_text:
                self.transcription_area.delete("1.0", tk.END)
                self.transcription_area.insert(tk.END, transcript_text)
                self.transcription_area.see(tk.END)
            
            # 设置当前文档
            self.set_current_document(path)
            self.update_status(f"已加载文档: {os.path.basename(path)}")
            
        except Exception as e:
            error_msg = f"更新UI失败: {str(e)}"
            print(error_msg)
            self.update_status(error_msg)

    def render_markdown_to_summary(self, md_text):
        """将Markdown渲染到富文本编辑区（处理文本与 Obsidian 图片占位符）。"""
        print("\n=== render_markdown_to_summary 被调用 ===")
        if not md_text:
            print("警告: 传入的md_text为空")
            return

        print(f"当前文档路径: {getattr(self, 'current_md_path', '未设置')}")
        print(f"附件目录: {getattr(self, 'attachments_dir', '未设置')}")
        print(f"Markdown内容长度: {len(md_text)} 字符")

        self.summary_area.text_widget.delete("1.0", tk.END)

        if not hasattr(self, 'attachments_dir') or not self.attachments_dir or not os.path.isdir(self.attachments_dir):
            print("警告: 附件目录未设置或不存在，直接插入文本")
            self.summary_area.text_widget.insert(tk.END, md_text)
            return

        pattern = re.compile(r'!\[\[(.*?)\]\]')
        sample_size = 200
        start_sample = md_text[:sample_size]
        end_sample = md_text[-sample_size:] if len(md_text) > sample_size else md_text
        print(f"Markdown内容示例:\n开始: {start_sample}...\n...{end_sample}")

        last_end = 0
        matches = list(pattern.finditer(md_text))
        print(f"找到 {len(matches)} 个图片占位符")
        for i, match in enumerate(matches[:5]):
            print(f"  匹配 {i+1}: {match.group(0)}")
        if len(matches) > 5:
            print(f"  还有 {len(matches)-5} 个匹配项未显示...")

        if not matches:
            self.summary_area.text_widget.insert(tk.END, md_text)
            return

        for i, match in enumerate(matches):
            if last_end < match.start():
                self.summary_area.text_widget.insert(tk.END, md_text[last_end:match.start()])

            filename = match.group(1)
            img_path = os.path.join(self.attachments_dir, filename)
            print(f"\n尝试加载图片: {img_path}")
            print(f"文件存在: {os.path.isfile(img_path)}")
            if os.path.isfile(img_path):
                print(f"文件大小: {os.path.getsize(img_path)} 字节")
                try:
                    self.summary_area.text_widget.see(tk.END)
                    self.root.update_idletasks()
                    self.summary_area.text_widget.insert(tk.END, "\n")
                    self.summary_area.insert_image(img_path)  # 移除返回值检查
                    print(f"成功插入图片: {img_path}")
                    self.summary_area.text_widget.insert(tk.END, "\n")
                except Exception as e:
                    print(f"图片加载异常: {e}")
                    import traceback
                    traceback.print_exc()
                    self.summary_area.text_widget.insert(tk.END, f"[图片加载错误: {os.path.basename(img_path)}]")
            else:
                print(f"未找到图片: {filename}")
                self.summary_area.text_widget.insert(tk.END, match.group(0))
            last_end = match.end()

        if last_end < len(md_text):
            self.summary_area.text_widget.insert(tk.END, md_text[last_end:])
        self.summary_area.text_widget.see("1.0")

    def find_device_index(self, p, keyword):
        for i in range(p.get_device_count()):
            dev_info = p.get_device_info_by_index(i)
            if keyword.lower() in dev_info.get("name", "").lower() and dev_info.get("maxInputChannels", 0) > 0:
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
        self.update_status(f'准备监听设备: "{p.get_device_info_by_index(device_index).get("name", "未知设备")}"')
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
                        with wave.open(filename, "wb") as wf:
                            wf.setnchannels(CHANNELS)
                            wf.setsampwidth(p.get_sample_size(FORMAT))
                            wf.setframerate(RATE)
                            wf.writeframes(b"".join(frames))
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
                    with wave.open(filename, "wb") as wf:
                        wf.setnchannels(CHANNELS)
                        wf.setsampwidth(p.get_sample_size(FORMAT))
                        wf.setframerate(RATE)
                        wf.writeframes(b"".join(frames))
                    self.audio_queue.put(filename)
                    frames = []
                    is_recording_segment = False
                    silence_frames = 0
            except Exception as e:
                print(f"音频录制错误: {e}")
                self.stop_event.set()
                break
        try:
            stream.stop_stream()
            stream.close()
        except Exception:
            pass
        try:
            p.terminate()
        except Exception:
            pass

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
                language_setting = self.config.get("whisper_language", "auto")
                language = None if language_setting == "auto" else language_setting
                result = self.whisper_model.transcribe(
                    filepath,
                    language=language,
                    fp16=torch.cuda.is_available(),
                    task="transcribe"
                )
                text = result.get("text", "").strip()
                if text:
                    self.transcription_queue.put(text)
                self.update_status("正在录制...")
            except queue.Empty:
                continue
            except Exception as e:
                print(f"转写文件时发生错误: {e}")

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
        
        # 添加截图按钮
        self.screenshot_button = tk.Button(self.button_frame, text="📸 截图", command=self.take_screenshot)
        self.screenshot_button.pack(side=tk.LEFT, padx=5)
        
        # 添加手动总结按钮
        self.manual_summary_button = tk.Button(self.button_frame, text="📝 手动总结", command=self.manual_summary)
        self.manual_summary_button.pack(side=tk.LEFT, padx=5)
        self.manual_summary_button["state"] = "disabled"  # 默认禁用，只有选中文本时才启用
        
        self.save_button = tk.Button(self.button_frame, text="保存为 Markdown", command=self.save_as_markdown)
        self.save_button.pack(side=tk.LEFT, padx=5)

        # --- 可拖拽的双面板 ---
        self.paned_window = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, sashrelief=tk.RAISED)
        self.paned_window.pack(expand=True, fill="both", padx=10, pady=10)

        # --- 左侧：笔记总结（富文本编辑器） ---
        self.summary_frame = tk.Frame(self.paned_window)
        self.summary_label = tk.Label(self.summary_frame, text="笔记总结（可编辑，支持图片粘贴）", font=("微软雅黑", 12, "bold"))
        self.summary_label.pack(anchor=tk.W, pady=(0, 5))
        
        # 创建富文本编辑器
        summary_scrollbar = tk.Scrollbar(self.summary_frame)
        summary_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.summary_area = RichTextEditor(
            self.summary_frame,
            on_change=self.on_editor_changed,
            wrap=tk.WORD,
            font=("微软雅黑", 12),
            height=20,
            yscrollcommand=summary_scrollbar.set
        )
        self.summary_area.pack(expand=True, fill="both")
        summary_scrollbar.config(command=self.summary_area.text_widget.yview)
        self.paned_window.add(self.summary_frame, width=500) # 设置初始宽度

        # --- 右侧：原始语音转文字 ---
        self.transcription_frame = tk.Frame(self.paned_window)
        self.transcription_label = tk.Label(self.transcription_frame, text="原始语音转文字", font=("微软雅黑", 12, "bold"))
        self.transcription_label.pack(anchor=tk.W, pady=(0, 5))
        
        # 创建可选择的文本区域，使用 SimpleTextEditor
        transcription_scrollbar = tk.Scrollbar(self.transcription_frame)
        transcription_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.transcription_area = SimpleTextEditor(
            self.transcription_frame, 
            on_change=self.on_editor_changed,
            wrap=tk.WORD, 
            font=("微软雅黑", 12),
            height=20,
            yscrollcommand=transcription_scrollbar.set
        )
        self.transcription_area.pack(expand=True, fill="both")
        transcription_scrollbar.config(command=self.transcription_area.text_widget.yview)
        
        # 优化：仅在选择释放或按键时检查，避免拖动时卡顿
        self.transcription_area.bind("<ButtonRelease-1>", self.on_text_selection)
        self.transcription_area.bind("<KeyRelease>", self.on_text_selection)
        
        self.paned_window.add(self.transcription_frame, width=700) # 设置初始宽度

    def on_text_selection(self, event=None):
        """当文本选择改变时调用"""
        try:
            # 检查是否有选中的文本
            if self.transcription_area.text_widget.tag_ranges(tk.SEL):
                self.manual_summary_button["state"] = "normal"
            else:
                self.manual_summary_button["state"] = "disabled"
        except tk.TclError:
            # 窗口关闭时可能会出现此错误
            pass

    def manual_summary(self):
        """手动总结选中的文本"""
        try:
            selected_text = self.transcription_area.get(tk.SEL_FIRST, tk.SEL_LAST)
            if not selected_text.strip():
                messagebox.showwarning("警告", "请先选择要总结的文本")
                return
            
            if len(selected_text.strip()) < 10:
                messagebox.showwarning("警告", "选中的文本太短，请选择更多内容")
                return
            
            self.manual_summary_button["state"] = "disabled"
            self.update_status("正在生成手动总结...")
            
            threading.Thread(target=self._do_manual_summary, args=(selected_text,), daemon=True).start()
            
        except tk.TclError:
            messagebox.showwarning("警告", "请先选择要总结的文本")
        except Exception as e:
            messagebox.showerror("错误", f"手动总结失败: {e}")
            self.manual_summary_button["state"] = "normal"

    def _do_manual_summary(self, selected_text):
        """执行手动总结"""
        try:
            max_chars = self.config.get("manual_summary_max_chars", 20000)
            if self.config.get("llm_provider") == "Gemini":
                max_chars = min(max_chars, 6000)
            text_to_summarize = selected_text[-max_chars:] if len(selected_text) > max_chars else selected_text
            
            prompt = SUMMARY_PROMPT.format(text_to_summarize)
            summary_content = self.call_llm_with_retries(prompt, retries=RETRY_MAX_ATTEMPTS, base_delay=RETRY_BASE_DELAY)
            
            if summary_content and summary_content.strip():
                self.root.after(0, self._update_manual_summary_ui, summary_content.strip())
            else:
                self.root.after(0, self._manual_summary_failed)
                
        except Exception as e:
            self.root.after(0, self._manual_summary_error, str(e))

    def _update_manual_summary_ui(self, summary_content):
        """更新手动总结的UI并优化标签"""
        try:
            self.summary_area.insert(tk.END, summary_content + "\n\n")
            self.summary_area.see(tk.END)
            
            text_widget = self.transcription_area.text_widget
            start_index = text_widget.index(tk.SEL_FIRST)
            end_index = text_widget.index(tk.SEL_LAST)

            text_widget.tag_configure("summarized", foreground="blue")

            if start_index != "1.0":
                prev_char_index = text_widget.index(f"{start_index} - 1 char")
                if "summarized" in text_widget.tag_names(prev_char_index):
                    ranges = text_widget.tag_ranges("summarized")
                    for i in range(0, len(ranges), 2):
                        if text_widget.compare(ranges[i], "<=", prev_char_index) and text_widget.compare(ranges[i+1], ">=", prev_char_index):
                            start_index = ranges[i]
                            break
            
            next_char_index = text_widget.index(f"{end_index}")
            if "summarized" in text_widget.tag_names(next_char_index):
                ranges = text_widget.tag_ranges("summarized")
                for i in range(0, len(ranges), 2):
                    if text_widget.compare(ranges[i], "<=", next_char_index) and text_widget.compare(ranges[i+1], ">=", next_char_index):
                        end_index = ranges[i+1]
                        break
            
            text_widget.tag_remove("summarized", start_index, end_index)
            text_widget.tag_add("summarized", start_index, end_index)
            
            text_widget.tag_remove(tk.SEL, "1.0", tk.END)
            
            self.update_status("手动总结完成")
            self.manual_summary_button["state"] = "disabled"
            self.schedule_autosave()
            
        except Exception as e:
            self._manual_summary_error(str(e))

    def _manual_summary_failed(self):
        """手动总结失败"""
        self.update_status("手动总结失败，请重试")
        self.manual_summary_button["state"] = "normal"
        messagebox.showwarning("总结失败", "无法生成总结，请检查模型配置或重试")

    def _manual_summary_error(self, error_msg):
        """手动总结出错"""
        self.update_status("手动总结出错")
        self.manual_summary_button["state"] = "normal"
        messagebox.showerror("总结错误", f"总结过程中发生错误: {error_msg}")

    def manual_summary(self):
        """手动总结选中的文本"""
        try:
            selected_text = self.transcription_area.get(tk.SEL_FIRST, tk.SEL_LAST)
            if not selected_text.strip():
                messagebox.showwarning("警告", "请先选择要总结的文本")
                return
            
            if len(selected_text.strip()) < 10:
                messagebox.showwarning("警告", "选中的文本太短，请选择更多内容")
                return
            
            self.manual_summary_button["state"] = "disabled"
            self.update_status("正在生成手动总结...")
            
            threading.Thread(target=self._do_manual_summary, args=(selected_text,), daemon=True).start()
            
        except tk.TclError:
            messagebox.showwarning("警告", "请先选择要总结的文本")
        except Exception as e:
            messagebox.showerror("错误", f"手动总结失败: {e}")
            self.manual_summary_button["state"] = "normal"

    def _do_manual_summary(self, selected_text):
        """执行手动总结"""
        try:
            max_chars = self.config.get("manual_summary_max_chars", 20000)
            if self.config.get("llm_provider") == "Gemini":
                max_chars = min(max_chars, 6000)
            text_to_summarize = selected_text[-max_chars:] if len(selected_text) > max_chars else selected_text
            
            prompt = SUMMARY_PROMPT.format(text_to_summarize)
            summary_content = self.call_llm_with_retries(prompt, retries=RETRY_MAX_ATTEMPTS, base_delay=RETRY_BASE_DELAY)
            
            if summary_content and summary_content.strip():
                self.root.after(0, self._update_manual_summary_ui, summary_content.strip())
            else:
                self.root.after(0, self._manual_summary_failed)
                
        except Exception as e:
            self.root.after(0, self._manual_summary_error, str(e))

    def _update_manual_summary_ui(self, summary_content):
        """更新手动总结的UI并优化标签"""
        try:
            self.summary_area.insert(tk.END, summary_content + "\n\n")
            self.summary_area.see(tk.END)
            
            text_widget = self.transcription_area.text_widget
            start_index = text_widget.index(tk.SEL_FIRST)
            end_index = text_widget.index(tk.SEL_LAST)

            text_widget.tag_configure("summarized", foreground="blue")

            if start_index != "1.0":
                prev_char_index = text_widget.index(f"{start_index} - 1 char")
                if "summarized" in text_widget.tag_names(prev_char_index):
                    ranges = text_widget.tag_ranges("summarized")
                    for i in range(0, len(ranges), 2):
                        if text_widget.compare(ranges[i], "<=", prev_char_index) and text_widget.compare(ranges[i+1], ">=", prev_char_index):
                            start_index = ranges[i]
                            break
            
            next_char_index = text_widget.index(f"{end_index}")
            if "summarized" in text_widget.tag_names(next_char_index):
                ranges = text_widget.tag_ranges("summarized")
                for i in range(0, len(ranges), 2):
                    if text_widget.compare(ranges[i], "<=", next_char_index) and text_widget.compare(ranges[i+1], ">=", next_char_index):
                        end_index = ranges[i+1]
                        break
            
            text_widget.tag_remove("summarized", start_index, end_index)
            text_widget.tag_add("summarized", start_index, end_index)
            
            text_widget.tag_remove(tk.SEL, "1.0", tk.END)
            
            self.update_status("手动总结完成")
            self.manual_summary_button["state"] = "disabled"
            self.schedule_autosave()
            
        except Exception as e:
            self._manual_summary_error(str(e))

    def _manual_summary_failed(self):
        """手动总结失败"""
        self.update_status("手动总结失败，请重试")
        self.manual_summary_button["state"] = "normal"
        messagebox.showwarning("总结失败", "无法生成总结，请检查模型配置或重试")

    def manual_summary(self):
        """手动总结选中的文本"""
        try:
            selected_text = self.transcription_area.get(tk.SEL_FIRST, tk.SEL_LAST)
            if not selected_text.strip():
                messagebox.showwarning("警告", "请先选择要总结的文本")
                return
            
            if len(selected_text.strip()) < 10:
                messagebox.showwarning("警告", "选中的文本太短，请选择更多内容")
                return
            
            self.manual_summary_button["state"] = "disabled"
            self.update_status("正在生成手动总结...")
            
            threading.Thread(target=self._do_manual_summary, args=(selected_text,), daemon=True).start()
            
        except tk.TclError:
            messagebox.showwarning("警告", "请先选择要总结的文本")
        except Exception as e:
            messagebox.showerror("错误", f"手动总结失败: {e}")
            self.manual_summary_button["state"] = "normal"

    def _do_manual_summary(self, selected_text):
        """执行手动总结"""
        try:
            max_chars = self.config.get("manual_summary_max_chars", 20000)
            if self.config.get("llm_provider") == "Gemini":
                max_chars = min(max_chars, 6000)
            text_to_summarize = selected_text[-max_chars:] if len(selected_text) > max_chars else selected_text
            
            prompt = SUMMARY_PROMPT.format(text_to_summarize)
            summary_content = self.call_llm_with_retries(prompt, retries=RETRY_MAX_ATTEMPTS, base_delay=RETRY_BASE_DELAY)
            
            if summary_content and summary_content.strip():
                self.root.after(0, self._update_manual_summary_ui, summary_content.strip())
            else:
                self.root.after(0, self._manual_summary_failed)
                
        except Exception as e:
            self.root.after(0, self._manual_summary_error, str(e))

    def _update_manual_summary_ui(self, summary_content):
        """更新手动总结的UI并优化标签"""
        try:
            self.summary_area.insert(tk.END, summary_content + "\n\n")
            self.summary_area.see(tk.END)
            
            text_widget = self.transcription_area.text_widget
            start_index = text_widget.index(tk.SEL_FIRST)
            end_index = text_widget.index(tk.SEL_LAST)

            text_widget.tag_configure("summarized", foreground="blue")

            if start_index != "1.0":
                prev_char_index = text_widget.index(f"{start_index} - 1 char")
                if "summarized" in text_widget.tag_names(prev_char_index):
                    ranges = text_widget.tag_ranges("summarized")
                    for i in range(0, len(ranges), 2):
                        if text_widget.compare(ranges[i], "<=", prev_char_index) and text_widget.compare(ranges[i+1], ">=", prev_char_index):
                            start_index = ranges[i]
                            break
            
            next_char_index = text_widget.index(f"{end_index}")
            if "summarized" in text_widget.tag_names(next_char_index):
                ranges = text_widget.tag_ranges("summarized")
                for i in range(0, len(ranges), 2):
                    if text_widget.compare(ranges[i], "<=", next_char_index) and text_widget.compare(ranges[i+1], ">=", next_char_index):
                        end_index = ranges[i+1]
                        break
            
            text_widget.tag_remove("summarized", start_index, end_index)
            text_widget.tag_add("summarized", start_index, end_index)
            
            text_widget.tag_remove(tk.SEL, "1.0", tk.END)
            
            self.update_status("手动总结完成")
            self.manual_summary_button["state"] = "disabled"
            self.schedule_autosave()
            
        except Exception as e:
            self._manual_summary_error(str(e))

    def _manual_summary_failed(self):
        """手动总结失败"""
        self.update_status("手动总结失败，请重试")
        self.manual_summary_button["state"] = "normal"
        messagebox.showwarning("总结失败", "无法生成总结，请检查模型配置或重试")

    def manual_summary(self):
        """手动总结选中的文本"""
        try:
            # 获取选中的文本
            selected_text = self.transcription_area.get(tk.SEL_FIRST, tk.SEL_LAST)
            if not selected_text.strip():
                messagebox.showwarning("警告", "请先选择要总结的文本")
                return
            
            if len(selected_text.strip()) < 10:
                messagebox.showwarning("警告", "选中的文本太短，请选择更多内容")
                return
            
            self.manual_summary_button["state"] = "disabled"
            self.update_status("正在生成手动总结...")
            
            threading.Thread(target=self._do_manual_summary, args=(selected_text,), daemon=True).start()
            
        except tk.TclError:
            messagebox.showwarning("警告", "请先选择要总结的文本")
        except Exception as e:
            messagebox.showerror("错误", f"手动总结失败: {e}")
            self.manual_summary_button["state"] = "normal"

    def _do_manual_summary(self, selected_text):
        """执行手动总结"""
        try:
            # 手动总结使用更大的字符限制，或者不限制
            max_chars = self.config.get("manual_summary_max_chars", 20000)
            # 如果是 Gemini，适当降低上限，避免 429/超时
            if self.config.get("llm_provider") == "Gemini":
                max_chars = min(max_chars, 6000)
            text_to_summarize = selected_text[-max_chars:] if len(selected_text) > max_chars else selected_text
            
            # 生成总结
            prompt = SUMMARY_PROMPT.format(text_to_summarize)
            summary_content = self.call_llm_with_retries(prompt, retries=RETRY_MAX_ATTEMPTS, base_delay=RETRY_BASE_DELAY)
            
            if summary_content and summary_content.strip():
                # 在主线程中更新UI
                self.root.after(0, self._update_manual_summary_ui, summary_content.strip())
            else:
                self.root.after(0, self._manual_summary_failed)
                
        except Exception as e:
            self.root.after(0, self._manual_summary_error, str(e))

    def _update_manual_summary_ui(self, summary_content):
        """更新手动总结的UI并优化标签"""
        try:
            # 将总结添加到总结区域
            self.summary_area.insert(tk.END, summary_content + "\n\n")
            self.summary_area.see(tk.END)
            
            # --- 优化：标记已总结文本并合并相邻标签 ---
            text_widget = self.transcription_area.text_widget
            start_index = text_widget.index(tk.SEL_FIRST)
            end_index = text_widget.index(tk.SEL_LAST)

            text_widget.tag_configure("summarized", foreground="blue")

            # 检查并合并前面的标签
            if start_index != "1.0":
                prev_char_index = text_widget.index(f"{start_index} - 1 char")
                if "summarized" in text_widget.tag_names(prev_char_index):
                    ranges = text_widget.tag_ranges("summarized")
                    for i in range(0, len(ranges), 2):
                        if text_widget.compare(ranges[i], "<=", prev_char_index) and text_widget.compare(ranges[i+1], ">=", prev_char_index):
                            start_index = ranges[i]
                            break
            
            # 检查并合并后面的标签
            next_char_index = text_widget.index(f"{end_index}")
            if "summarized" in text_widget.tag_names(next_char_index):
                ranges = text_widget.tag_ranges("summarized")
                for i in range(0, len(ranges), 2):
                    if text_widget.compare(ranges[i], "<=", next_char_index) and text_widget.compare(ranges[i+1], ">=", next_char_index):
                        end_index = ranges[i+1]
                        break
            
            text_widget.tag_remove("summarized", start_index, end_index)
            text_widget.tag_add("summarized", start_index, end_index)
            # ------------------------------------------
            
            # 清除选择
            text_widget.tag_remove(tk.SEL, "1.0", tk.END)
            
            self.update_status("手动总结完成")
            self.manual_summary_button["state"] = "disabled"
            # 触发保存
            self.schedule_autosave()
            
        except Exception as e:
            self._manual_summary_error(str(e))

    def summary_loop(self):
        """定期检查和总结文本（仅在自动模式下）"""
        while not self.stop_event.is_set():
            # 每次循环都检查配置，确保实时响应配置变化
            if self.config.get("summary_mode", "auto") != "auto":
                time.sleep(5)
                continue
            # 自动模式下按配置的间隔执行
            time.sleep(self.config.get("auto_summary_interval", 300))
            # 再次检查，防止间隔期间模式被切换
            if self.config.get("summary_mode", "auto") == "auto":
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
        """获取新增文本并生成总结（仅在自动模式下）"""
        if self.config.get("summary_mode", "auto") != "auto":
            return  # 手动模式下不执行自动总结
        # 提取上次总结后的新文本
        text_to_analyze = self.transcription_history[self.last_summary_text_len:]
        if not text_to_analyze or len(text_to_analyze) < MIN_TEXT_FOR_SUMMARY:
            print(f"新增文本过短 ({len(text_to_analyze)}字)，不进行总结。")
            return
        # 限制提交给模型的文本长度（取最近的内容，更利于上下文连贯）
        max_chars = self.config.get("auto_summary_max_chars", 8000)
        bounded_text = text_to_analyze[-max_chars:]
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
            # 触发保存
            self.schedule_autosave()
        else:
            self.update_status("大模型未返回有效总结，继续监听...")
            print("大模型未返回有效的总结，继续积累文本。")

    def start_recording(self):
        self.is_recording = True
        self.start_button["state"] = "disabled"
        self.stop_button["state"] = "normal"
        self.stop_event = threading.Event()
        
        self.recorder_thread = threading.Thread(target=self.record_audio, daemon=True)
        self.transcriber_thread = threading.Thread(target=self.transcribe_audio, daemon=True)
        
        # 只有在自动模式下才启动总结线程
        if self.config.get("summary_mode", "auto") == "auto":
            self.summary_thread = threading.Thread(target=self.summary_loop, daemon=True)
            self.summary_thread.start()
        else:
            self.summary_thread = None
        
        self.recorder_thread.start()
        self.transcriber_thread.start()
        
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
        
    def call_llm(self, prompt):
        """调用大语言模型API"""
        if self.config["llm_provider"] == "Ollama":
            return self.call_ollama(prompt)
        elif self.config["llm_provider"] == "Gemini":
            return self.call_gemini(prompt)
        else:
            print(f"未知的LLM提供商: {self.config['llm_provider']}")
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
            last_response_line = response_text.strip().split("\n")[-1]
            try:
                data = json.loads(last_response_line)
                raw_response = data.get("response", "")
                
                # 使用正则表达式移除 <think> 标签及其内容
                clean_response = re.sub(r"<think>.*?</think>", "", raw_response, flags=re.DOTALL).strip()
                return clean_response or None
            except (json.JSONDecodeError, IndexError, KeyError):
                print("警告：无法解析大模型响应，返回原始文本。")
                return (response_text or None)
        except requests.exceptions.RequestException as e:
            print(f"Ollama API调用错误: {e}")
            self.update_status("Ollama API调用失败，请检查服务。")
            return None

    def call_gemini(self, prompt):
        """调用 Gemini API（带状态码感知重试 + 404 模型回退 + v1beta 兜底）"""
        if not self.config["gemini_api_key"]:
            print("错误：Gemini API Key未配置")
            self.update_status("Gemini API Key未配置")
            return None
            
        headers = {
            "Content-Type": "application/json"
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
                        "parts": [{"text": prompt}]
                    }]
                }
                for attempt in range(1, RETRY_MAX_ATTEMPTS + 1):
                    try:
                        print("\n--- 发送给Gemini的提示词（用于调试） ---")
                        print(prompt[:2000] + ("...[truncated]" if len(prompt) > 2000 else ""))
                        print(f"使用模型: {model_name} | API: {api_version}")
                        print("-------------------------------------------\n")

                        response = requests.post(url, headers=headers, json=payload, timeout=90)

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
        config_window.geometry("500x600")  # 增加高度
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
        
        # 语言检测配置
        language_frame = tk.LabelFrame(main_frame, text="语言检测配置", font=("微软雅黑", 9))
        language_frame.pack(fill=tk.X, pady=(0, 15))
        
        self.language_var = tk.StringVar(value=self.config.get("whisper_language", "auto"))
        language_radio_frame = tk.Frame(language_frame)
        language_radio_frame.pack(anchor=tk.W, pady=(10, 5))
        
        tk.Radiobutton(language_radio_frame, text="自动检测", variable=self.language_var, 
                      value="auto", command=self.on_language_change).pack(side=tk.LEFT, padx=(10, 20))
        tk.Radiobutton(language_radio_frame, text="中文", variable=self.language_var, 
                      value="zh", command=self.on_language_change).pack(side=tk.LEFT, padx=(0, 20))
        tk.Radiobutton(language_radio_frame, text="英文", variable=self.language_var, 
                      value="en", command=self.on_language_change).pack(side=tk.LEFT)
        
        # 总结模式配置
        summary_mode_frame = tk.LabelFrame(main_frame, text="总结模式配置", font=("微软雅黑", 9))
        summary_mode_frame.pack(fill=tk.X, pady=(0, 15))
        
        self.summary_mode_var = tk.StringVar(value=self.config.get("summary_mode", "auto"))
        summary_mode_radio_frame = tk.Frame(summary_mode_frame)
        summary_mode_radio_frame.pack(anchor=tk.W, pady=(10, 5))
        
        tk.Radiobutton(summary_mode_radio_frame, text="自动总结", variable=self.summary_mode_var, 
                      value="auto", command=self.on_summary_mode_change).pack(side=tk.LEFT, padx=(10, 20))
        tk.Radiobutton(summary_mode_radio_frame, text="手动总结", variable=self.summary_mode_var, 
                      value="manual", command=self.on_summary_mode_change).pack(side=tk.LEFT)
        
        # 自动总结间隔配置
        self.auto_interval_frame = tk.Frame(summary_mode_frame)
        self.auto_interval_frame.pack(fill=tk.X, pady=(5, 10), padx=10)
        
        tk.Label(self.auto_interval_frame, text="自动总结间隔（秒）:").pack(side=tk.LEFT)
        self.auto_interval_var = tk.StringVar(value=str(self.config.get("auto_summary_interval", 300)))
        auto_interval_entry = tk.Entry(self.auto_interval_frame, textvariable=self.auto_interval_var, width=10)
        auto_interval_entry.pack(side=tk.LEFT, padx=(5, 0))
        
        # 文本截断配置
        truncation_frame = tk.LabelFrame(main_frame, text="文本截断配置", font=("微软雅黑", 9))
        truncation_frame.pack(fill=tk.X, pady=(0, 15))
        
        # 自动总结截断长度
        auto_truncation_frame = tk.Frame(truncation_frame)
        auto_truncation_frame.pack(fill=tk.X, pady=(10, 5), padx=10)
        
        tk.Label(auto_truncation_frame, text="自动总结最大字符数:").pack(side=tk.LEFT)
        self.auto_max_chars_var = tk.StringVar(value=str(self.config.get("auto_summary_max_chars", 8000)))
        auto_max_chars_entry = tk.Entry(auto_truncation_frame, textvariable=self.auto_max_chars_var, width=10)
        auto_max_chars_entry.pack(side=tk.LEFT, padx=(5, 0))
        
        # 手动总结截断长度
        manual_truncation_frame = tk.Frame(truncation_frame)
        manual_truncation_frame.pack(fill=tk.X, pady=(5, 10), padx=10)
        
        tk.Label(manual_truncation_frame, text="手动总结最大字符数:").pack(side=tk.LEFT)
        self.manual_max_chars_var = tk.StringVar(value=str(self.config.get("manual_summary_max_chars", 20000)))
        manual_max_chars_entry = tk.Entry(manual_truncation_frame, textvariable=self.manual_max_chars_var, width=10)
        manual_max_chars_entry.pack(side=tk.LEFT, padx=(5, 0))
        
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
        self.on_summary_mode_change()
        
        # 绑定关闭事件
        config_window.protocol("WM_DELETE_WINDOW", config_window.destroy)
    
    def on_language_change(self):
        """当语言选择改变时更新界面"""
        pass  # 暂时不需要特殊处理

    def on_summary_mode_change(self):
        """当总结模式改变时更新界面"""
        if self.summary_mode_var.get() == "auto":
            self.auto_interval_frame.pack(fill=tk.X, pady=(5, 10), padx=10)
        else:
            self.auto_interval_frame.pack_forget()

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
        self.config["summary_mode"] = self.summary_mode_var.get()
        self.config["whisper_language"] = self.language_var.get()
        
        # 验证自动总结间隔
        try:
            interval = int(self.auto_interval_var.get())
            if interval < 30:
                messagebox.showwarning("警告", "自动总结间隔不能少于30秒")
                return
            self.config["auto_summary_interval"] = interval
        except ValueError:
            messagebox.showwarning("警告", "自动总结间隔必须是数字")
            return
        
        # 验证截断长度配置
        try:
            auto_max_chars = int(self.auto_max_chars_var.get())
            if auto_max_chars < 100:
                messagebox.showwarning("警告", "自动总结最大字符数不能少于100")
                return
            self.config["auto_summary_max_chars"] = auto_max_chars
        except ValueError:
            messagebox.showwarning("警告", "自动总结最大字符数必须是数字")
            return
        
        try:
            manual_max_chars = int(self.manual_max_chars_var.get())
            if manual_max_chars < 100:
                messagebox.showwarning("警告", "手动总结最大字符数不能少于100")
                return
            self.config["manual_summary_max_chars"] = manual_max_chars
        except ValueError:
            messagebox.showwarning("警告", "手动总结最大字符数必须是数字")
            return
        
        # 保存到文件
        if save_config(self.config):
            # 如果正在录制，需要重新启动总结线程
            if self.is_recording:
                # 停止当前的总结线程
                if self.summary_thread and self.summary_thread.is_alive():
                    # 等待线程自然结束
                    pass
                
                # 根据新配置启动或停止总结线程
                if self.config.get("summary_mode", "auto") == "auto":
                    self.summary_thread = threading.Thread(target=self.summary_loop, daemon=True)
                    self.summary_thread.start()
                else:
                    self.summary_thread = None
            
            messagebox.showinfo("配置保存", "配置已成功保存！")
            config_window.destroy()
        else:
            messagebox.showerror("配置保存失败", "无法保存配置文件，请检查文件权限。")

    def on_closing(self):
        if self.is_recording:
            if messagebox.askokcancel("退出", "录制仍在进行中。确定要退出吗？"):
                self.stop_recording()
                # 退出前保存一次
                try:
                    self.save_document()
                except Exception:
                    pass
                self.root.destroy()
        else:
            try:
                self.save_document()
            except Exception:
                pass
            self.root.destroy()

    def take_screenshot(self):
        """调用截图工具"""
        if hasattr(self.summary_area, 'take_screenshot'):
            self.summary_area.take_screenshot()
        else:
            messagebox.showerror("错误", "截图功能不可用")

if __name__ == "__main__":
    root = tk.Tk()
    app = TranscriptionApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()