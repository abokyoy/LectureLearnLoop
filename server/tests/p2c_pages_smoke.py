"""P2c 页面路由冒烟测试：整页可渲染 + fragments 鉴权与内容 + 登录页可用。

直接运行：python tests/p2c_pages_smoke.py（服务需在 6001 运行）。
"""
from __future__ import annotations

import sys
import time
import urllib.request
import urllib.error
import json
import uuid

sys.path.insert(0, ".")

BASE = "http://127.0.0.1:6001"
FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = ""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name} {detail[:160]}")
    if not cond:
        FAILS.append(name)


def get(path: str, token: str | None = None):
    req = urllib.request.Request(BASE + path)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def post_json(path: str, obj: dict):
    data = json.dumps(obj).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802
        return None


def main():
    # 1. 整页路由（未登录也应返回壳，数据接口 401 由前端跳登录）
    pages = {
        "/": "content-area",
        "/online_course": "content-area",
        "/knowledge_base": "content-area",
        "/settings": "content-area",
        "/llm_logs": "content-area",
        "/practice": "</html>",
        "/practice_simple": "</html>",
    }
    for path, marker in pages.items():
        st, body = get(path)
        check(f"page {path}", st == 200 and marker in body, f"status={st} len={len(body)}")

    # 1b. 四期D组：/learn_materials 已合并 → 302 重定向到 /online_course
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(urllib.request.Request(BASE + "/learn_materials"), timeout=10) as r:
            st, loc = r.status, ""
    except urllib.error.HTTPError as e:
        st, loc = e.code, e.headers.get("Location", "")
    check("page /learn_materials -> 302 /online_course",
          st == 302 and "/online_course" in loc, f"status={st} loc={loc}")

    # 2. 登录/注册页
    st, body = get("/login")
    check("page /login", st == 200 and "柯基学习小助手" in body, f"status={st}")
    st, body = get("/register")
    check("page /register", st == 200, f"status={st}")
    st, body = get("/logout")
    check("page /logout", st == 200 and "ll_token" in body, f"status={st}")

    # 3. fragments 未带 token -> 401
    st, _ = get("/fragments/settings")
    check("fragments 401 without token", st == 401, f"status={st}")

    # 4. 注册随机用户拿 token
    uname = "p2c_" + uuid.uuid4().hex[:6]
    st, j = post_json("/api/auth/register", {"username": uname, "password": "test123456"})
    ok = st == 200 and j.get("success") and j.get("data", {}).get("token")
    check("register test user", bool(ok), f"status={st}")
    if not ok:
        print("无法继续：注册失败", j)
        sys.exit(1)
    token = j["data"]["token"]

    # 5. 各 fragment 渲染（四期D组：learn_from_materials 已移出白名单）
    frag_ids = ["dashboard", "online_course_notes",
                "practice_knowledge", "practice_errors", "memory_knowledge",
                "memory_errors", "knowledge_base", "settings", "llm_logs"]
    for fid in frag_ids:
        st, _ = get("/fragments/" + fid, token=token)
        body_ok = False
        if st == 200:
            j2 = json.loads(get("/fragments/" + fid, token=token)[1])
            body_ok = j2.get("success") and isinstance(j2.get("data"), str) and len(j2["data"]) > 10
        check(f"fragment {fid}", st == 200 and body_ok, f"status={st}")

    # 6. practice_materials 无片段 -> 404（前端 fallback 整页跳 /practice）
    st, _ = get("/fragments/practice_materials", token=token)
    check("fragment practice_materials -> 404", st == 404, f"status={st}")

    # 6b. 四期D组：learn_from_materials 片段已下线 -> 404
    st, _ = get("/fragments/learn_from_materials", token=token)
    check("fragment learn_from_materials -> 404", st == 404, f"status={st}")

    # 7. SPA 壳关键元素：sidebar / api.js 挂载 / updateContentArea
    st, body = get("/")
    check("shell has sidebar", "sidebar" in body and "updateContentArea" in body, f"status={st}")
    check("shell loads api.js", "/static/js/api.js" in body, "")

    print()
    if FAILS:
        print(f"== {len(FAILS)} FAILED: {FAILS}")
        sys.exit(1)
    print("== ALL PAGE SMOKE TESTS PASSED ==")


if __name__ == "__main__":
    main()
