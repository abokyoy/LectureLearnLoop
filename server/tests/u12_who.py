# 核实：最近登录的账号是谁 + 各用户当前余额 + 今日积分流水（定位用户实际测试账号）
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db_adapter import get_connection

out = []
with get_connection() as conn:
    cols = [r[0] for r in conn.execute("SELECT column_name FROM information_schema.columns WHERE table_name='users'").fetchall()]
    out.append("USER_COLS: " + json.dumps(cols))
    lc = [c for c in ("last_login_at", "last_login", "updated_at") if c in cols]
    col = lc[0] if lc else "created_at"
    rows = conn.execute(
        "SELECT user_id, username, is_admin, %s FROM users ORDER BY %s DESC NULLS LAST LIMIT 12" % (col, col)
    ).fetchall()
    out.append("USERS_BY_%s:" % col)
    for r in rows:
        out.append("  " + json.dumps(list(map(str, r)), ensure_ascii=False))

    ids = [r[0] for r in rows]
    if ids:
        q = ",".join("'%s'" % i for i in ids)
        bal = conn.execute("SELECT user_id, balance, total_used FROM user_credits WHERE user_id IN (%s)" % q).fetchall()
        out.append("BALANCES:")
        for r in bal:
            out.append("  " + json.dumps(list(map(str, r)), ensure_ascii=False))

    # 今日流水（created_at 为 TEXT UTC 'YYYY-MM-DD ...'，字符串前缀比较）
    today = "2026-10-02"
    tx = conn.execute(
        "SELECT user_id, type, credits_delta, credits_after, note, created_at "
        "FROM credit_transactions WHERE created_at >= ? ORDER BY created_at DESC LIMIT 20",
        (today,)
    ).fetchall()
    out.append("TODAY_TX:")
    for r in tx:
        out.append("  " + json.dumps(list(map(str, r)), ensure_ascii=False))

open(os.path.join(os.path.dirname(__file__), "..", "logs", "u12_who.txt"), "w", encoding="utf-8").write("\n".join(out) + "\n")
print("done")
