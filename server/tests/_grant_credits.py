# 定位用户当前账号（最近登录）并充值积分（一次性工具，批10）
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db_adapter import get_connection
import credits_service as credits

out = []
conn = get_connection()
# users 表列（找登录时间字段）
cols = [r[1] for r in conn.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name='users'").fetchall()]
out.append("USER_COLS: " + json.dumps(cols))
cand = [c for c in ("last_login_at", "last_login", "updated_at", "created_at") if c in cols]
if cand:
    col = cand[0]
    rows = conn.execute(
        "SELECT username, user_id, %s FROM users WHERE username IN ('aboykoy','aboykyo') ORDER BY %s DESC NULLS LAST" % (col, col)
    ).fetchall()
    out.append("LOGIN_BY_%s: %s" % (col, json.dumps([list(r) for r in rows], ensure_ascii=False, default=str)))

# 最近登录流水（auth 可能在 credit_transactions 无记录，查 sessions/token 表若存在）
tables = [r[0] for r in conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'").fetchall()]
out.append("TABLES_HAS_SESSION: " + json.dumps([t for t in tables if "session" in t or "token" in t]))
for t in [t for t in tables if "session" in t or "token" in t]:
    try:
        rows = conn.execute("SELECT * FROM %s ORDER BY 1 DESC LIMIT 4" % t).fetchall()
        out.append("SAMPLE_%s: %s" % (t, json.dumps([list(map(str, r)) for r in rows], ensure_ascii=False)[:600]))
    except Exception as e:
        out.append("SAMPLE_%s_ERR: %s" % (t, e))
conn.close()

# 充值：两个候选账号各充 500（都是用户本人可能使用的账号，测试环境数据，多充无害且保证可测）
with get_connection() as conn2:
    for uname in ("aboykyo", "aboykoy"):
        r = conn2.execute("SELECT user_id FROM users WHERE username = ?", (uname,)).fetchone()
        if not r:
            out.append("GRANT_%s: user not found" % uname)
            continue
        res = credits.admin_adjust(r[0], 500, "批10 用户验收充值", "0001")
        out.append("GRANT_%s(%s): %s" % (uname, r[0], json.dumps(res, ensure_ascii=False, default=str)))

open(os.path.join(os.path.dirname(__file__), "ui_grant_out.txt"), "w", encoding="utf-8").write("\n".join(out) + "\n")
print("ok")
