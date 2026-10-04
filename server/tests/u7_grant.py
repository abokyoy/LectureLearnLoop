# u7：给测试账号发放验证积分并查余额（走 credits_service.admin_adjust，与 u1 充值同路径）
import os
import sys

sys.path.insert(0, r"e:\LLM\LectureLearnLoop\server")
os.chdir(r"e:\LLM\LectureLearnLoop\server")

from dotenv import load_dotenv
load_dotenv(".env")

import credits_service as cs

UID = "940ee3cf7c33"
before = cs.get_balance(UID)
print("BEFORE:", before)
res = cs.admin_adjust(UID, 2000, "u7 练习链路验证用测试积分", "agent_u7")
print("ADJUST:", res)
print("AFTER:", cs.get_balance(UID))
