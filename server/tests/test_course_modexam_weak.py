# -*- coding: utf-8 -*-
"""模块考薄弱点收集断言（2026-11-12 用户裁定：模块考结果驱动后续课文生成）。

覆盖：同题包只取最近一次 attempt、跨题包合并去重、非 moduleexam/跨目标行忽略、
明细损坏降级跳过、_merged_weak 前测在前去重。
运行方式（server/ 目录）：python -m pytest tests/test_course_modexam_weak.py -v
"""
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import routes_courses as rc  # noqa: E402


def _conn():
    from database import db_adapter
    import config
    return db_adapter.get_connection(str(config.DB_PATH))


def _mk_attempt(conn, uid, gid, tid, kps, kind="moduleexam", raw_detail=None):
    """kps: [(kp_name, is_correct)] → 落一行 attempt；raw_detail 可直塞损坏明细。"""
    if raw_detail is None:
        raw_detail = json.dumps({"per_question": [
            {"stem": "题", "kp_name": k, "is_correct": ok} for k, ok in kps]},
            ensure_ascii=False)
    cur = conn.execute(
        "INSERT INTO course_attempts (user_id, goal_id, test_id, kind, lesson_title, "
        "score, detail_json) VALUES (?,?,?,?,?,?,?)",
        (uid, gid, tid, kind, "模块", 0.5, raw_detail))
    return cur.lastrowid


def test_modexam_weak_limit_truncation():
    """评审M-3：超过 limit 时只保留最近一次作答优先的前 limit 个（上限截断语义）。"""
    uid = "cgt" + uuid.uuid4().hex[:8]
    conn = _conn()
    try:
        gid = conn.execute("INSERT INTO learning_goals (user_id, subject_name, goal_text, "
                           "status) VALUES (?,?,'t','ready')", (uid, "科")).lastrowid
        mid = conn.execute("INSERT INTO course_modules (goal_id, ord, title) VALUES (?,1,'m')",
                           (gid,)).lastrowid
        # 12 个题包各一道错题，kp 名随 id 递增（越新越前）
        for i in range(12):
            tid = conn.execute("INSERT INTO course_tests (kind, lesson_id, module_id, "
                               "questions_json) VALUES ('moduleexam',NULL,?,'[]')",
                               (mid,)).lastrowid
            _mk_attempt(conn, uid, gid, tid, [(f"错点{i:02d}", False)])
        conn.commit()
        got = rc._modexam_weak_points(conn, gid, uid)
        assert len(got) == 10, got
        assert got == [f"错点{i:02d}" for i in range(11, 1, -1)], got  # 最近优先取前10
    finally:
        conn.execute("DELETE FROM course_attempts WHERE user_id=?", (uid,))
        conn.execute("DELETE FROM course_tests WHERE module_id IN "
                     "(SELECT id FROM course_modules WHERE goal_id=?)", (gid,))
        conn.execute("DELETE FROM course_modules WHERE goal_id=?", (gid,))
        conn.execute("DELETE FROM learning_goals WHERE id=?", (gid,))
        conn.commit()
        conn.close()


def test_modexam_weak_points():
    uid = "cgw" + uuid.uuid4().hex[:8]
    conn = _conn()
    gids = []
    try:
        gid = conn.execute("INSERT INTO learning_goals (user_id, subject_name, goal_text, "
                           "status) VALUES (?,?,'t','ready')", (uid, "科")).lastrowid
        gids.append(gid)
        mid = conn.execute("INSERT INTO course_modules (goal_id, ord, title) VALUES (?,1,'m')",
                           (gid,)).lastrowid
        tids = [conn.execute("INSERT INTO course_tests (kind, lesson_id, module_id, "
                             "questions_json) VALUES ('moduleexam',NULL,?,'[]')",
                             (mid,)).lastrowid for _ in range(3)]
        # 题包1：旧 attempt 错「旧错点」，新 attempt 旧点已答对、新点答错 → 只应取「新错点」
        _mk_attempt(conn, uid, gid, tids[0], [("旧错点", False)])
        _mk_attempt(conn, uid, gid, tids[0], [("旧错点", True), ("新错点", False)])
        # 题包2：错「甲错点」+ 空 kp 行被忽略
        _mk_attempt(conn, uid, gid, tids[1], [("甲错点", False), ("", False)])
        # 题包3：明细损坏 → 跳过不炸
        _mk_attempt(conn, uid, gid, tids[2], [], raw_detail="{坏json")
        # 干扰行：pretest 与别的目标，均不得混入
        _mk_attempt(conn, uid, gid, tids[0], [("前测错点", False)], kind="pretest")
        gid_other = conn.execute("INSERT INTO learning_goals (user_id, subject_name, goal_text, "
                                 "status) VALUES (?,?,'t','ready')", (uid, "科")).lastrowid
        gids.append(gid_other)
        _mk_attempt(conn, uid, gid_other, tids[0], [("他目标错点", False)])
        conn.commit()

        got = rc._modexam_weak_points(conn, gid, uid)
        assert set(got) == {"新错点", "甲错点"}, got
        assert "旧错点" not in got and "前测错点" not in got and "他目标错点" not in got

        # 前测在前：重复项（新错点）只保留一次且位置随前测序列（评审M-3：防去重假阴性）
        merged = rc._merged_weak(conn, gid, uid, ["新错点", "前测错点", "  "])
        assert merged[0] == "新错点" and merged[1] == "前测错点", merged
        assert len(merged) == 3, merged  # 去重硬断言：新错点不得重复计入
        assert set(merged) == {"新错点", "前测错点", "甲错点"}, merged
    finally:
        conn.execute("DELETE FROM course_attempts WHERE user_id=?", (uid,))
        conn.execute("DELETE FROM course_tests WHERE module_id IN "
                     "(SELECT id FROM course_modules WHERE goal_id IN (?,?))", gids)
        for g in gids:
            conn.execute("DELETE FROM course_modules WHERE goal_id=?", (g,))
            conn.execute("DELETE FROM learning_goals WHERE id=?", (g,))
        conn.commit()
        conn.close()
