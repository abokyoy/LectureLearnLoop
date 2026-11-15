# -*- coding: utf-8 -*-
"""目标导向学习（体系化课程）建表断言：五表存在 + 基本 CRUD 往返（? 占位经 db_adapter）。

运行方式（server/ 目录）：python -m pytest tests/test_course_schema.py -v
计划：docs/superpowers/plans/2026-11-11-goal-driven-learning.md Task 1
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TABLES = ["learning_goals", "course_modules", "course_lessons", "course_tests", "course_attempts"]


def _conn():
    from database import db_adapter
    import config
    return db_adapter.get_connection(str(config.DB_PATH))


def test_tables_exist():
    from app import create_app
    create_app()  # 启动建表（IF NOT EXISTS 幂等）
    c = _conn()
    try:
        for t in TABLES:
            assert c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] >= 0, t
    finally:
        c.close()


def test_roundtrip():
    c = _conn()
    tag = "cg" + uuid.uuid4().hex[:8]
    try:
        c.execute("INSERT INTO learning_goals (user_id, subject_name, goal_text) VALUES (?,?,?)",
                  (tag, tag + "_科", "测试目标"))
        gid = c.execute("SELECT id FROM learning_goals WHERE user_id=?", (tag,)).fetchone()[0]
        c.execute("INSERT INTO course_modules (goal_id, ord, title, description) VALUES (?,?,?,?)",
                  (gid, 1, "模块一", "d"))
        mid = c.execute("SELECT id FROM course_modules WHERE goal_id=?", (gid,)).fetchone()[0]
        c.execute("INSERT INTO course_lessons (module_id, ord, title, est_minutes) VALUES (?,?,?,?)",
                  (mid, 1, "课文一", 30))
        row = c.execute("SELECT status, regen_count, content_mode FROM course_lessons WHERE module_id=?",
                        (mid,)).fetchone()
        assert row[0] == "new" and row[1] == 0 and row[2] is None
        lid = c.execute("SELECT id FROM course_lessons WHERE module_id=?", (mid,)).fetchone()[0]
        c.execute("INSERT INTO course_tests (kind, lesson_id, questions_json) VALUES (?,?,?)",
                  ("pretest", lid, "[]"))
        c.execute("INSERT INTO course_attempts (user_id, goal_id, test_id, kind, score, detail_json) "
                  "VALUES (?,?,?,?,?,?)", (tag, gid, 0, "pretest", 0.5, "[]"))
        aid = c.execute("SELECT id FROM course_attempts WHERE user_id=?", (tag,)).fetchone()[0]
        assert aid > 0
    finally:
        c.execute("DELETE FROM course_attempts WHERE user_id=?", (tag,))
        c.execute("DELETE FROM course_tests WHERE lesson_id IN "
                  "(SELECT id FROM course_lessons WHERE module_id IN "
                  "(SELECT id FROM course_modules WHERE goal_id=?))", (gid,))
        c.execute("DELETE FROM course_lessons WHERE module_id IN "
                  "(SELECT id FROM course_modules WHERE goal_id=?)", (gid,))
        c.execute("DELETE FROM course_modules WHERE goal_id=?", (gid,))
        c.execute("DELETE FROM learning_goals WHERE id=?", (gid,))
        c.commit()
        c.close()
