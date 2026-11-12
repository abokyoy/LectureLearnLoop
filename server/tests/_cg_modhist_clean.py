# -*- coding: utf-8 -*-
"""模块考历史 E2E 断言清理：删除测试用户在所有带 user_id 列表中的数据，
以及按 goal 归属的无 user_id 表行。argv: uid
仅对测试用户执行，禁止对正式账号使用。"""
import sys

sys.path.insert(0, r"e:\LLM\LectureLearnLoop" + r"\server")
from database.db_adapter import get_connection  # noqa: E402

uid = sys.argv[1]
conn = get_connection()
gids = [r[0] for r in conn.execute(
    "SELECT id FROM learning_goals WHERE user_id = ?", (uid,)).fetchall()]

# 无 user_id 列、按 goal 归属的子表先删
if gids:
    ph = ",".join(["?"] * len(gids))
    conn.execute("DELETE FROM course_lessons WHERE module_id IN "
                 f"(SELECT id FROM course_modules WHERE goal_id IN ({ph}))", gids)
    conn.execute(f"DELETE FROM course_modules WHERE goal_id IN ({ph})", gids)

# 所有带 user_id 列的表统一删（course_tests 无 user_id 列，按本次 seed 的 id 删）
tid = sys.argv[2] if len(sys.argv) > 2 else None
if tid:
    conn.execute("DELETE FROM course_tests WHERE id = ?", [int(tid)])
tables = [r[0] for r in conn.execute(
    "SELECT table_name FROM information_schema.columns "
    "WHERE column_name = 'user_id' AND table_schema = 'public'").fetchall()]
for t in sorted(tables):
    if t == "users":
        continue
    try:
        conn.execute(f"DELETE FROM {t} WHERE user_id = ?", (uid,))
        conn.commit()  # 逐表提交：失败回滚不污染已删成功的表
    except Exception as e:  # noqa: BLE001 个别表 user_id 语义不同则跳过并打印
        conn.rollback()
        print("SKIP", t, str(e)[:80])
conn.execute("DELETE FROM users WHERE user_id = ?", (uid,))
conn.commit()
print("CLEANED uid=%s goals=%s" % (uid, gids))
