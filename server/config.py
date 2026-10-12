"""
服务端配置中心 —— 唯一配置来源（.env + 常量路径）。

架构收敛说明：
- 旧工程通过 app_config.json 提供配置（含明文密钥，掉坑笔记 P005），本工程废止该机制；
- `load_config()` 保持与旧 llm_provider_factory / knowledge_management 相同的键名，
  但数据源改为 .env，禁止任何代码再直接读 app_config.json。
"""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------- 路径常量
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
VAULT_DIR = DATA_DIR / "vault"          # vault/<user_id>/...
LOG_DIR = BASE_DIR / "logs"
DB_PATH = DATA_DIR / "knowledge_management.db"
PRACTICE_DB_PATH = DATA_DIR / "practice_history.db"

for _d in (DATA_DIR, VAULT_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- .env
load_dotenv(BASE_DIR / ".env")

SERVER_PORT = int(os.getenv("SERVER_PORT", "9992"))
JWT_SECRET = os.getenv("JWT_SECRET", "")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")
# P6 实测：Deepgram nova-2 language=multi 对中文音频返回空转写，中文课程默认 zh-CN。
# 旧设置页 whisper_language 映射：auto→multi / zh→zh-CN / en→en（可选 "auto"/"zh"/"en"）。
DEEPGRAM_LANGUAGE = os.getenv("DEEPGRAM_LANGUAGE", "zh-CN")
DEEPGRAM_LANGUAGE_MODE = os.getenv("DEEPGRAM_LANGUAGE_MODE", "fixed")  # fixed=用上面固定值；auto=按用户设置页映射
HTTP_PROXY_URL = os.getenv("HTTP_PROXY_URL", "")

# ---------------------------------------------------------------- 文件导入（PaddleOCR-VL 文档解析 Job API）
# key 复用 AIFinFlowX 项目已生产验证的官方接口（落 .env，不落代码）；免费额度按官方政策。
PADDLE_OCR_JOB_URL = os.getenv("PADDLE_OCR_JOB_URL", "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs")
PADDLE_OCR_TOKEN = os.getenv("PADDLE_OCR_TOKEN", "")
PADDLE_OCR_MODEL = os.getenv("PADDLE_OCR_MODEL", "PaddleOCR-VL-1.6")
IMPORT_MAX_BYTES = 200 * 1024 * 1024       # 单文件上限 200MB（2026-10-04 大PDF分段；Flask MAX_CONTENT_LENGTH 同值）

# ---------------------------------------------------------------- 手机拍照传图（错题录入，2026-10-13）
# 独立小服务监听 0.0.0.0:PHOTO_PORT（占用则 9900-9999 内自适应）；主 Flask 仍仅 127.0.0.1（P006 口径不变）。
PHOTO_PORT = int(os.getenv("PHOTO_PORT", "9991"))
PHOTO_PUBLIC_BASE = os.getenv("PHOTO_PUBLIC_BASE", "")  # 公网可达完整前缀，如 http://xxx.oicp.vip:12345（穿透公网端口由服务商定，整串配置不自动拼）
PHOTO_DISABLE = os.getenv("PHOTO_DISABLE", "") == "1"   # 测试/禁用环境不拉起小服务

# ---------------------------------------------------------------- 错题智能分析：视觉大模型（2026-10-13）
# 系统级 VL 通道（硅基流动 OpenAI 兼容）；国内直连，请求侧 trust_env=False 避开 V2RAYN（实测代理对
# paddle/siliconflow 通道会 SSL 握手失败）。用户自备视觉 Key 优先，此段仅作系统兜底。
VL_API_BASE = os.getenv("VL_API_BASE", "https://api.siliconflow.cn/v1")
VL_API_KEY = os.getenv("VL_API_KEY", "")
VL_MODEL = os.getenv("VL_MODEL", "Qwen/Qwen3-VL-32B-Instruct")

# 大 PDF 书籍分段导入（2026-10-04 方案：docs/计划/2026-10-04-大PDF分段导入与阅读基础版方案.md）
PDF_SEG_PAGE_SIZE = 20        # 固定 20 页一个桶段（数字=真实页码，所有落段计算唯一来源）
PDF_BOOK_PAGE_MIN = 20        # 分流主驱动：页数 > 此值才可能走书籍文件夹（体积不得单独作为免除条件，裁定#1）
PDF_BOOK_EXEMPT_PAGES = 60    # 小文件豁免：页数 ≤ 此值且体积 ≤ EXEMPT_SIZE_MB 时不建文件夹（纯文字大书>60页仍走分段）
PDF_BOOK_EXEMPT_SIZE_MB = 10  # 小文件豁免体积上限（MB），与 EXEMPT_PAGES 同时满足才豁免

# ---------------------------------------------------------------- 数据库全局配置（PostgreSQL 唯一后端）
# 架构决策：全面废除 SQLite，全站仅使用 PostgreSQL（见 database/db_adapter.py）。
DB_BACKEND = "postgres"
PG_HOST = os.getenv("PG_HOST", "127.0.0.1")
PG_PORT = int(os.getenv("PG_PORT", "5432"))
PG_DATABASE = os.getenv("PG_DATABASE", "lecturelearnloop")
PG_USER = os.getenv("PG_USER", "postgres")
PG_PASSWORD = os.getenv("PG_PASSWORD", "")
PG_POOL_MIN = int(os.getenv("PG_POOL_MIN", "2"))
PG_POOL_MAX = int(os.getenv("PG_POOL_MAX", "20"))

# admin 种子账号（存量数据 user_id 归属）
ADMIN_USER_ID = "0001"

# ---------------------------------------------------------------- SECRET_KEY 落盘（修复断点 D3）
_SECRET_FILE = DATA_DIR / "flask_secret.key"


def get_flask_secret_key() -> str:
    """持久化的 Flask SECRET_KEY，避免每次重启会话失效。"""
    if _SECRET_FILE.exists():
        return _SECRET_FILE.read_text(encoding="utf-8").strip()
    key = secrets.token_hex(32)
    _SECRET_FILE.write_text(key, encoding="utf-8")
    return key


# ---------------------------------------------------------------- 运行时配置（设置页可改的非 .env 键）
RUNTIME_CONFIG_FILE = DATA_DIR / "runtime_config.json"


# ---------------------------------------------------------------- 兼容旧模块的配置提供者
def load_config() -> dict:
    """
    返回与旧 app_config.json 相同键名的配置 dict。
    LLM 提供商固定为 DeepSeek（用户确认：单一提供商、失败直接报错、不做降级链）。
    """
    cfg = {
        "llm_provider": "DeepSeek",
        # DeepSeek
        "deepseek_api_key": os.getenv("DEEPSEEK_API_KEY", ""),
        "deepseek_model": os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
        "deepseek_api_url": os.getenv(
            "DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions"
        ),
        # 其余提供商键保留为空，防止旧代码 KeyError（今晚不会用到它们）
        "gemini_api_key": "",
        "gemini_model": "",
        "qwen_api_key": "",
        "qwen_model": "",
        "qwen_api_url": "",
        "ollama_url": "http://localhost:11434",
        "ollama_model": "",
        "ollama_api_url": "http://localhost:11434/api/generate",
        # 相似度匹配（业务规则已确认：阈值 0.35）
        "similarity_min_score": float(os.getenv("SIMILARITY_MIN_SCORE", "0.35")),
        # 运行时路径
        "db_path": str(DB_PATH),
        "practice_db_path": str(PRACTICE_DB_PATH),
        "vault_dir": str(VAULT_DIR),
        "http_proxy": HTTP_PROXY_URL,
        # 数据库后端（只读展示；切换只允许通过 .env，设置页不得覆盖）
        "db_backend": DB_BACKEND,
    }
    # 合并设置页保存的运行时配置（P2：saveConfig 桥方法落点）；路径类键不允许覆盖
    if RUNTIME_CONFIG_FILE.exists():
        try:
            overrides = json.loads(RUNTIME_CONFIG_FILE.read_text(encoding="utf-8"))
            _protected = {"db_path", "practice_db_path", "vault_dir", "db_backend"}
            for k, v in overrides.items():
                if k not in _protected:
                    cfg[k] = v
        except Exception:  # noqa: BLE001  运行时配置损坏时静默回退 .env
            pass
    return cfg


def save_runtime_config(updates: dict) -> bool:
    """写入运行时配置（白名单外的键由调用方过滤）；返回是否成功。"""
    try:
        existing = {}
        if RUNTIME_CONFIG_FILE.exists():
            existing = json.loads(RUNTIME_CONFIG_FILE.read_text(encoding="utf-8"))
        existing.update(updates)
        RUNTIME_CONFIG_FILE.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return True
    except Exception:  # noqa: BLE001
        return False
