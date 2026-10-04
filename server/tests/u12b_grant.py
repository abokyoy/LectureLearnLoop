# 给用户当前实际登录账号 p6cdp_c4d6ec(cffa4eccc4a5) 充值
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import credits_service as credits

UID = "cffa4eccc4a5"
before = credits.get_balance(UID)
res = credits.admin_adjust(UID, 2000, "用户实测验收充值（当前登录账号）", "agent_u12b")
after = credits.get_balance(UID)
out = ["BEFORE: %s" % json.dumps(before, ensure_ascii=False, default=str),
       "ADJUST: %s" % json.dumps(res, ensure_ascii=False, default=str),
       "AFTER: %s" % json.dumps(after, ensure_ascii=False, default=str)]
open(os.path.join(os.path.dirname(__file__), "..", "logs", "u12b_grant.txt"), "w", encoding="utf-8").write("\n".join(out) + "\n")
print("done")
