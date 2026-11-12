# -*- coding: utf-8 -*-
"""课文图文结合 E2E 断言清理：删测试用户课程链、principle_cache 产物与账号本身。
argv: uid。仅对测试用户执行，禁止对正式账号使用。"""
import sys

sys.path.insert(0, r"e:\LLM\LectureLearnLoop\server")
from database.db_adapter import get_connection  # noqa: E402

uid = sys.argv[1]
conn = get_connection()
gids = [r[0] for r in conn.execute(
    "SELECT id FROM learning_goals WHERE user_id = ?", (uid,)).fetchall()]
if gids:
    ph = ",".join(["?"] * len(gids))
    conn.execute("DELETE FROM course_lessons WHERE module_id IN "
                 f"(SELECT id FROM course_modules WHERE goal_id IN ({ph}))", gids)
    conn.execute(f"DELETE FROM course_modules WHERE goal_id IN ({ph})", gids)

# principle_cache 归档轨（micro_courses 带 user_id；micro_scenes 按 course_id 连带删）
conn.execute("DELETE FROM micro_scenes WHERE course_id IN "
             "(SELECT id FROM micro_courses WHERE user_id = ?)", (uid,))
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
