# -*- coding: utf-8 -*-
"""清理 u15_c3 冒烟残留测试数据（U15C3S 前缀学科 + 指定知识点）。"""
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database import db_adapter  # noqa: E402
import config  # noqa: E402

tk = open(r"logs\ui_walk_token.txt", encoding="utf-8").read().strip()
seg = tk.split(".")[1]
seg += "=" * (-len(seg) % 4)
uid = json.loads(base64.urlsafe_b64decode(seg))["uid"]

c = db_adapter.get_connection(str(config.DB_PATH))
cur = c.cursor()
cur.execute("SELECT id FROM knowledge_points WHERE user_id = ? AND subject_name LIKE ?", (uid, "U15C3S%"))
pids = [x[0] for x in cur.fetchall()]
for pid in pids:
    cur.execute("DELETE FROM kp_proficiency_history WHERE user_id = ? AND knowledge_point_id = ?", (uid, pid))
    cur.execute("DELETE FROM knowledge_point_sources WHERE knowledge_point_id = ?", (pid,))
    cur.execute("DELETE FROM knowledge_points WHERE id = ? AND user_id = ?", (pid, uid))
cur.execute("DELETE FROM user_subjects WHERE user_id = ? AND subject_name LIKE ?", (uid, "U15C3S%"))
c.commit()
c.close()
print("PURGED pids:", pids)
