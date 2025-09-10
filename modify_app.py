import re

# 读取原始文件
with open("app.py", "r", encoding="utf-8") as f:
    content = f.read()

# 1. 添加ttk导入
content = content.replace("from tkinter import scrolledtext, messagebox, filedialog", "from tkinter import scrolledtext, messagebox, filedialog, ttk")

# 2. 修改导入配置
content = content.replace("from config import SUMMARY_PROMPT", "from config import SUMMARY_PROMPT, load_config, save_config")

# 3. 移除旧的配置常量
old_config = """# --- Ollama 配置 ---
OLLAMA_API_URL = \"http://localhost:11434/api/generate\"
OLLAMA_MODEL = \"deepseek-r1:1.5b\"
TRANSCRIPTION_LOG_FILE = \"transcription.txt\"

# --- 总结配置 ---
SUMMARY_CHECK_INTERVAL = 300 # 每300秒（5分钟）检查一次
MIN_TEXT_FOR_SUMMARY = 50 # 降低门槛，至少有50字新增文本才触发总结
# SUMMARY_PROMPT 在 config.py 中定义"""

new_config = """# --- 总结配置 ---
SUMMARY_CHECK_INTERVAL = 300 # 每300秒（5分钟）检查一次
MIN_TEXT_FOR_SUMMARY = 50 # 降低门槛，至少有50字新增文本才触发总结
TRANSCRIPTION_LOG_FILE = \"transcription.txt\"
# SUMMARY_PROMPT 在 config.py 中定义"""

content = content.replace(old_config, new_config)

# 4. 修改__init__方法
old_init = """        self.transcription_history = \"\"

        self.setup_ui()
        self.check_transcription_queue()"""

new_init = """        self.transcription_history = \"\"
        
        # 加载配置
        self.config = load_config()

        self.setup_ui()
        self.check_transcription_queue()"""

content = content.replace(old_init, new_init)

# 5. 添加配置按钮
old_buttons = """        self.stop_button = tk.Button(self.button_frame, text=\"停止录制\", command=self.stop_recording)
        self.stop_button.pack(side=tk.LEFT, padx=5)
        self.stop_button[\"state\"] = \"disabled\"
        
        self.save_button = tk.Button(self.button_frame, text=\"保存为 Markdown\", command=self.save_as_markdown)
        self.save_button.pack(side=tk.LEFT, padx=5)"""

new_buttons = """        self.stop_button = tk.Button(self.button_frame, text=\"停止录制\", command=self.stop_recording)
        self.stop_button.pack(side=tk.LEFT, padx=5)
        self.stop_button[\"state\"] = \"disabled\"
        
        self.config_button = tk.Button(self.button_frame, text=\"配置模型\", command=self.open_config_dialog)
        self.config_button.pack(side=tk.LEFT, padx=5)
        
        self.save_button = tk.Button(self.button_frame, text=\"保存为 Markdown\", command=self.save_as_markdown)
        self.save_button.pack(side=tk.LEFT, padx=5)"""

content = content.replace(old_buttons, new_buttons)

# 6. 修改call_ollama方法
old_call_ollama = """    def call_ollama(self, prompt):
        \"\"\"调用 Ollama API，处理结构化 JSON 返回\"\"\"
        payload = {
            \"model\": OLLAMA_MODEL,
            \"prompt\": prompt,
            \"stream\": False,
        }"""

new_call_ollama = """    def call_llm(self, prompt):
        \"\"\"调用大语言模型API\"\"\"
        if self.config[\"llm_provider\"] == \"Ollama\":
            return self.call_ollama(prompt)
        elif self.config[\"llm_provider\"] == \"Gemini\":
            return self.call_gemini(prompt)
        else:
            print(f\"未知的LLM提供商: {self.config[
llm_provider]}\")
            return prompt

    def call_ollama(self, prompt):
        \"\"\"调用 Ollama API，处理结构化 JSON 返回\"\"\"
        payload = {
            \"model\": self.config[\"ollama_model\"],
            \"prompt\": prompt,
            \"stream\": False,
        }"""

content = content.replace(old_call_ollama, new_call_ollama)

# 7. 修改Ollama API调用
content = content.replace("response = requests.post(OLLAMA_API_URL, json=payload, timeout=90)", "response = requests.post(self.config[\"ollama_api_url\"], json=payload, timeout=90)")

# 8. 修改process_summary中的调用
content = content.replace("summary_content = self.call_ollama(prompt).strip()", "summary_content = self.call_llm(prompt).strip()")

# 9. 在文件末尾添加新方法
old_end = """    def on_closing(self):
        if self.is_recording:
            if messagebox.askokcancel(\"退出\", \"录制仍在进行中。确定要退出吗？\"):
                self.stop_recording()
                self.root.destroy()
        else:
            self.root.destroy()"""

new_end = """    def call_gemini(self, prompt):
        \"\"\"调用 Gemini API\"\"\"
        if not self.config[\"gemini_api_key\"]:
            print(\"错误：Gemini API Key未配置\")
            self.update_status(\"Gemini API Key未配置\")
            return prompt
            
        url = f\"https://generativelanguage.googleapis.com/v1beta/models/{self.config[gemini_model]}:generateContent?key={self.config[gemini_api_key]}\"
        
        payload = {
            \"contents\": [{
                \"parts\": [{\"text\": prompt}]
            }]
        }
        
        try:
            print(\"\\n--- 发送给Gemini的提示词（用于调试） ---\")
            print(prompt)
            print(\"-------------------------------------------\\n\")

            response = requests.post(url, json=payload, timeout=90)
            response.raise_for_status()
            
            data = response.json()
            
            print(\"\\n--- Gemini原始响应（用于调试） ---\")
            print(json.dumps(data, ensure_ascii=False, indent=2))
            print(\"---------------------------------------\\n\")
            
            if \"candidates\" in data and len(data[\"candidates\"]) > 0:
                content = data[\"candidates\"][0][\"content\"][\"parts\"][0][\"text\"]
                return content
            else:
                print(\"警告：Gemini响应格式异常\")
                return prompt
                
        except requests.exceptions.RequestException as e:
            print(f\"Gemini API调用错误: {e}\")
            self.update_status(\"Gemini API调用失败，请检查网络和API Key。\")
            return prompt

    def open_config_dialog(self):
        \"\"\"打开配置对话框\"\"\"
        config_window = tk.Toplevel(self.root)
        config_window.title(\"模型配置\")
        config_window.geometry(\"500x400\")
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
        
        tk.Label(provider_frame, text=\"大语言模型提供商:\", font=(\"微软雅黑\", 10, \"bold\")).pack(anchor=tk.W)
        
        self.provider_var = tk.StringVar(value=self.config[\"llm_provider\"])
        provider_radio_frame = tk.Frame(provider_frame)
        provider_radio_frame.pack(anchor=tk.W, pady=(5, 0))
        
        tk.Radiobutton(provider_radio_frame, text=\"Ollama (本地)\", variable=self.provider_var, 
                      value=\"Ollama\", command=self.on_provider_change).pack(side=tk.LEFT, padx=(0, 20))
        tk.Radiobutton(provider_radio_frame, text=\"Gemini (云端)\", variable=self.provider_var, 
                      value=\"Gemini\", command=self.on_provider_change).pack(side=tk.LEFT)
        
        # Ollama配置框架
        self.ollama_frame = tk.LabelFrame(main_frame, text=\"Ollama 配置\", font=(\"微软雅黑\", 9))
        self.ollama_frame.pack(fill=tk.X, pady=(0, 15))
        
        # API URL
        tk.Label(self.ollama_frame, text=\"API URL:\").pack(anchor=tk.W, padx=10, pady=(10, 0))
        self.ollama_url_var = tk.StringVar(value=self.config[\"ollama_api_url\"])
        ollama_url_entry = tk.Entry(self.ollama_frame, textvariable=self.ollama_url_var, width=50)
        ollama_url_entry.pack(fill=tk.X, padx=10, pady=(5, 10))
        
        # 模型名称
        tk.Label(self.ollama_frame, text=\"模型名称:\").pack(anchor=tk.W, padx=10)
        self.ollama_model_var = tk.StringVar(value=self.config[\"ollama_model\"])
        ollama_model_entry = tk.Entry(self.ollama_frame, textvariable=self.ollama_model_var, width=50)
        ollama_model_entry.pack(fill=tk.X, padx=10, pady=(5, 10))
        
        # Gemini配置框架
        self.gemini_frame = tk.LabelFrame(main_frame, text=\"Gemini 配置\", font=(\"微软雅黑\", 9))
        self.gemini_frame.pack(fill=tk.X, pady=(0, 15))
        
        # API Key
        tk.Label(self.gemini_frame, text=\"API Key:\").pack(anchor=tk.W, padx=10, pady=(10, 0))
        self.gemini_key_var = tk.StringVar(value=self.config[\"gemini_api_key\"])
        gemini_key_entry = tk.Entry(self.gemini_frame, textvariable=self.gemini_key_var, width=50, show=\"*\")
        gemini_key_entry.pack(fill=tk.X, padx=10, pady=(5, 10))
        
        # 模型名称
        tk.Label(self.gemini_frame, text=\"模型名称:\").pack(anchor=tk.W, padx=10)
        self.gemini_model_var = tk.StringVar(value=self.config[\"gemini_model\"])
        gemini_model_entry = tk.Entry(self.gemini_frame, textvariable=self.gemini_model_var, width=50)
        gemini_model_entry.pack(fill=tk.X, padx=10, pady=(5, 10))
        
        # 按钮框架
        button_frame = tk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))
        
        tk.Button(button_frame, text=\"保存配置\", command=lambda: self.save_config_and_close(config_window)).pack(side=tk.RIGHT, padx=(5, 0))
        tk.Button(button_frame, text=\"取消\", command=config_window.destroy).pack(side=tk.RIGHT)
        
        # 初始化显示状态
        self.on_provider_change()
        
        # 绑定关闭事件
        config_window.protocol(\"WM_DELETE_WINDOW\", config_window.destroy)
    
    def on_provider_change(self):
        \"\"\"当提供商选择改变时更新界面\"\"\"
        if self.provider_var.get() == \"Ollama\":
            self.ollama_frame.pack(fill=tk.X, pady=(0, 15))
            self.gemini_frame.pack_forget()
        else:
            self.ollama_frame.pack_forget()
            self.gemini_frame.pack(fill=tk.X, pady=(0, 15))
    
    def save_config_and_close(self, config_window):
        \"\"\"保存配置并关闭对话框\"\"\"
        # 更新配置
        self.config[\"llm_provider\"] = self.provider_var.get()
        self.config[\"ollama_api_url\"] = self.ollama_url_var.get()
        self.config[\"ollama_model\"] = self.ollama_model_var.get()
        self.config[\"gemini_api_key\"] = self.gemini_key_var.get()
        self.config[\"gemini_model\"] = self.gemini_model_var.get()
        
        # 保存到文件
        if save_config(self.config):
            messagebox.showinfo(\"配置保存\", \"配置已成功保存！\")
            config_window.destroy()
        else:
            messagebox.showerror(\"配置保存失败\", \"无法保存配置文件，请检查文件权限。\")

    def on_closing(self):
        if self.is_recording:
            if messagebox.askokcancel(\"退出\", \"录制仍在进行中。确定要退出吗？\"):
                self.stop_recording()
                self.root.destroy()
        else:
            self.root.destroy()"""

content = content.replace(old_end, new_end)

# 写入修改后的文件
with open("app.py", "w", encoding="utf-8") as f:
    f.write(content)

print("文件修改完成")
