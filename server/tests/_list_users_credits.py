# 查全部用户余额与最近流水时间，定位用户测试账号（一次性工具脚本）
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from credits_service import list_users_credits
from database.db_adapter import get_connection

out = []
out.append("USERS: " + json.dumps(list_users_credits(), ensure_ascii=False, default=str))

# 每用户最近一次流水时间（判断谁是活跃真实用户）
conn = get_connection()
rows = conn.execute(
    "SELECT user_id, MAX(created_at) FROM credit_transactions GROUP BY user_id ORDER BY MAX(created_at) DESC"
).fetchall()
out.append("LAST_TX: " + json.dumps([list(r) for r in rows], ensure_ascii=False, default=str))
conn.close()

open(os.path.join(os.path.dirname(__file__), "ui_users_credits.txt"), "w", encoding="utf-8").write("\n".join(out) + "\n")
print("ok")
