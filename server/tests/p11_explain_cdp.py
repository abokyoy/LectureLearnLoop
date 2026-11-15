"""
P11 黑板「原理图」入口（html-explainer Demo 轮）CDP 取证（2026-11-09）。

用户任务：在 AI 老师黑板页的板上方加一个入口，点击后把当前课堂信息交给
自家大模型，按 html-explainer 的方法论（模型现写自包含 HTML 画面，浏览器
渲染，不生成像素）生成一页可交互的原理图，成功后弹窗展示，先看效果。

本脚本走真 UI 链路（headless Edge 真点击），LLM 用桩（本进程 monkeypatch
BE.call_llm_for_user，产一份带交互纪律的示范 HTML）：
  H1 点击入口 → 弹窗立刻出现并显示「正在生成」等待态（后台作业模式）；
  H2 作业 done → 弹窗内 sandboxed iframe 渲染出原理图（截图存档）；
  H3 iframe 内真点击 → 沙箱脚本执行并 postMessage 回父页（交互活的）；
  H4 关窗再点入口 → 秒开缓存结果，不再发起第二次生成（不双扣分）；
  H5 「重新生成」+ 模型返回脏内容 → 弹窗内失败提示（终态失败有反馈）。

运行：python server/tests/p11_explain_cdp.py
产物：server/tests/fixtures/p11_explain_*.png
"""
from __future__ import annotations

import asyncio
import base64
import json
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import httpx
import requests
import websockets

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
SERVER = HERE.parent
FIX = HERE / "fixtures"
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(HERE))

from app import create_app                         # noqa: E402
from services import board_explainer as BE         # noqa: E402
from services import mcp_bridge as MB              # noqa: E402
from test_xz_teacher_board import FakeCloud        # noqa: E402

APP = create_app()
USER = "p11cdp_" + uuid.uuid4().hex[:6]
PWD = "test123456"

fails: list[str] = []


def step(cond, name, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}  {str(detail)[:220]}")
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


# ---------------------------------------------------------------- LLM 桩
# 示范 html 特意按 html-explainer 纪律写：CSS 变量配色、系统字体栈、一景一焦点
# 分 3 步、无外链，且「点一下画面推进一步」并 postMessage 回父页（证明沙箱脚本真的在跑）。
_DEMO_HTML = """<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><style>
:root{--ink:#1f2937;--accent:#f59e0b;--c1:#2563eb;--bg:#ffffff;--mut:#9ca3af;--soft:#eff6ff}
*{box-sizing:border-box}body{margin:0;padding:28px;background:var(--bg);color:var(--ink);
font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
h2{margin:0 0 6px;font-size:26px}p.sub{margin:0 0 18px;color:var(--mut);font-size:15px}
.stage{display:flex;gap:28px;align-items:center}
svg{flex:0 0 340px}
.panel{flex:1;min-width:240px}
.cap{font-size:20px;line-height:1.6;min-height:3.2em;padding:14px 16px;
background:var(--soft);border-left:4px solid var(--accent);border-radius:8px}
.dots{margin-top:14px;display:flex;gap:8px}
.dot{width:12px;height:12px;border-radius:99px;background:var(--mut)}
.dot.on{background:var(--accent)}
.hint{margin-top:14px;font-size:13px;color:var(--mut)}
.seg{opacity:0;transition:opacity .6s}.show .seg{opacity:1}
.mid{stroke:var(--accent);stroke-width:4}
</style></head><body>
<h2>三角形中位线定理 · 交互演示</h2>
<p class="sub">点画面任意处，下一步</p>
<div class="stage" id="S">
<svg viewBox="0 0 200 160" width="340">
 <polygon points="30,130 170,130 100,30" fill="none" stroke="var(--c1)" stroke-width="3"/>
 <line class="seg mid" x1="65" y1="80" x2="135" y2="80"/>
 <circle cx="30" cy="130" r="4" fill="var(--c1)"/><circle cx="170" cy="130" r="4" fill="var(--c1)"/>
 <circle cx="100" cy="30" r="4" fill="var(--c1)"/>
 <text x="18" y="146" font-size="12">A</text><text x="166" y="146" font-size="12">B</text>
 <text x="96" y="22" font-size="12">C</text>
 <text x="52" y="72" font-size="12" fill="var(--accent)">D</text>
 <text x="132" y="72" font-size="12" fill="var(--accent)">E</text>
</svg>
<div class="panel">
 <div class="cap" id="cap"></div>
 <div class="dots"><i class="dot" id="d0"></i><i class="dot" id="d1"></i><i class="dot" id="d2"></i></div>
 <p class="hint">DE 是中位线：DE 平行 AB，且 DE = &#189; AB</p>
</div></div>
<script>
var caps=["第1步：三角形ABC，D、E 分别是两边 AC、BC 的中点。",
"第2步：连中点 D、E —— 这条 DE 就叫中位线（高亮那条橙色线）。",
"第3步：定理：中位线 DE 平行于底边 AB，且长度等于底边的一半。"];
var cur=0;
function render(){
 var S=document.getElementById('S');
 S.className='stage'+(cur>=1?' show':'');
 document.getElementById('cap').textContent=caps[cur];
 for(var i=0;i<3;i++)document.getElementById('d'+i).className=
   'dot'+(i===cur?' on':'');
 try{parent.postMessage({t:'hx-step',n:cur},'*')}catch(e){}
}
document.addEventListener('click',function(){cur=(cur+1)%caps.length;render()});
window.addEventListener('load',render);
</script></body></html>"""

_stub_state = {"mode": "ok", "calls": []}


def _stub(uid, prompt, context="", scene="", timeout=None, thinking=None):
    _stub_state["calls"].append({"scene": scene, "prompt_len": len(prompt),
                                 "thinking": thinking})
    if _stub_state["mode"] == "garbage":
        return "抱歉，我这次输出不了 JSON"
    time.sleep(1.2)                     # 模拟模型时延，给等待态留观测窗
    return json.dumps({"title": "中位线定理 · 原理图",
                       "narration": "这张图演示中位线为什么等于底边的一半",
                       "html": _DEMO_HTML}, ensure_ascii=False)


BE.call_llm_for_user = _stub


# ---------------------------------------------------------------- 服务端
def start_server(port):
    t = threading.Thread(
        target=lambda: APP.run(host="127.0.0.1", port=port, threaded=True, debug=False,
                               use_reloader=False),
        daemon=True, name="p11-server")
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
    return tok


def say(base, tok, role, text):
    requests.post(base + "/api/board/speech",
                  json={"role": role, "text": text, "ts": int(time.time() * 1000)},
                  headers={"Authorization": "Bearer " + tok}, timeout=6)


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
                           "!!document.querySelector('#tb-explain-btn')"):
                booted = True
                break
        except RuntimeError:
            pass
        await asyncio.sleep(0.5)
    step(booted, "黑板页已打开（#tb-explain-btn 入口就位，板上方入口取证前提）")
    if not booted:
        await tb.__aexit__()
        proc.terminate()
        return None
    await asyncio.sleep(2.0)
    return tb, proc


JS_MSGS = ("window.__hxMsgs=[];addEventListener('message',function(e){"
           "var d=e.data;if(d&&d.t==='hx-step')window.__hxMsgs.push(d.n)});true")
JS_MASK_STATE = """(() => { const m = document.querySelector('#tb-explain-mask');
  const b = document.querySelector('#tb-explain-body');
  return {open: !!(m && !m.classList.contains('hidden')),
          hasIframe: !!(b && b.querySelector('iframe')),
          bodyText: b ? (b.textContent || '').slice(0, 60) : ''};})()"""
JS_IFRAME_RECT = """(() => { const f = document.querySelector('#tb-explain-body iframe');
  if (!f) return null; const r = f.getBoundingClientRect();
  return {x: r.left + r.width / 2, y: r.top + r.height / 2};})()"""


async def wait_iframe(tb, timeout=25):
    deadline = time.time() + timeout
    st = None
    while time.time() < deadline:
        st = await tb.ev(JS_MASK_STATE)
        if st and st["hasIframe"]:
            return st
        await asyncio.sleep(0.4)
    return st


async def main() -> int:
    FIX.mkdir(parents=True, exist_ok=True)
    srv_port, cdp_port = free_port(), free_port()
    base = start_server(srv_port)
    tok = make_user(base)
    step(True, "取证账号就绪", USER)

    MB._db_get = lambda key: ""
    MB.RETRY_S = 1
    cloud = FakeCloud()
    cloud.start()
    MB._spawn(f"ws://127.0.0.1:{cloud.port}/mcp", USER)
    step(cloud.wait_bridge(timeout=60), "MCP 桥已连上假小智云")
    if not cloud.wait_bridge(timeout=1):
        return 2

    # 真实上板：老师写过字、说过话（这就是原理图的课堂素材来源）
    cloud.call_tool("board_write", {"content": "三角形的〔中位线〕平行于底边，且等于底边的一半",
                                    "kind": "step"})
    cloud.call_tool("board_draw", {"title": "中位线图", "spec": {
        "plot_type": "geometry",
        "points": [{"label": "A", "x": 0, "y": 0}, {"label": "B", "x": 4, "y": 0},
                   {"label": "C", "x": 2, "y": 3}],
        "segments": [{"a": "A", "b": "B"}, {"a": "B", "b": "C"}, {"a": "C", "b": "A"}]}})
    say(base, tok, "teacher", "我们把中位线连出来看看，它和底边是什么关系。")
    step(True, "板面已有内容（卡+图+旁白），原理图有料可生成")

    profile = HERE / f"_p11_profile_{uuid.uuid4().hex[:6]}"
    got = await open_page(base, tok, cdp_port, profile)
    if not got:
        return 2
    tb, proc = got
    try:
        await tb.ev(JS_MSGS)

        # ---- H1 点击入口 → 等待态可见 ----
        await tb.ev("document.querySelector('#tb-explain-btn').click();true")
        await asyncio.sleep(0.35)      # 作业在后台线程，stub 睡 1.2s → 此刻必须还在 generating
        st = await tb.ev(JS_MASK_STATE)
        step(st["open"] and "正在生成" in st["bodyText"] and not st["hasIframe"],
             "H1 点击后弹窗立即打开并显示等待态（后台作业，不卡页面）", str(st))
        await tb.shot("p11_wait.png")

        # ---- H2 done → sandboxed iframe 渲染 ----
        st2 = await wait_iframe(tb)
        step(bool(st2 and st2["hasIframe"]), "H2a 作业完成后弹窗内出现原理图 iframe", str(st2))
        has_sandbox = await tb.ev(
            "(()=>{const f=document.querySelector('#tb-explain-body iframe');"
            "return f ? f.getAttribute('sandbox') : null})()")
        step(has_sandbox == "allow-scripts",
             "H2b iframe 走 sandbox=allow-scripts（安全边界与微课实验页同口径）", str(has_sandbox))
        await asyncio.sleep(1.2)       # 等 iframe 首帧 postMessage 到达
        n_load = await tb.ev("window.__hxMsgs.length")
        step(n_load >= 1, "H2c 沙箱内脚本已执行（load 时向父页报步骤）", f"msgs={n_load}")
        await tb.shot("p11_explain_done.png")

        # ---- H3 iframe 内真点击 → 交互推进 ----
        pos = await tb.ev(JS_IFRAME_RECT)
        step(pos is not None, "取到 iframe 中心坐标", str(pos))
        if not pos:
            return 2
        for etype in ("mousePressed", "mouseReleased"):
            await tb.send("Input.dispatchMouseEvent", type=etype,
                          x=int(pos["x"]), y=int(pos["y"]),
                          button="left", clickCount=1)
        await asyncio.sleep(1.0)
        n_click = await tb.ev("window.__hxMsgs.length")
        last = await tb.ev("window.__hxMsgs[__hxMsgs.length-1]")
        step(n_click >= n_load + 1 and last == 1,
             "H3 真点击画面推进到第 2 步（沙箱交互是活的）", f"before={n_load} after={n_click} step={last}")
        await tb.shot("p11_explain_step2.png")

        # ---- H4 关窗再开 → 秒回缓存，不双扣分 ----
        await tb.ev("document.querySelector('#tb-explain-close').click();true")
        await asyncio.sleep(0.4)
        calls_before = len(_stub_state["calls"])
        await tb.ev("document.querySelector('#tb-explain-btn').click();true")
        await asyncio.sleep(0.6)
        st4 = await tb.ev(JS_MASK_STATE)
        calls_after = len(_stub_state["calls"])
        step(st4["open"] and st4["hasIframe"] and calls_after == calls_before,
             "H4 重开弹窗直接展示缓存结果，未再次调用模型（不双扣分）",
             f"calls={calls_before}->{calls_after}")

        # ---- H5 重新生成 + 模型返回脏内容 → 失败反馈在弹窗内 ----
        _stub_state["mode"] = "garbage"
        await tb.ev("document.querySelector('#tb-explain-again').click();true")
        deadline = time.time() + 20
        st5 = {"bodyText": ""}
        while time.time() < deadline:
            st5 = await tb.ev(JS_MASK_STATE)
            if st5["open"] and "生成失败" in st5["bodyText"]:
                break
            await asyncio.sleep(0.4)
        step("生成失败" in st5["bodyText"],
             "H5 重新生成遇脏输出：弹窗内给出失败提示（终态必有反馈）", st5["bodyText"])
        await tb.shot("p11_explain_fail.png")
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
    except BaseException as e:
        import traceback
        traceback.print_exc()
        fails.append("uncaught: " + repr(e)[:160])
    finally:
        verdict = ("ALL PASS" if not fails and code == 0
                   else ("FAIL(" + str(len(fails)) + "): " + " | ".join(fails)
                         if fails else "EARLY EXIT code=" + str(code)))
        print("\n==== P11 CDP(原理图入口): " + verdict + " ====")
        sys.exit(0 if not fails and code == 0 else 2)
