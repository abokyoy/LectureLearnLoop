# 一次性：验证 :6001 服务已加载评审修复（_safe_opts + SQLite 补列）指纹
import sys, json, urllib.request

sys.path.insert(0, r"e:\LLM\LectureLearnLoop\server")
out = []

# 1. HTTP 存活
try:
    code = urllib.request.urlopen("http://127.0.0.1:6001/login", timeout=5).status
    out.append(f"HTTP {code}")
except Exception as e:
    out.append(f"HTTP_FAIL {e}")

# 2. 源码含修复特征（确认磁盘版本）
src = open(r"e:\LLM\LectureLearnLoop\server\knowledge_management.py", encoding="utf-8").read()
out.append("SRC_safe_opts=" + str("_safe_opts" in src))
out.append("SRC_sqlite_alter=" + str("ALTER TABLE practice_records ADD COLUMN options_json TEXT" in src))

# 3. 实际进程指纹：对 PG 走 SQLite 分支不可行，改为检查进程启动时间晚于源码修改时间
import os, time
mt = os.path.getmtime(r"e:\LLM\LectureLearnLoop\server\knowledge_management.py")
out.append(f"SRC_MTIME={time.strftime('%H:%M:%S', time.localtime(mt))}")

# 4. 运行中进程启动时刻（WMI 需要权限，用 psutil 若可用；否则用 6001 PID 的 CreateTime）
try:
    import psutil
    for c in psutil.net_connections("inet"):
        if c.status == "LISTEN" and c.laddr and c.laddr.port == 6001:
            p = psutil.Process(c.pid)
            ct = time.localtime(p.create_time())
            out.append(f"LISTENER pid={c.pid} started={time.strftime('%H:%M:%S', ct)} after_src={p.create_time() > mt}")
except Exception as e:
    out.append(f"PSUTIL_FAIL {e}")

open(r"e:\LLM\LectureLearnLoop\server\logs\u14_codeproof.txt", "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out))
