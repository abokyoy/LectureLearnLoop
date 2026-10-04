# 列出全部"非测试前缀"账号 + 余额，定位界面上余额 0 的账号
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db_adapter import get_connection

TESTPFX = ("p2t_", "p4user_", "p5_", "u8ov_", "pn_", "crdt", "cadmin", "pen_tester", "u_", "b8", "b9", "b10")
out = []
with get_connection() as conn:
    rows = conn.execute(
        "SELECT u.user_id, u.username, u.display_name, u.is_admin, u.created_at, "
        "COALESCE(c.balance, -999) FROM users u LEFT JOIN user_credits c ON c.user_id = u.user_id "
        "ORDER BY u.created_at"
    ).fetchall()
    out.append("TOTAL_USERS: %d" % len(rows))
    for r in rows:
        un = str(r[1] or "")
        if un.startswith(TESTPFX):
            continue
        out.append(json.dumps(list(map(str, r)), ensure_ascii=False))
open(os.path.join(os.path.dirname(__file__), "..", "logs", "u12_users.txt"), "w", encoding="utf-8").write(
    "\n".join(out) + "\n")
print("done")
