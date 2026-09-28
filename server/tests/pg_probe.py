# -*- coding: utf-8 -*-
"""PG 服务器连通性探测（凭据统一从 server/.env 经 config 读取，禁止硬编码密钥）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
import psycopg2  # noqa: E402

c = psycopg2.connect(host=config.PG_HOST, port=config.PG_PORT, user=config.PG_USER,
                     password=config.PG_PASSWORD, dbname="postgres", connect_timeout=8)
cur = c.cursor()
cur.execute("SELECT version()")
print("SERVER:", cur.fetchone()[0][:70])
cur.execute("SELECT datname FROM pg_database")
print("DATABASES:", [r[0] for r in cur.fetchall()])
cur.execute("SHOW max_connections")
print("max_connections:", cur.fetchone()[0])
print("TARGET_DB:", config.PG_DATABASE, "| BACKEND:", config.DB_BACKEND)
c.close()
print("PG_CONNECT_OK")
