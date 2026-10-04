# -*- coding: utf-8 -*-
"""文件导入任务表（2026-09-30 导入功能；双方言模式参照 schema_credits.py）。

约定：
- 时间列统一 TEXT（UTC 'YYYY-MM-DD HH:MM:SS'），与全库既有风格一致；
- id 用自增整型主键（适配层 db_adapter 对含 id 列的 INSERT 会盲注 RETURNING id 并 int() 回填，
  TEXT 主键会炸——见掉坑笔记），对外暴露的 task_id 为独立 hex 业务键（UNIQUE）。
"""
from __future__ import annotations


_IMPORT_TASKS_SQLITE = """
CREATE TABLE IF NOT EXISTS import_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL UNIQUE,
    user_id TEXT NOT NULL,
    file_name TEXT NOT NULL,
    folder_path TEXT NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    progress_json TEXT NOT NULL DEFAULT '',
    result_md TEXT NOT NULL DEFAULT '',
    result_pdf TEXT NOT NULL DEFAULT '',
    remote_job_id TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    parent_task_id TEXT NOT NULL DEFAULT '',
    seg_from INTEGER,
    seg_to INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

_IMPORT_TASKS_PG = """
CREATE TABLE IF NOT EXISTS import_tasks (
    id BIGSERIAL PRIMARY KEY,
    task_id TEXT NOT NULL UNIQUE,
    user_id TEXT NOT NULL,
    file_name TEXT NOT NULL,
    folder_path TEXT NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    progress_json TEXT NOT NULL DEFAULT '',
    result_md TEXT NOT NULL DEFAULT '',
    result_pdf TEXT NOT NULL DEFAULT '',
    remote_job_id TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    parent_task_id TEXT NOT NULL DEFAULT '',
    seg_from INTEGER,
    seg_to INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_import_tasks_user_time ON import_tasks (user_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_import_tasks_parent ON import_tasks (parent_task_id)",
]

# 新列（2026-10-04 大PDF分段）——旧库 CREATE TABLE IF NOT EXISTS 不会补列，需幂等 ALTER。
# sqlite 不支持 ADD COLUMN IF NOT EXISTS，PG 支持；统一用裸 ALTER + try/except 兼容双方言
# （列已存在时 sqlite 报 duplicate column、PG 报 DuplicateColumnError，均吞掉）。
_NEW_COLUMNS = [
    ("parent_task_id", "TEXT NOT NULL DEFAULT ''"),
    ("seg_from", "INTEGER"),
    ("seg_to", "INTEGER"),
]


def _ensure_columns(conn_factory) -> None:
    for col, decl in _NEW_COLUMNS:
        try:
            with conn_factory() as conn:
                conn.execute(f"ALTER TABLE import_tasks ADD COLUMN {col} {decl}")
        except Exception as e:  # noqa: BLE001 列已存在属正常幂等，不阻断启动
            msg = str(e).lower()
            if "duplicate" not in msg and "already exists" not in msg:
                raise


def init_import_tables(conn_factory) -> None:
    """建表 + 新列迁移 + 索引（幂等，CREATE TABLE IF NOT EXISTS）。"""
    from database.db_adapter import is_postgres
    pg = is_postgres()
    with conn_factory() as conn:
        conn.execute(_IMPORT_TASKS_PG if pg else _IMPORT_TASKS_SQLITE)
    _ensure_columns(conn_factory)
    with conn_factory() as conn:
        for ddl in _INDEXES:
            conn.execute(ddl)
