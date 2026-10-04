# -*- coding: utf-8 -*-
"""u11 全链路健康冒烟：登录取 token -> 主入口/全部 SPA 片段/核心 API 逐一 200+success 断言。"""
import json
import urllib.request

BASE = "http://127.0.0.1:6001"
OUT = r"e:\LLM\LectureLearnLoop\server\logs\u11_smoke.txt"
FRAGMENTS = [
    "dashboard", "online_course_notes", "knowledge_base", "settings",
    "practice_overview", "practice_materials", "practice_knowledge", "practice_errors",
    "memory_overview", "memory_knowledge", "memory_errors", "knowledge_point",
]
lines = []


def req(path, token=None, method="GET", body=None):
    r = urllib.request.Request(BASE + path, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(r, data, timeout=15) as resp:
        return resp.status, resp.read().decode("utf-8", "replace")


# 1) 取 token（与 E2E 同源：logs/ui_walk_token.txt）
tok = ""
try:
    tok = open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", encoding="utf-8").read().strip()
    st, txt = req("/api/auth/me", tok)
    j = json.loads(txt)
    lines.append("TOKEN_ME -> %s success=%s" % (st, j.get("success")))
except Exception as e:
    lines.append("TOKEN_ME -> FAIL %r" % e)

# 2) SPA 主入口
try:
    st, txt = req("/", tok)
    lines.append("APP_SHELL -> %s ok=%s" % (st, "<html" in txt.lower()))
except Exception as e:
    lines.append("APP_SHELL -> FAIL %r" % e)

# 3) 全部片段端点
bad = []
for fid in FRAGMENTS:
    try:
        st, txt = req("/fragments/" + fid, tok)
        ok = st == 200 and len(txt) > 50
    except Exception as e:
        st, ok, txt = "ERR:" + repr(e), False, ""
    lines.append("FRAG %-22s -> %s ok=%s" % (fid, st, ok))
    if not ok:
        bad.append(fid)

# 4) 核心数据 API
for path in ["/api/subjects", "/api/dashboard/stats",
             "/api/practice/overview", "/api/memory/overview"]:
    try:
        st, txt = req(path, tok)
        j = json.loads(txt)
        lines.append("API %-36s -> %s success=%s" % (path, st, j.get("success")))
    except Exception as e:
        lines.append("API %-36s -> FAIL %r" % (path, e))

lines.append("BAD_FRAGMENTS -> " + (str(bad) if bad else "NONE"))
open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("done")
