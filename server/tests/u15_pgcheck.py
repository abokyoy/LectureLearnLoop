# -*- coding: utf-8 -*-
"""检查本机 PostgreSQL 正式库是否已含集成线 FSRS 表/列（当时 DDL 直接在正式库执行过）。"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from database import db_adapter
import config

conn = db_adapter.get_connection(str(config.DB_PATH))
out = []
try:
    cols = {r[0] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='knowledge_points'").fetchall()}
    need = ["difficulty_score", "importance_score", "fsrs_stability", "fsrs_difficulty",
            "fsrs_state", "fsrs_reps", "fsrs_lapses", "last_review_time", "due_time", "mastery_manual"]
    out.append("kp columns present: " + ",".join(c for c in need if c in cols))
    out.append("kp columns MISSING : " + (",".join(c for c in need if c not in cols) or "NONE"))
    cols2 = {r[0] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='error_questions'").fetchall()}
    need2 = need + ["question_content", "question_hash"]
    out.append("eq columns present: " + ",".join(c for c in need2 if c in cols2))
    out.append("eq columns MISSING : " + (",".join(c for c in need2 if c not in cols2) or "NONE"))
    pr_cols = {r[0] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='practice_records'").fetchall()}
    out.append("practice_records qhash: " + ("YES" if "question_hash" in pr_cols else "NO")
               + " | question_type/options_json: " + ",".join(
                   c for c in ("question_type", "options_json") if c in pr_cols))
    tabs = {r[0] for r in conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public'").fetchall()}
    for t in ("kp_proficiency_history", "memory_cards", "error_proficiency_history", "system_config"):
        out.append(f"table {t}: " + ("EXISTS" if t in tabs else "MISSING"))
    # 存量数据规模
    for t in ("kp_proficiency_history", "memory_cards"):
        if t in tabs:
            n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            out.append(f"rows {t}: {n}")
    n2 = conn.execute("SELECT COUNT(*) FROM knowledge_points WHERE fsrs_state IS NOT NULL AND fsrs_state <> 0").fetchone()[0]
    out.append(f"kp rows with fsrs_state!=0: {n2}")
finally:
    conn.close()
pathlib.Path(__file__).resolve().parents[1].joinpath("logs", "u15_pgcheck.txt").write_text("\n".join(out), encoding="utf-8")
print("\n".join(out))
