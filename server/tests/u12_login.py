# 查 19:35 后的登录记录，确定用户实际登录账号（排除测试账号前缀）
import sys, os, json, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

P = r"e:\LLM\LectureLearnLoop\server\logs\debug_trace.jsonl"
TESTPFX = ("p2t_", "p4user_", "p5_", "u8ov_", "pn_", "crdt", "cadmin", "pen_tester", "u_", "test")
out = []
with open(P, encoding="utf-8", errors="replace") as f:
    for ln in f:
        try:
            j = json.loads(ln)
        except Exception:
            continue
        ts = j.get("timestamp", "")
        if ts < "2026-10-02T19:32":
            continue
        m, a, d = j.get("module"), j.get("action"), j.get("data") or {}
        if m == "auth" and a in ("login", "login_failed", "register_done"):
            u = str(d.get("username", ""))
            if not u.startswith(TESTPFX):
                out.append("%s %s %s %s" % (ts[11:19], a, u, json.dumps(d, ensure_ascii=False)[:160]))
        elif m == "credits" and a == "daily_bonus":
            out.append("%s daily_bonus %s" % (ts[11:19], d))
open(os.path.join(os.path.dirname(__file__), "..", "logs", "u12_login.txt"), "w", encoding="utf-8").write(
    "\n".join(out[-40:]) + "\n")
print("done", len(out))
