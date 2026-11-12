# -*- coding: utf-8 -*-
"""题包提示与我不会 E2E 断言 seed（仅测试用户数据，用后即删，零 LLM）。

argv: username out_json
建 goal→module→lesson（status='new' 进前测步），直接向 course_tests 灌 pretest 题包：
3 题，q0/q1 带 hint（含哨兵 HINTSENTINEL0/1），q2 无 hint 键（旧题包静默降级断言）。
输出 {uid,gid,mid,lid} 供 node 断言与清理。"""
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

PACK = [
    {"stem": "提示轮题干0 $x^2$", "options": ["甲0", "乙0", "丙0", "丁0"], "answer_index": 0,
     "kp_name": "提示轮点0", "explanation": "解析0",
     "hint": "HINTSENTINEL0 术语解释：梯度是变化率方向，从核心概念方向思考。"},
    {"stem": "提示轮题干1", "options": ["甲1", "乙1", "丙1", "丁1"], "answer_index": 1,
     "kp_name": "提示轮点1", "explanation": "解析1",
     "hint": "HINTSENTINEL1 学习率决定迭代步长。"},
    {"stem": "提示轮题干2", "options": ["甲2", "乙2", "丙2", "丁2"], "answer_index": 2,
     "kp_name": "提示轮点2", "explanation": "解析2"},  # 旧契约形态：无 hint 键
]

gid = conn.execute(
    "INSERT INTO learning_goals (user_id, subject_name, goal_text, status) "
    "VALUES (?,?,?,'ready')",
    (uid, "提示断言学科", "题包提示与我不会断言专用目标")).lastrowid
mid = conn.execute(
    "INSERT INTO course_modules (goal_id, ord, title, description) "
    "VALUES (?,1,'断言模块H','断言用')", (gid,)).lastrowid
lid = conn.execute(
    "INSERT INTO course_lessons (module_id, ord, title, description, status) "
    "VALUES (?,1,'提示轮课文','概要H','new')", (mid,)).lastrowid
conn.execute(
    "INSERT INTO course_tests (kind, lesson_id, questions_json) VALUES ('pretest', ?, ?)",
    (lid, json.dumps(PACK, ensure_ascii=False)))
conn.commit()

res = {"uid": uid, "gid": gid, "mid": mid, "lid": lid}
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(res, f, ensure_ascii=False)
print("SEEDED", res)
