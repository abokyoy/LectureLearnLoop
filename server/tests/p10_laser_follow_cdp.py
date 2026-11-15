"""
P10「激光常驻 + 旁白自动跟随」CDP 取证（2026-11-09，用户裁定方案 B）。

用户痛点（原话）：激光笔时有时无，希望它随时都在、跟着老师解说的内容走，
让学生永远知道该看板上哪一处（尤其图上、板书上）。

本脚本走真链路自证（不塞内存桩）：
  进程内假小智云 -> 真 MCP 桥 -> board_write(带〔〕锚的步骤卡) +
  board_draw(geometry 三角形，派生 marks=点标 A/B/C 裸单字)；
  旁白走真 HTTP /api/board/speech（role=teacher/student 逐句）；
  headless Edge/Chrome(CDP) 打开 /teacher_board，实测 #tb-laser 行为。

覆盖取证点：
  P1 常驻：板上有可指对象时，静置 >3 秒（旧机制 3 秒自灭）激光 tb-laser-on
     一直亮、坐标有效（MutationObserver 全程无 remove）。
  P2 板书锚跟随：老师句里出现〔斜边〕锚文本 -> 服务端 focus.anchor 自动落该锚、
     前端该 tb-anc 点亮 tb-anc-on、激光坐标随之移动。
  P3 图点跟随：老师句「…点C…」(单字只认「点C」形式) -> focus 落 plot 卡 mark=3。
  P4 学生的话不动：学生句里出现「A点」也不移动激光（不伪造老师手势）。
  P5 无命中不动：老师句中不含任何锚/点标 -> focus 保持不变。

运行：python server/tests/p10_laser_follow_cdp.py
产物：server/tests/fixtures/p10_laser_*.png
依赖：本机 Edge 或 Chrome（自动找）、websockets、httpx、requests。
"""
from __future__ import annotations

import asyncio
import base64
import json
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import requests
import websockets

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent            # server/tests
SERVER = HERE.parent                              # server
FIX = HERE / "fixtures"
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(HERE))

from app import create_app                         # noqa: E402
from services import mcp_bridge as MB              # noqa: E402
from test_xz_teacher_board import FakeCloud        # noqa: E402

APP = create_app()
USER = "p10cdp_" + uuid.uuid4().hex[:6]
PWD = "test123456"

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
    """单 target 的 CDP ws 客户端（id 递增，串行使用）。"""

    def __init__(self, ws_url):
        self.ws_url, self.ws, self._id = ws_url, None, 0

    async def __aenter__(self):
        self.ws = await websockets.connect(self.ws_url, max_size=64 * 1024 * 1024)
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


async def cdp_pages(port):
    async with httpx.AsyncClient(timeout=10) as c:
        return [t for t in (await c.get(f"http://127.0.0.1:{port}/json/list")).json()
                if t.get("type") == "page"]


async def wait_cdp(port, timeout=40):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            pages = await cdp_pages(port)
            if pages:
                return pages[0]
        except Exception:
            pass
        await asyncio.sleep(0.5)
    return None


# ---------------------------------------------------------------- 服务端
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


def say(base, tok, role, text):
    requests.post(base + "/api/board/speech",
                  json={"role": role, "text": text, "ts": int(time.time() * 1000)},
                  headers={"Authorization": "Bearer " + tok}, timeout=6)


def get_focus(base, tok):
    h = {"Authorization": "Bearer " + tok}
    d = requests.get(base + "/api/board/state", headers=h, timeout=6).json()["data"]
    return d.get("focus"), d.get("items") or []


async def wait_focus_seq(base, tok, prev_seq, timeout=12):
    """等 focus.seq 变化（新跟随事件落地），返回 (focus, items)。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        f, items = get_focus(base, tok)
        if f and f.get("seq") != prev_seq:
            return f, items
        await asyncio.sleep(0.4)
    return get_focus(base, tok)


# ---------------------------------------------------------------- CDP
async def open_page(base, tok, cdp_port, profile):
    browser = find_browser()
    if not browser:
        step(False, "本机有 Edge/Chrome 可跑 headless 取证")
        return None
    proc = subprocess.Popen(
        [browser, "--headless=new", f"--remote-debugging-port={cdp_port}",
         f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
         "--disable-gpu", "--window-size=1440,900", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    target = await wait_cdp(cdp_port)
    step(target is not None, "headless 浏览器 CDP 就绪", browser.split("\\")[-1])
    if not target:
        proc.terminate()
        return None
    init = ("try{localStorage.setItem('ll_token', %s);}catch(e){}" % json.dumps(tok)) + "true"
    tb = Tab(target["webSocketDebuggerUrl"])
    await tb.__aenter__()
    await tb.send("Runtime.enable")
    await tb.send("Page.enable")
    await tb.send("Page.addScriptToEvaluateOnNewDocument", source=init)
    await tb.send("Page.navigate", url=base + "/teacher_board")
    booted = False
    deadline = time.time() + 40
    while time.time() < deadline:
        try:
            if await tb.ev("!!document.querySelector('#tb-board') && "
                           "!!document.querySelector('#tb-laser')"):
                booted = True
                break
        except RuntimeError:
            pass
        await asyncio.sleep(0.5)
    step(booted, "黑板页已打开（#tb-board + #tb-laser 就位）")
    if not booted:
        await tb.__aexit__()
        proc.terminate()
        return None
    await asyncio.sleep(2.0)
    return tb, proc


JS_LASER = """(() => {
  const L = document.querySelector('#tb-laser');
  if (!L) return {present: false};
  const r = L.getBoundingClientRect();
  return {present: true, on: L.classList.contains('tb-laser-on'),
          left: parseFloat(L.style.left) || 0, top: parseFloat(L.style.top) || 0,
          cx: Math.round(r.left + r.width / 2), cy: Math.round(r.top + r.height / 2),
          ancOn: document.querySelectorAll('#tb-board .tb-anc-on').length};
})()"""

JS_WATCH = """(() => {
  const L = document.querySelector('#tb-laser');
  window.__laserOff = 0;
  new MutationObserver(() => { if (!L.classList.contains('tb-laser-on')) window.__laserOff++; })
    .observe(L, {attributes: true, attributeFilter: ['class']});
  return true; })()"""


async def main() -> int:
    FIX.mkdir(parents=True, exist_ok=True)
    srv_port, cdp_port = free_port(), free_port()
    base = start_server(srv_port)
    tok, uid = make_user(base)
    step(True, "取证账号就绪", f"{USER} uid={uid}")

    MB._db_get = lambda key: ""
    MB.RETRY_S = 1
    cloud = FakeCloud()
    cloud.start()
    MB._spawn(f"ws://127.0.0.1:{cloud.port}/mcp", USER)
    step(cloud.wait_bridge(timeout=60), "MCP 桥已连上假小智云")
    if not cloud.wait_bridge(timeout=1):
        return 2

    # 上板：一张带〔〕锚的步骤卡 + 一张 geometry 三角形（派生 marks=点标 A/B/C）
    cloud.call_tool("board_write", {"content": "直角三角形里，两条〔直角边〕的平方和等于〔斜边〕的平方",
                                    "kind": "step"})
    cloud.call_tool("board_draw", {"title": "直角三角形", "spec": {
        "plot_type": "geometry",
        "points": [{"label": "A", "x": 0, "y": 0}, {"label": "B", "x": 4, "y": 0},
                   {"label": "C", "x": 2, "y": 3}],
        "segments": [{"a": "A", "b": "B"}, {"a": "B", "b": "C"}, {"a": "C", "b": "A"}]}})
    _, items = get_focus(base, tok)
    step_card = next((i for i in items if i["kind"] == "step"), None)
    plot_card = next((i for i in items if i["kind"] == "plot"), None)
    step(step_card is not None and plot_card is not None, "步骤卡与几何图卡已上板",
         f"step={step_card and step_card['id']} plot={plot_card and plot_card['id']}")
    marks = ((plot_card or {}).get("data") or {}).get("marks") or []
    step([m.get("name") for m in marks][:3] == ["A", "B", "C"],
         "geometry 派生 marks=点标裸单字（A/B/C）", str([m.get("name") for m in marks]))

    profile = HERE / f"_p10_profile_{uuid.uuid4().hex[:6]}"
    got = await open_page(base, tok, cdp_port, profile)
    if not got:
        return 2
    tb, proc = got
    try:
        # ---- P1 常驻：先让老师句命中图上点B（激光落右栏画幅），静置跨旧 3 秒自灭窗 ----
        say(base, tok, "teacher", "先看这张图，把这条线连到点B。")
        await asyncio.sleep(1.5)
        await tb.ev(JS_WATCH)
        lit = await tb.ev(JS_LASER)
        f_plot, _ = get_focus(base, tok)
        step(lit["present"] and lit["on"] and lit["cx"] > 0,
             "P1a 有焦点时激光亮且坐标有效（图上）", str(lit))
        await asyncio.sleep(4.0)          # 旧机制 3 秒会自灭，这里必须仍亮
        still = await tb.ev(JS_LASER)
        off_cnt = await tb.ev("window.__laserOff || 0")
        step(still["on"] and off_cnt == 0,
             "P1b 常驻：静置 4 秒（跨过旧 3 秒自灭窗）激光全程未灭",
             f"on={still['on']} offEvents={off_cnt}")
        await tb.shot("p10_laser_persist.png")

        # ---- P2 板书锚跟随：老师句从图上切到板书「斜边」，激光跨区移动 ----
        pos_before = (still["cx"], still["cy"])
        seq0 = (f_plot or {}).get("seq")
        say(base, tok, "teacher", "回来看板书，这一条斜边才是重点。")
        f1, _ = await wait_focus_seq(base, tok, seq0)
        anchors = (step_card or {}).get("anchors") or []
        exp_anchor = anchors.index("斜边") + 1 if "斜边" in anchors else None
        step(f1 and f1.get("item_id") == (step_card or {}).get("id")
             and f1.get("anchor") == exp_anchor,
             "P2a 服务端：老师句命中「斜边」 -> focus 落步骤卡对应锚（1 基）",
             f"focus={f1} anchors={anchors}")
        await asyncio.sleep(1.5)
        lit2 = await tb.ev(JS_LASER)
        step(lit2["on"] and lit2["ancOn"] >= 1 and
             abs(lit2["cx"] - pos_before[0]) + abs(lit2["cy"] - pos_before[1]) > 40,
             "P2b 前端：板书锚点亮 + 激光从图上跨区移到板书（位移 >40px）",
             f"before={pos_before} now=({lit2['cx']},{lit2['cy']})")
        await tb.shot("p10_laser_anchor.png")

        # ---- P3 图点跟随：老师句「…点C…」 -> focus 落 plot 卡 mark=3 ----
        seq1 = (f1 or {}).get("seq")
        say(base, tok, "teacher", "再看图，把这条线连到点C。")
        f2, _ = await wait_focus_seq(base, tok, seq1)
        step(f2 and f2.get("item_id") == (plot_card or {}).get("id") and f2.get("mark") == 3,
             "P3 服务端：老师句「点C」 -> focus 落几何图 mark=3（单字认「点C」形式）", str(f2))
        await asyncio.sleep(1.5)
        lit3 = await tb.ev(JS_LASER)
        step(lit3["on"], "P3b 图点跟随后激光仍亮（落点在图/卡上）", str(lit3))
        await tb.shot("p10_laser_mark.png")

        # ---- P4 学生的话不动激光 ----
        seq2 = (f2 or {}).get("seq")
        say(base, tok, "student", "老师，那点A在哪里呀？")
        await asyncio.sleep(1.8)
        f3, _ = get_focus(base, tok)
        step((f3 or {}).get("seq") == seq2,
             "P4 学生的句里出现「点A」也不移动焦点（不伪造老师手势）", str(f3))

        # ---- P5 老师句无命中不动 ----
        say(base, tok, "teacher", "这一节我们先讲到这里，做个小结。")
        await asyncio.sleep(1.8)
        f4, _ = get_focus(base, tok)
        step((f4 or {}).get("seq") == seq2,
             "P5 老师句中无任何锚/点标 -> 焦点保持不变（不乱指）", str(f4))
        return 0
    finally:
        await tb.send("Page.navigate", url="about:blank")
        await tb.__aexit__()
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    code = 1
    try:
        code = asyncio.run(main())
    except BaseException as e:                    # never let a throw masquerade as pass
        import traceback
        traceback.print_exc()
        fails.append("uncaught: " + repr(e)[:160])
    finally:
        verdict = ("ALL PASS" if not fails and code == 0
                   else ("FAIL(" + str(len(fails)) + "): " + " | ".join(fails)
                         if fails else "EARLY EXIT code=" + str(code)))
        print("\n==== P10 CDP(激光常驻+旁白跟随): " + verdict + " ====")
        sys.exit(0 if not fails and code == 0 else 2)
