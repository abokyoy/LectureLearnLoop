# -*- coding: utf-8 -*-
"""练/记系统改造（2026-09-28）正式库变更脚本：幂等 DDL + question_hash 存量回填。

用途：
1. 执行 database/schema_postgres.py 的 PG_TABLES 全量清单（所有语句均为
   IF NOT EXISTS / ADD COLUMN IF NOT EXISTS，幂等可重跑）；
2. 回填 error_questions.question_content / question_hash 与 practice_records.question_hash
   （md5 题干），已回填过的行自动跳过。

用法（在 server 目录下）：
    python -m tools.apply_fsrs_schema            # 建列建表 + 回填
    python -m tools.apply_fsrs_schema --no-backfill

回滚预案（方案 §6）：不删列不删表，回滚=停用 fsrs_service 写回路径。
"""
import argparse
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from database import db_adapter, schema_postgres  # noqa: E402


def qhash(text):
    return hashlib.md5(str(text or "").encode("utf-8")).hexdigest()


def apply_ddl(conn):
    n = 0
    for stmt in schema_postgres.PG_TABLES:
        conn.execute(stmt)
        n += 1
    conn.commit()
    print(f"[ddl] 执行 {n} 条幂等语句完成")


def backfill(conn):
    # 1) practice_records.question_hash：按 md5(题干) 回填
    rows = conn.execute(
        "SELECT id, question_content FROM practice_records "
        "WHERE question_hash IS NULL AND question_content IS NOT NULL").fetchall()
    cur = conn.cursor()
    cur.executemany("UPDATE practice_records SET question_hash = ? WHERE id = ?",
                    [(qhash(r[1]), r[0]) for r in rows])
    cur.close()
    print(f"[backfill] practice_records.question_hash 回填 {len(rows)} 行")

    # 2) error_questions：题干从关联练习记录补齐，再算 hash
    rows = conn.execute(
        "SELECT e.id, e.practice_record_id FROM error_questions e "
        "WHERE e.question_hash IS NULL").fetchall()
    done = 0
    for eid, prid in rows:
        row = conn.execute("SELECT question_content FROM practice_records WHERE id = ?",
                           (prid,)).fetchone()
        if row and row[0]:
            conn.execute("UPDATE error_questions SET question_content = ?, question_hash = ? "
                         "WHERE id = ?", (row[0], qhash(row[0]), eid))
            done += 1
    conn.commit()
    print(f"[backfill] error_questions 题干/hash 回填 {done}/{len(rows)} 行"
          f"（无关联练习记录的错题跳过，后续可经补录入口处理）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-backfill", action="store_true")
    args = ap.parse_args()
    if not db_adapter.is_postgres():
        print("[warn] 当前后端非 postgres：PG 权威路径下才需要执行本脚本；"
              "SQLite 由 knowledge_management.init_database 自动补列")
        return 1
    conn = db_adapter.get_connection(str(config.DB_PATH))
    try:
        apply_ddl(conn)
        if not args.no_backfill:
            backfill(conn)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
