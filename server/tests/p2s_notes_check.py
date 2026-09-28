# -*- coding: utf-8 -*-
"""二期学习笔记自证（纯 HTTP，对齐全计划验收点）。

链路：注册临时用户 → 建笔记 → autosave 入库 → /api/notes/content 轮询可见 →
recording 标志与 /api/notes/active 横幅源 → 截图嵌入同步入库 → 完成清标志 →
MD 文件与库正文一致 → 跨用户越权防护。断言全部走 HTTP 返回值，可重复执行。
"""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:6001"
PNG_1PX = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQ"
           "GAhKmMIQAAAABJRU5ErkJggg==")

PASS_CNT = 0
FAILS = []


def req(method, path, data=None, token=None, timeout=30):
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


def main():
    ts = str(int(time.time()))
    t1 = register("p2notes_a_" + ts)
    t2 = register("p2notes_b_" + ts)
    check("注册两个临时用户取得 token", bool(t1 and t2))
    if not (t1 and t2):
        return finish()

    # 1) 建笔记（既有 bridge 端点）
    st, b = req("POST", "/api/vault/note", {"folder_path": "vault"}, t1)
    name = b.get("data") or ""
    rel = "vault/" + name
    check("新建笔记返回文件名", st == 200 and bool(name), str(b))

    # 2) autosave：写文件 + 正文入库
    body1 = "# 听课笔记\n\n## 转写全文\n\n大家好这是一段测试转写文本\n"
    st, b = req("POST", "/api/notes/autosave", {"path": rel, "content": body1}, t1)
    d = b.get("data", {})
    check("autosave 成功且返回 updated_time/note_id", st == 200 and d.get("success") and d.get("updated_time") and d.get("note_id"), str(b))
    upd1 = d.get("updated_time", "")

    # 3) 轮询读取：库为权威源
    st, b = req("GET", "/api/notes/content?path=" + urllib.parse.quote(rel), None, t1)
    d = b.get("data", {})
    check("content 轮询可见正文(source=db)", st == 200 and d.get("exists") and d.get("source") == "db" and d.get("content") == body1, str(d)[:200])
    check("content 字数统计>0", (d.get("word_count") or 0) > 0, str(d.get("word_count")))

    # 4) recording 标志 + active 横幅源
    st, b = req("POST", "/api/notes/recording", {"path": rel, "on": True}, t1)
    check("置录制中标志", st == 200 and b.get("data", {}).get("success"), str(b))
    st, b = req("GET", "/api/notes/active", None, t1)
    items = b.get("data", {}).get("items", [])
    check("active 返回录制中笔记", any(name in (i.get("name") or "") for i in items), str(items)[:200])
    st, b = req("GET", "/api/notes/list", None, t1)
    li = [i for i in b.get("data", {}).get("items", []) if i.get("name") == name]
    check("list 可见该笔记且 recording=True", bool(li) and li[0].get("recording") is True, str(li)[:200])

    # 5) 截图嵌入同步入库（screenshot 带 note_path 追加后 upsert）
    st, b = req("POST", "/api/vault/screenshot", {"image_b64": PNG_1PX, "note_path": rel}, t1)
    d = b.get("data", {})
    check("截图保存并追加笔记", st == 200 and d.get("success") and d.get("appended_to_note"), str(b)[:200])
    st, b = req("GET", "/api/notes/content?path=" + urllib.parse.quote(rel), None, t1)
    d = b.get("data", {})
    check("截图 markdown 已同步入库", ("![截屏]" in (d.get("content") or "")) and (body1 in (d.get("content") or "")), str(d)[:200])
    upd2 = d.get("updated_time", "")
    check("轮询水位 updated_time 前进", upd2 >= upd1, upd1 + " -> " + upd2)

    # 6) MD 文件与库正文一致（文件一手落盘，一手入库）
    st, b = req("GET", "/api/vault/rawfile?path=" + urllib.parse.quote(rel), None, t1)
    file_text = b.get("data") or ""
    st, b2 = req("GET", "/api/notes/content?path=" + urllib.parse.quote(rel), None, t1)
    db_text = b2.get("data", {}).get("content") or ""
    check("MD 文件与库正文一致", file_text == db_text and len(db_text) > 0,
          f"file={len(file_text)} db={len(db_text)}")

    # 7) 完成：清 recording 标志
    st, b = req("POST", "/api/notes/recording", {"path": rel, "on": False}, t1)
    check("清除录制中标志", st == 200 and b.get("data", {}).get("success"), str(b))
    st, b = req("GET", "/api/notes/active", None, t1)
    items = b.get("data", {}).get("items", [])
    check("active 已清空", all((i.get("name") or "") != name for i in items), str(items)[:120])

    # 8) 跨用户越权防护：u2 读 u1 绝对路径被拒
    st, b = req("GET", "/api/notes/active", None, t2)
    check("u2 active 隔离(空)", st == 200 and not any(name in json.dumps(i, ensure_ascii=False) for i in b.get("data", {}).get("items", [])), str(b)[:160])
    st, b = req("GET", "/api/vault/tree-nested", None, t1)
    u1abs = None

    def walk(nodes):
        global u1abs
        for n in nodes or []:
            if (n.get("name") or n.get("text") or "") == name:
                u1abs = n.get("path") or n.get("id")
            walk(n.get("children"))
    walk(b.get("data") if isinstance(b.get("data"), list) else [])
    if u1abs:
        st, _ = req("GET", "/api/notes/content?path=" + urllib.parse.quote(str(u1abs)), None, t2)
        check("u2 越权读 u1 笔记被拒(403)", st == 403, "status=" + str(st))
    else:
        # 兜底：直接拿 rel 也试一次跨用户（u2 无此文件 → exists False，不得泄露正文）
        st, b = req("GET", "/api/notes/content?path=" + urllib.parse.quote(rel), None, t2)
        d = b.get("data", {})
        check("u2 读同名相对路径不泄露正文", st == 200 and not d.get("content"), str(d)[:120])

    # 9) autosave 非法路径防护（越出 vault root）
    st, _ = req("POST", "/api/notes/autosave", {"path": "../evil.md", "content": "x"}, t1)
    check("autosave 越界路径被拒(403)", st == 403, "status=" + str(st))
    return finish()


def finish():
    print(f"\nRESULT: PASS={PASS_CNT} FAIL={len(FAILS)}")
    for f in FAILS:
        print("  FAIL -> " + f)
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
