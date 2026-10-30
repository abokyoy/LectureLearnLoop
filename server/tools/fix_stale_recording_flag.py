# 一次性数据修复：清理 notes.recording 残留标识（v0.1.4 交付前）
# 背景：done() 清标识曾被窗口销毁掐死 → recording 永久为 1 → 脑图 409 误拦
# CodeReview 收紧：只清 30 分钟以上无更新的残留行，避免误伤正在录音的会话
import os
import psycopg2

env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
with open(env_path, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

conn = psycopg2.connect(
    host=os.environ.get("PG_HOST", "127.0.0.1"),
    port=int(os.environ.get("PG_PORT", "5432")),
    dbname=os.environ.get("PG_DATABASE", "lecturelearnloop"),
    user=os.environ.get("PG_USER", "postgres"),
    password=os.environ.get("PG_PASSWORD", ""),
)
cur = conn.cursor()
cur.execute("SELECT user_id, file_name, recording, updated_time FROM notes WHERE recording = 1 "
            "AND updated_time < to_char(timezone('UTC', now()) - interval '30 minutes', 'YYYY-MM-DD HH24:MI:SS')")
rows = cur.fetchall()
print("BEFORE stale recording=1 rows:", rows)
cur.execute("UPDATE notes SET recording = 0 WHERE recording = 1 "
            "AND updated_time < to_char(timezone('UTC', now()) - interval '30 minutes', 'YYYY-MM-DD HH24:MI:SS')")
print("CLEARED:", cur.rowcount)
conn.commit()
cur.execute("SELECT count(*) FROM notes WHERE recording = 1 AND updated_time < to_char(timezone('UTC', now()) - interval '30 minutes', 'YYYY-MM-DD HH24:MI:SS')")
print("AFTER remaining stale:", cur.fetchone()[0])
conn.close()
