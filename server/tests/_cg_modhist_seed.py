# -*- coding: utf-8 -*-
"""模块考历史 E2E 断言 seed（仅测试用户数据，用后即删）。

argv: username out_json
建 goal(ready)+module+course_tests(题包复制自真实模块考 test 177，免 LLM 出题)，
输出期望判分（全部选 A 时）供 node 断言。"""
import json
import sys

sys.path.insert(0, r"e:\LLM\LectureLearnLoop\server")
from database.db_adapter import get_connection  # noqa: E402

username, out_path = sys.argv[1], sys.argv[2]
conn = get_connection()
urow = conn.execute("SELECT user_id FROM users WHERE username = ?", (username,)).fetchone()
if not urow:
    raise SystemExit("user not found: " + username)
uid = urow[0]
qrow = conn.execute(
    "SELECT questions_json FROM course_tests WHERE id = 177").fetchone()
if not qrow:
    raise SystemExit("参照题包 test 177 不存在")
pack = json.loads(qrow[0])

gid = conn.execute(
    "INSERT INTO learning_goals (user_id, subject_name, goal_text, status) "
    "VALUES (?,?,?,'ready')",
    (uid, "模块考断言学科", "模块考历史记录断言专用目标")).lastrowid
mid = conn.execute(
    "INSERT INTO course_modules (goal_id, ord, title, description) "
    "VALUES (?,1,?,'断言用模块')", (gid, "断言模块甲")).lastrowid
tid = conn.execute(
    "INSERT INTO course_tests (kind, lesson_id, module_id, questions_json) "
    "VALUES ('moduleexam', NULL, ?, ?)",
    (mid, json.dumps(pack, ensure_ascii=False))).lastrowid
conn.commit()

n = len(pack)
correct_if_all_a = sum(1 for q in pack if q["answer_index"] == 0)
res = {"uid": uid, "gid": gid, "mid": mid, "tid": tid, "n": n,
       "expect_wrong": n - correct_if_all_a,
       "expect_score_pct": round(100.0 * correct_if_all_a / n)}
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(res, f, ensure_ascii=False)
print("SEEDED", res)
