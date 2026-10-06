# -*- coding: utf-8 -*-
"""文件导入任务表（2026-09-30 导入功能；PostgreSQL 唯一后端）。

约定：
- 时间列统一 TEXT（UTC 'YYYY-MM-DD HH:MM:SS'），与全库既有风格一致；
- id 用自增整型主键（适配层 db_adapter 对含 id 列的 INSERT 会盲注 RETURNING id 并 int() 回填，
  TEXT 主键会炸——见掉坑笔记），对外暴露的 task_id 为独立 hex 业务键（UNIQUE）。
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
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_import_tasks_user_time ON import_tasks (user_id, created_at DESC)",
]


def init_import_tables(conn_factory) -> None:
    """建表 + 索引（幂等，CREATE TABLE IF NOT EXISTS）。"""
    with conn_factory() as conn:
        conn.execute(_IMPORT_TASKS_PG)
        for ddl in _INDEXES:
            conn.execute(ddl)
