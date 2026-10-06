# -*- coding: utf-8 -*-
"""文件导入任务表（PostgreSQL 唯一后端）。

约定：
- 时间列统一 TEXT（UTC 'YYYY-MM-DD HH:MM:SS'）；
- id 用 BIGSERIAL 主键，对外暴露的 task_id 为独立 hex 业务键（UNIQUE）。
"""
from __future__ import annotations


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

# 幂等补列（旧库可能缺少这些列）
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
        except Exception as e:  # noqa: BLE001 列已存在属正常幂等
            msg = str(e).lower()
            if "duplicate" not in msg and "already exists" not in msg and "已经存在" not in str(e):
                raise


def init_import_tables(conn_factory) -> None:
    """建表 + 新列迁移 + 索引（幂等）。"""
    with conn_factory() as conn:
        conn.execute(_IMPORT_TASKS_PG)
    _ensure_columns(conn_factory)
    with conn_factory() as conn:
        for ddl in _INDEXES:
            conn.execute(ddl)
