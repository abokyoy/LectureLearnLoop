SUMMARY_PROMPT = """你是一名专业的文本分析和学习笔记助手。我将提供一段实时音频转录的文字片段。你的任务是分析这段文字，并直接输出一个结构化的摘要。

请严格遵守以下规则：
1. 直接输出摘要内容，不要包含任何额外的标题，例如"总结"、"摘要"或"这段内容讨论了什么"之类的前言。
2. 摘要应该以结构化的形式呈现，例如使用项目符号（-）或编号来组织要点。
3. 你的目标是清晰、简洁地总结出文本片段中的核心信息。
4. 如果提供的文本片段没有实质性内容可供总结，请返回空。

原始文本片段如下：

---

{}
"""

# --- 大语言模型配置 ---
# 服务商: "Ollama" 或 "Gemini"
LLM_PROVIDER = "Ollama"

# Ollama 配置
OLLAMA_API_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "deepseek-r1:1.5b"

# Gemini API Key (如果你使用Gemini，请填写你的API Key)
GEMINI_API_KEY = ""

# 使用的Gemini模型
GEMINI_MODEL = "gemini-1.5-flash-002"

# 总结模式配置
SUMMARY_MODE = "auto"  # "auto" 或 "manual"
AUTO_SUMMARY_INTERVAL = 300  # 自动总结间隔时间（秒）

# 文本截断配置
AUTO_SUMMARY_MAX_CHARS = 8000  # 自动总结的最大字符数
MANUAL_SUMMARY_MAX_CHARS = 20000  # 手动总结的最大字符数（更大，不截断）

# 配置保存文件
CONFIG_FILE = "app_config.json"

def load_config():
    """加载配置文件"""
    import json
    import os
    
    default_config = {
        "llm_provider": "Ollama",
        "ollama_model": "deepseek-r1:1.5b",
        "ollama_api_url": "http://localhost:11434/api/generate",
        "gemini_api_key": "",
        "gemini_model": "gemini-1.5-flash-002",
        "summary_mode": "auto",
        "auto_summary_interval": 300,
        "whisper_language": "auto",
        "auto_summary_max_chars": 8000,
        "manual_summary_max_chars": 20000
    }
    
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
                # 合并默认配置，确保所有必要的键都存在
                for key, value in default_config.items():
                    if key not in config:
                        config[key] = value
                return config
        except Exception as e:
            print(f"加载配置文件失败: {e}")
            return default_config
    else:
        return default_config

def save_config(config):
    """保存配置文件"""
    import json
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"保存配置文件失败: {e}")
        return False
