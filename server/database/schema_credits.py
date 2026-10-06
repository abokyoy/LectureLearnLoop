# -*- coding: utf-8 -*-
"""积分体系表结构（PostgreSQL 唯一后端）。

五张表：
- user_credits / credit_transactions / system_config / user_llm_config / activation_codes

约定：
- 时间列统一 TEXT（UTC 'YYYY-MM-DD HH:MM:SS'）；
- 金额列 NUMERIC(12,1)，写入前一律 round(1)。
"""
from __future__ import annotations

import datetime as dt


def _now() -> str:
    return dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


# 每张表的 PG DDL
_TABLES_PG = [
    """
    CREATE TABLE IF NOT EXISTS user_credits (
        user_id TEXT PRIMARY KEY,
        balance NUMERIC(12,1) NOT NULL DEFAULT 0,
        total_recharged NUMERIC(12,1) NOT NULL DEFAULT 0,
        total_granted NUMERIC(12,1) NOT NULL DEFAULT 0,
        total_used NUMERIC(12,1) NOT NULL DEFAULT 0,
        last_bonus_date TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS credit_transactions (
        id BIGSERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        type TEXT NOT NULL,
        scene TEXT NOT NULL DEFAULT '',
        prompt_tokens BIGINT NOT NULL DEFAULT 0,
        completion_tokens BIGINT NOT NULL DEFAULT 0,
        total_tokens BIGINT NOT NULL DEFAULT 0,
        credits_delta NUMERIC(12,1) NOT NULL DEFAULT 0,
        credits_after NUMERIC(12,1) NOT NULL DEFAULT 0,
        use_own_key INTEGER NOT NULL DEFAULT 0,
        note TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS system_config (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL DEFAULT '',
        description TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_llm_config (
        user_id TEXT PRIMARY KEY,
        provider TEXT NOT NULL DEFAULT 'DeepSeek',
        api_key TEXT NOT NULL DEFAULT '',
        model TEXT NOT NULL DEFAULT '',
        api_url TEXT NOT NULL DEFAULT '',
        enabled INTEGER NOT NULL DEFAULT 1,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS activation_codes (
        id BIGSERIAL PRIMARY KEY,
        code TEXT NOT NULL UNIQUE,
        credits NUMERIC(12,1) NOT NULL,
        batch_id TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'active',
        created_by TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        used_by TEXT NOT NULL DEFAULT '',
        used_at TEXT NOT NULL DEFAULT ''
    )
    """,
]

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_ct_user_time ON credit_transactions (user_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_ac_status ON activation_codes (status)",
]

# 系统配置默认值（种子：仅当键不存在时写入，不覆盖管理员已改值）
DEFAULT_SYSTEM_CONFIG = [
    ("credits_daily_bonus", "100", "每日登录赠送积分"),
    ("credits_token_ratio", "4000", "Token→积分换算比例（多少个 Token = 1 积分）"),
    ("credits_asr_per_minute", "1", "录音转文字每分钟扣分"),
    ("credits_per_yuan", "100", "充值换算：多少积分 = 1 元"),
    ("credits_recharge_text", "请前往官方淘宝/微店店铺购买积分卡密，收到码后在下方兑换。", "充值弹窗引导文案"),
    ("credits_recharge_url", "", "购买店铺链接（展示用）"),
]

# 系统大模型键（沿用 load_config() 键名，system_config 表存在即覆盖 .env/runtime 文件）
LLM_CONFIG_KEYS = {
    "llm_provider": "系统大模型提供商",
    "deepseek_api_key": "系统 DeepSeek API Key",
    "deepseek_model": "系统 DeepSeek 模型",
    "deepseek_api_url": "系统 DeepSeek API URL",
    "gemini_api_key": "系统 Gemini API Key",
    "gemini_model": "系统 Gemini 模型",
    "qwen_api_key": "系统通义千问 API Key",
    "qwen_model": "系统通义千问模型",
    "qwen_api_url": "系统通义千问 API URL",
    "ollama_api_url": "系统 Ollama URL",
    "ollama_model": "系统 Ollama 模型",
}


def init_credits_tables(conn_factory, migrate_runtime_llm: bool = True) -> None:
    """建表 + 种子默认配置 + 一次性迁移 runtime_config.json 中的大模型密钥到表内。"""
    with conn_factory() as conn:
        for ddl in _TABLES_PG:
            conn.execute(ddl)
        for ddl in _INDEXES:
            conn.execute(ddl)
        now = _now()
        for key, val, desc in DEFAULT_SYSTEM_CONFIG:
            conn.execute(
                "INSERT INTO system_config (key, value, description, updated_at) VALUES (?, ?, ?, ?) ON CONFLICT (key) DO NOTHING",
                (key, val, desc, now),
            )
        if migrate_runtime_llm:
            _migrate_runtime_llm(conn)
        for key, desc in LLM_CONFIG_KEYS.items():
            conn.execute(
                "INSERT INTO system_config (key, value, description, updated_at) VALUES (?, ?, ?, ?) ON CONFLICT (key) DO NOTHING",
                (key, "", desc, now),
            )


def _migrate_runtime_llm(conn) -> None:
    try:
        import json
        import config as _cfg

        rf = _cfg.RUNTIME_CONFIG_FILE
        if not rf.exists():
            return
        data = json.loads(rf.read_text(encoding="utf-8"))
        now = _now()
        for key in LLM_CONFIG_KEYS:
            v = data.get(key)
            if not v:
                continue
            row = conn.execute("SELECT value FROM system_config WHERE key = ?", (key,)).fetchone()
            if row is None or (row[0] or "") == "":
                conn.execute(
                    "INSERT INTO system_config (key, value, description, updated_at) VALUES (?, ?, ?, ?) ON CONFLICT (key) DO NOTHING",
                    (key, str(v), "迁移自 runtime_config.json", now),
                )
    except Exception:  # noqa: BLE001 迁移失败不阻断启动（.env 兜底仍可用）
        pass
