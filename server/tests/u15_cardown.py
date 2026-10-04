# -*- coding: utf-8 -*-
"""查 memory_cards 表数据归属（哪些用户、卡片数、科目分布）。"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from database import db_adapter
import config

conn = db_adapter.get_connection(str(config.DB_PATH))
out = []
try:
    ucols = {r[0] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='users'").fetchall()}
    out.append("users cols: " + ",".join(sorted(ucols)))
    uid = "user_id" if "user_id" in ucols else ("username" if "username" in ucols else "id")
    rows = conn.execute(
        f"SELECT mc.user_id, MAX(u.{uid}), mc.card_type, COUNT(*), "
        "STRING_AGG(DISTINCT mc.subject_name, ' | ') "
        f"FROM memory_cards mc LEFT JOIN users u ON CAST(u.{uid} AS TEXT) = mc.user_id "
        "GROUP BY mc.user_id, mc.card_type").fetchall()
    for r in rows:
        out.append(f"user={r[0]} name={r[1]} type={r[2]} count={r[3]} subjects={r[4]}")
    hist = conn.execute(
        "SELECT user_id, COUNT(DISTINCT knowledge_point_id) FROM kp_proficiency_history GROUP BY user_id").fetchall()
    out.append("kp_hist: " + "; ".join(f"{h[0]}->{h[1]}kp" for h in hist))
    fsrs = conn.execute(
        "SELECT user_id, COUNT(*) FROM knowledge_points WHERE COALESCE(fsrs_state,0)<>0 GROUP BY user_id").fetchall()
    out.append("kp_fsrs_active: " + "; ".join(f"{f[0]}->{f[1]}" for f in fsrs))
    e_fsrs = conn.execute(
        "SELECT user_id, COUNT(*) FROM error_questions WHERE COALESCE(fsrs_state,0)<>0 GROUP BY user_id").fetchall()
    out.append("eq_fsrs_active: " + "; ".join(f"{f[0]}->{f[1]}" for f in e_fsrs))
finally:
    conn.close()
pathlib.Path(__file__).resolve().parents[1].joinpath("logs", "u15_cardown.txt").write_text("\n".join(out), encoding="utf-8")
print("\n".join(out))
