# -*- coding: utf-8 -*-
"""三期知识脑图自证（纯 HTTP，真实 LLM 一次 + 幂等再生成一次）。

链路：注册临时用户 → autosave 建笔记 → POST /api/notes/mindmap（真实 LLM）→
正文含标记段与 mermaid 代码、库/文件逐字一致、updated_time 前进 →
再生成断言幂等只保留一段 → 录音中 409 → 路径穿越 403 →
两个前端页面静态断言（Select all 条 / checkbox / 生成脑图按钮）。
"""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:6001"

PASS_CNT = 0
FAILS = []


def req(method, path, data=None, token=None, timeout=60):
    r = urllib.request.Request(BASE + path, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    body = json.dumps(data).encode() if data is not None else None
    try:
        with urllib.request.urlopen(r, body, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8", "replace") or "{}")
        except Exception:  # noqa: BLE001
            return e.code, {}


def get_text(path, token=None, timeout=30):
    r = urllib.request.Request(BASE + path)
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""


def check(name, ok, detail=""):
    global PASS_CNT
    if ok:
        PASS_CNT += 1
        print("PASS  " + name)
    else:
        FAILS.append(name + " " + detail)
        print("FAIL  " + name + " " + detail)


def register(uname):
    # 注册后必走一次 login：每日赠分挂在 login 钩子上，LLM 端点积分预检才放行
    req("POST", "/api/auth/register", {"username": uname, "password": "Passw0rd!"})
    st, b = req("POST", "/api/auth/login", {"username": uname, "password": "Passw0rd!"})
    return b.get("data", {}).get("token")


POINTS = [
    {"name": "构造函数", "description": "对象初始化时自动执行，与类同名，用于建立对象初始状态"},
    {"name": "继承", "description": "子类复用父类字段与方法，支持单继承与多层扩展"},
    {"name": "多态", "description": "同一接口不同实现，运行时按对象实际类型分派调用"},
]


def main():
    ts = str(int(time.time()))
    t1 = register("p3mmap_u_" + ts)
    check("注册/登录获得 token", bool(t1))
    if not t1:
        finish()

    rel = "vault/脑图自证_" + ts + ".md"
    body0 = "# 面向对象程序设计\n\n本课讲解构造函数、继承与多态。"
    st, b = req("POST", "/api/notes/autosave", {"path": rel, "content": body0}, t1)
    check("autosave 建笔记", st == 200 and b.get("data", {}).get("success"))
    ut0 = b.get("data", {}).get("updated_time", "")

    # 1) 真实 LLM 首次生成
    st, b = req("POST", "/api/notes/mindmap",
                {"path": rel, "title": "面向对象程序设计", "points": POINTS}, t1, timeout=120)
    d = b.get("data", {})
    check("生成脑图返回 200", st == 200 and d.get("success"), "st=%s err=%s" % (st, b.get("error")))
    mm = d.get("mermaid") or ""
    check("mermaid 为 mindmap 且含 root", mm.startswith("mindmap") and "root" in mm, mm[:80])
    check("首次生成 replaced=False", d.get("replaced") is False)
    check("updated_time 前进", (d.get("updated_time") or "") >= ut0)

    st, b = req("GET", "/api/notes/content?path=" + urllib.parse.quote(rel), token=t1)
    c1 = b.get("data", {}).get("content", "")
    check("正文含脑图标记段与代码块",
          "<!-- LL:MMAP:BEGIN -->" in c1 and "```mermaid" in c1 and "<!-- LL:MMAP:END -->" in c1)
    check("原正文保留", "面向对象程序设计" in c1 and "构造函数" in c1)
    check("库为权威源 source=db", b.get("data", {}).get("source") == "db")

    # 2) MD 文件与库逐字一致
    st, raw = get_text("/api/vault/rawfile?path=" + urllib.parse.quote(rel), t1)
    check("文件与库正文逐字一致", st == 200 and json.loads(raw).get("data") == c1)

    # 3) 幂等：再生成只保留一段
    st, b = req("POST", "/api/notes/mindmap",
                {"path": rel, "title": "面向对象程序设计", "points": POINTS[:2]}, t1, timeout=120)
    d2 = b.get("data", {})
    check("二次生成 200 且 replaced=True", st == 200 and d2.get("success") and d2.get("replaced") is True)
    st, b = req("GET", "/api/notes/content?path=" + urllib.parse.quote(rel), token=t1)
    c2 = b.get("data", {}).get("content", "")
    check("仅保留一段脑图标记",
          c2.count("<!-- LL:MMAP:BEGIN -->") == 1 and c2.count("<!-- LL:MMAP:END -->") == 1)

    # 4) 录音中拒绝 409
    req("POST", "/api/notes/recording", {"path": rel, "on": True}, t1)
    st, b = req("POST", "/api/notes/mindmap", {"path": rel, "points": POINTS[:1]}, t1)
    check("录音中生成脑图 409", st == 409, "st=%s" % st)
    req("POST", "/api/notes/recording", {"path": rel, "on": False}, t1)

    # 5) 防护
    st, b = req("POST", "/api/notes/mindmap", {"path": "../evil.md", "points": POINTS[:1]}, t1)
    check("路径穿越 403", st == 403)
    st, b = req("POST", "/api/notes/mindmap", {"path": rel, "points": []}, t1)
    check("空知识点 400", st == 400)
    st, b = req("POST", "/api/notes/mindmap", {"path": rel, "points": POINTS[:1]})
    check("未认证 401", st == 401)

    # 6) 两个前端页面静态断言（三期交付内容在线上页；
    #    四期D组：/learn_materials 已 302 合并到 /online_course，urllib 自动跟随后断言仍验证合并页交付内容）
    for page, name in (("/online_course", "在线课程笔记页"), ("/learn_materials", "学习资料页(302→合并页)")):
        st, html = get_text(page, t1)
        ok = (st == 200 and "point-select-bar" in html and "point-select-all" in html
              and "point-check" in html and "gen-mindmap-btn" in html
              and "generateKnowledgeMindmap" in html)
        check(name + " 交付内容断言(200+勾选/脑图元素)", ok, "st=%s" % st)

    # 7) 清理：恢复笔记原始正文（去脑图段），文件与库同步复原
    st, b = req("POST", "/api/notes/autosave", {"path": rel, "content": body0}, token=t1)
    check("清理：恢复原正文", st == 200 and b.get("data", {}).get("success"))
    st, b = req("GET", "/api/notes/content?path=" + urllib.parse.quote(rel), token=t1)
    clean = b.get("data", {}).get("content", "")
    check("清理后无脑图标记段", "LL:MMAP" not in clean and clean == body0)

    finish()


def finish():
    print("----")
    print("PASS %d / FAIL %d" % (PASS_CNT, len(FAILS)))
    for f in FAILS:
        print("FAILED:", f)
    sys.exit(0 if not FAILS else 1)


if __name__ == "__main__":
    main()
