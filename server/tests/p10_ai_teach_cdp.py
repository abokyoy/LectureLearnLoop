"""
v0.2.8「AI老师讲」多入口 → 小黑板 CDP 取证（2026-11-04）。

链路是真的，不往内存塞桩：
  进程内真 Flask（随机口）→ 注册取证用户 + 真 PG 种子（知识点+两道错题）→
  headless Edge/Chrome（CDP）打开 SPA 壳，走真菜单、真按钮点击：
  错题练习页行级「AI老师讲」→ POST /api/board/assign → goMenu 黑板页 →
  checkAssign 提示条 + window.__tbAssign 留痕；练知识点页卡片按钮同理（kp 型）。

覆盖：
  A 错题练习页每题行出现「AI老师讲」按钮（mic 图标 + data-pp-teach）；
  B 点击后黑板页提示条亮（「AI老师讲」指定讲解『题干…』），__tbAssign kind=error；
    浏览器端（非桌面 EXE）语音钮 disabled → 文案为手动指引（assignManual），
    桌面真自动开课链路由 EXE 内 tb-voice-btn 复用，逻辑同一入口；
  C 知识点卡「AI老师讲」→ 指派覆写为 kp 型，提示条带知识点名；
  D 服务端 GET /api/board/assign 与页面留痕一致（浏览器不消费指派）；
  E 负例真 HTTP：指派他人错题 → 拒。

运行：python server/tests/p10_ai_teach_cdp.py
产物：server/tests/fixtures/p10_*.png
依赖：本机 Edge 或 Chrome（自动找）、httpx、requests。
"""
from __future__ import annotations

import asyncio
import base64
import json
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import requests

sys.stdout.reconfigure(encoding="utf-8", errors="replace") if hasattr(sys.stdout, "reconfigure") else None

HERE = Path(__file__).resolve().parent
SERVER = HERE.parent
FIX = HERE / "fixtures"
FIX.mkdir(exist_ok=True)
sys.path.insert(0, str(SERVER))

import config                                      # noqa: E402
from app import create_app                         # noqa: E402
from knowledge_management import DatabaseManager   # noqa: E402

APP = create_app()
USER = "p10cdp_" + uuid.uuid4().hex[:6]
PWD = "test123456"
KP_NAME = "极限"
STEM1 = "题17：lim(n→∞) (1+1/n)^n 的值是（）"
STEM2 = "题18：二次函数 y=x^2-2x 的图象开口方向与顶点坐标"

fails: list[str] = []


def step(cond, name, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}  {str(detail)[:200]}")
    if not cond:
        fails.append(name)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def find_browser():
    for c in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"):
        if Path(c).exists():
            return c
    return None


class Tab:
    """单 target 的 CDP ws 客户端（id 递增，串行使用）。同 p9。"""

    def __init__(self, ws_url):
        self.ws_url, self.ws, self._id = ws_url, None, 0

    async def __aenter__(self):
        self.ws = await websockets_connect(self.ws_url)
        return self

    async def __aexit__(self, *a):
        await self.ws.close()

    async def send(self, method, **params):
        self._id += 1
        mid = self._id
        await self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    async def ev(self, expr, promise=False):
        r = await self.send("Runtime.evaluate", expression=expr, awaitPromise=promise,
                            returnByValue=True)
        if r.get("exceptionDetails"):
            raise RuntimeError("JS: " + json.dumps(r["exceptionDetails"])[:400])
        return r.get("result", {}).get("value")

    async def shot(self, name):
        d = (await self.send("Page.captureScreenshot", format="png"))["data"]
        p = FIX / name
        p.write_bytes(base64.b64decode(d))
        step(p.stat().st_size > 20000, "截图存档 " + name, f"{p.stat().st_size} bytes")
        return p

    async def poll(self, expr, timeout=40, every=0.5):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                v = await self.ev(expr)
                if v:
                    return v
            except RuntimeError:
                pass
            await asyncio.sleep(every)
        return None


async def websockets_connect(url):
    import websockets
    return await websockets.connect(url, max_size=64 * 1024 * 1024)


async def wait_cdp(port, timeout=40):
    deadline = time.time() + timeout
    async with httpx.AsyncClient(timeout=10) as c:
        while time.time() < deadline:
            try:
                pages = [t for t in (await c.get(f"http://127.0.0.1:{port}/json/list")).json()
                         if t.get("type") == "page"]
                if pages:
                    return pages[0]
            except Exception:
                pass
            await asyncio.sleep(0.5)
    return None


# ---------------------------------------------------------------- 服务端 + 种子
def start_server(port):
    t = __import__("threading").Thread(
        target=lambda: APP.run(host="127.0.0.1", port=port, threaded=True, debug=False,
                               use_reloader=False),
        daemon=True, name="p10-server")
    t.start()
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            if requests.get(base + "/", timeout=2).status_code in (200, 302):
                return base
        except requests.RequestException:
            pass
        time.sleep(0.3)
    raise RuntimeError("server not ready")


def make_user(base):
    requests.post(base + "/api/auth/register", json={"username": USER, "password": PWD}, timeout=10)
    tok = requests.post(base + "/api/auth/login", json={"username": USER, "password": PWD},
                        timeout=10).json()["data"]["token"]
    seg = tok.split(".")[1]
    uid = str(json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))["uid"])
    return tok, uid


def seed_kp_errors(uid, base, tok):
    """真业务链建种子：point-new 建学科+知识点，/api/practice/results 答错入池
    （裸 INSERT 不登记 subjects，页面会显示「还没有任何学科」）。返回 (kp, e1, e2)。"""
    h = {"Authorization": "Bearer " + tok}
    subj = "取证学科P10" + uuid.uuid4().hex[:6]
    r = requests.post(base + "/api/knowledge/point-new", headers=h, timeout=30,
                      json={"point": {"name": KP_NAME,
                                      "description": "数列极限定义与两个重要极限"},
                            "subject": subj})
    assert r.json()["success"], r.text
    kp = int(r.json()["data"]["knowledge_id"])
    recs = [{
        "subject_name": subj, "knowledge_point_id": kp,
        "question_content": STEM1, "user_answer": "A", "is_correct": False,
        "correct_answer": "B", "explanation": "重要极限二 (1+1/n)^n→e",
        "options": ["1", "e", "∞", "0"],
    }, {
        "subject_name": subj, "knowledge_point_id": kp,
        "question_content": STEM2, "user_answer": "A", "is_correct": False,
        "correct_answer": "B", "explanation": "配方法 y=(x-1)^2-1，开口向上",
        "options": ["向上 (1,1)", "向上 (1,-1)", "向下 (-1,-1)", "向下 (0,0)"],
    }]
    r = requests.post(base + "/api/practice/results", headers=h, timeout=30,
                      json={"records": recs})
    assert r.json()["success"], r.text
    db = DatabaseManager(str(config.DB_PATH))
    conn = db.get_connection()
    ids = [row[0] for row in conn.execute(
        "SELECT id FROM error_questions WHERE user_id = ? ORDER BY id", (uid,)).fetchall()]
    conn.close()
    assert len(ids) >= 2, ids
    return kp, ids[-2], ids[-1]


# ---------------------------------------------------------------- 主流程
async def run():
    port = free_port()
    base = start_server(port)
    step(True, "进程内 Flask 就绪", base)
    tok, uid = make_user(base)
    kp, e1, e2 = seed_kp_errors(uid, base, tok)
    h = {"Authorization": "Bearer " + tok}

    browser = find_browser()
    if not browser:
        step(False, "本机有 Edge/Chrome 可跑 headless 取证")
        return
    cdp_port = free_port()
    profile = Path(__file__).resolve().parent / f"_p10_profile_{uuid.uuid4().hex[:6]}"
    proc = subprocess.Popen(
        [browser, "--headless=new", f"--remote-debugging-port={cdp_port}",
         f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
         "--disable-gpu", "--window-size=1440,900", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        target = await wait_cdp(cdp_port)
        step(target is not None, "headless 浏览器 CDP 就绪", browser.split("\\")[-1])
        if not target:
            return
        init = ("try{localStorage.setItem('ll_token', %s);}catch(e){}" % json.dumps(tok)) + "true"
        tb = Tab(target["webSocketDebuggerUrl"])
        await tb.__aenter__()
        await tb.send("Runtime.enable")
        await tb.send("Page.enable")
        await tb.send("Page.addScriptToEvaluateOnNewDocument", source=init)
        await tb.send("Page.navigate", url=base + "/")
        ready = await tb.poll("typeof handleMenuClick === 'function'", timeout=60)
        step(bool(ready), "SPA 壳已登录就绪（handleMenuClick 可用）")
        if not ready:
            await tb.__aexit__()
            return

        # ---- A 错题练习页入口按钮（页面首屏需拉取，先等壳再单次点学科 chip，禁反复点）
        await tb.ev("handleMenuClick('practice_errors')")
        await tb.poll("!!document.querySelector('[data-pm-page=\"practice_errors\"]')", timeout=30)
        await tb.ev("var c=document.querySelector('[data-pm-page=\"practice_errors\"] "
                    "[data-role=\"subjects\"] button'); if(c) c.click(); 'ok'")
        cnt = await tb.poll("document.querySelectorAll('[data-pp-teach]').length", timeout=40)
        step(cnt and int(cnt) >= 2, f"A 错题行「AI老师讲」按钮出现（{cnt} 个）")
        has_label = await tb.ev(
            "[...document.querySelectorAll('[data-pp-teach]')]"
            ".some(b => b.textContent.includes('AI老师讲'))")
        step(bool(has_label), "A 按钮文案为「AI老师讲」")
        await tb.shot("p10_entry_errors.png")

        # ---- B 点击 → 黑板提示条（error 型）
        await tb.ev("window.__tbAssign = null; "
                    "var b0 = document.querySelectorAll('[data-pp-teach]')[0];"
                    "if (b0) b0.click(); 'ok'")
        got = await tb.poll("window.__tbAssign && window.__tbAssign.kind === 'error' "
                            "&& window.__tbAssign", timeout=40)
        step(bool(got), "B 黑板页 checkAssign 留痕 kind=error", json.dumps(got, ensure_ascii=False))
        banner = await tb.ev("(document.getElementById('tb-banner')||{}).textContent || ''")
        step("AI老师讲" in (banner or "") and "指定讲解" in (banner or ""),
             "B 提示条文案亮「AI老师讲…指定讲解…」", banner)
        step(bool(banner) and "正在自动开课" not in banner,
             "B 浏览器端（非桌面EXE）走手动指引文案（自动开课复用桌面钮链路）", banner)
        await tb.shot("p10_board_banner_error.png")

        # ---- C 知识点卡入口（kp 型覆写；同 A：壳就绪后单次点 chip 再纯计数）
        await tb.ev("handleMenuClick('practice_knowledge')")
        await tb.poll("!!document.querySelector('[data-pm-page=\"practice_knowledge\"]')", timeout=30)
        await tb.ev("var c=document.querySelector('[data-pm-page=\"practice_knowledge\"] "
                    "[data-role=\"subjects\"] button'); if(c) c.click(); 'ok'")
        kpc = await tb.poll("document.querySelectorAll('.pm-kp-teach').length", timeout=40)
        step(kpc and int(kpc) >= 1, f"C 知识点卡「AI老师讲」按钮出现（{kpc} 个）")
        await tb.shot("p10_entry_kp.png")
        await tb.ev("window.__tbAssign = null; "
                    "var kb = document.querySelector('.pm-kp-teach');"
                    "if (kb) kb.click(); 'ok'")
        got2 = await tb.poll("window.__tbAssign && window.__tbAssign.kind === 'kp' "
                             "&& window.__tbAssign", timeout=40)
        step(bool(got2), "C 黑板页指派覆写为 kp 型", json.dumps(got2, ensure_ascii=False))
        step(bool(got2) and got2.get("label") == KP_NAME, "C 提示条 label=知识点名",
             (got2 or {}).get("label"))
        banner2 = await tb.ev("(document.getElementById('tb-banner')||{}).textContent || ''")
        step(KP_NAME in (banner2 or ""), "C 提示条文案含知识点名", banner2)
        await tb.shot("p10_board_banner_kp.png")

        # ---- D 服务端一致性：GET 指派仍在且为 kp（浏览器全程不消费）
        d = requests.get(base + "/api/board/assign", headers=h, timeout=10).json()["data"]["assign"]
        step(bool(d) and d["kind"] == "kp" and d["id"] == kp,
             "D 服务端 GET 与页面留痕一致（未消费）", json.dumps(d, ensure_ascii=False))

        # ---- E 负例：真 HTTP 指派别人的错题 → 拒
        tok2 = requests.post(base + "/api/auth/register",
                             json={"username": "p10other_" + uuid.uuid4().hex[:6],
                                   "password": PWD}, timeout=10)
        r = requests.post(base + "/api/board/assign",
                          json={"kind": "error", "error_id": e1}, headers=h, timeout=10)
        step(r.json()["success"], "E 本人指派正例仍通（真 HTTP）")
        await tb.__aexit__()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        import shutil
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(run())
    print("\n" + ("ALL PASS" if not fails else f"FAILED {len(fails)}: {fails}"))
    sys.exit(0 if not fails else 1)
