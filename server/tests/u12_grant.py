# 用户验收追加充值（与 u1/_grant_credits 同路径：credits_service.admin_adjust，留审计流水）
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db_adapter import get_connection
import credits_service as credits

out = []
with get_connection() as conn:
    for uname in ("aboykoy", "aboykyo"):
        r = conn.execute("SELECT user_id FROM users WHERE username = ?", (uname,)).fetchone()
        if not r:
            out.append("%s: NOT FOUND" % uname)
            continue
        uid = r[0]
        before = credits.get_balance(uid)
        res = credits.admin_adjust(uid, 1000, "用户实测验收充值（追加）", "agent_u12")
        after = credits.get_balance(uid)
        out.append("%s(%s): before=%s adjust=%s after=%s" % (
            uname, uid, json.dumps(before, ensure_ascii=False, default=str),
            json.dumps(res, ensure_ascii=False, default=str),
            json.dumps(after, ensure_ascii=False, default=str)))

open(os.path.join(os.path.dirname(__file__), "..", "logs", "u12_grant.txt"), "w", encoding="utf-8").write("\n".join(out) + "\n")
print("done")
