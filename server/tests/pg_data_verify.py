# -*- coding: utf-8 -*-
"""直查 PG：确认业务数据真实落在 PostgreSQL（迁移+运行期写入证据）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
import psycopg2  # noqa: E402

c = psycopg2.connect(host=config.PG_HOST, port=config.PG_PORT, user=config.PG_USER,
                     password=config.PG_PASSWORD, dbname=config.PG_DATABASE)
cur = c.cursor()
for t in ("users", "user_subjects", "knowledge_points", "practice_records", "error_questions"):
    cur.execute(f"SELECT COUNT(*) FROM {t}")
    print(f"PG {t}: {cur.fetchone()[0]}")
cur.execute("SELECT COUNT(*) FROM users WHERE username LIKE 'pgload_%'")
print("PG users(pgload_ 并发压测账号):", cur.fetchone()[0])
cur.execute("SELECT COUNT(*) FROM knowledge_points WHERE point_name LIKE 'p_%'")
print("PG knowledge_points(并发写入):", cur.fetchone()[0])
cur.execute("SELECT COUNT(*) FROM pg_stat_activity WHERE application_name='lecturelearnloop-server'")
print("PG 服务端活动连接(池):", cur.fetchone()[0])
c.close()
print("PG_DATA_VERIFIED")
