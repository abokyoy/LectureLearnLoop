"""
P8 黑板两段式版式 CDP 取证（v0.2.2 阶段五，2026-11-05）。

链路是真的，不往内存塞桩：
  进程内假小智云 -> 真 MCP 桥 -> board_write / board_draw / board_highlight 工具上板；
  字幕走真 HTTP /api/board/speech（与 EXE 上报同一条路），图被顶走时闭窗烧讲稿；
  页面用 headless Edge/Chrome（CDP）打开，逐条断言版式行为并截图存档。

覆盖计划里点名的 UI 口径：页面本身不滚动、当前句贴底、上滑脱钩与「回到最新」、
新图置顶且旧图下沉变暗、卡片并入字幕流、冷图折叠与点开放大、拖拽分隔条、
真机模式提示、备课弹窗、课件抽屉与 PDF/PPTX 导出。

运行：python server/tests/p8_board_cdp.py
产物：server/tests/fixtures/p8_board_*.png
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

sys.stdout.reconfigure(encoding="utf-8", errors="replace") if hasattr(sys.stdout, "reconfigure") else None

HERE = Path(__file__).resolve().parent            # server/tests
SERVER = HERE.parent                              # server
FIX = HERE / "fixtures"
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(HERE))

import config                                      # noqa: E402
from app import create_app                         # noqa: E402
from services import mcp_bridge as MB              # noqa: E402
from services import xz_device as XD               # noqa: E402
from test_xz_teacher_board import FakeCloud        # noqa: E402

APP = create_app()
USER = "p8cdp_" + uuid.uuid4().hex[:6]
PWD = "test123456"

# 讲课脚本：覆盖 DSL 全部图型（函数/切线/单位圆/极坐标/箱体/柱状/桑基/树/时间轴/几何）。
# 张数必须多过前端的 PLOT_LIVE_MAX（8），取证才拍得到「冷图折叠 + 点冷行放大」这条真路径。
CARDS = [
    ("topic", "重要极限一"),
    ("step", "夹逼：cos x ≤ sin x / x ≤ 1"),
    ("formula", "\\lim_{x\\to 0}\\frac{\\sin x}{x}=1"),
    ("step", "取倒数后夹出极限为 1"),
]
SENTENCES = [
    ("teacher", "同学们看这道题：求 lim(x→0) sin x / x。"),
    ("teacher", "先把 sin x 和 x 两条曲线画出来，就在同一张图上。"),
    ("student", "老师，两条线在原点附近是不是重合了？"),
    ("teacher", "对，就是这个「贴得越来越近」——夹逼准则要用的正是它。"),
    ("teacher", "我把 0 附近这一条带子涂上阴影，注意上界是 sin x，下界是 x。"),
    ("teacher", "再在 x=1 处画一条切线，斜率是 cos 1，这就是导数的几何意义。"),
    ("student", "那这个阴影面积和极限有什么关系？"),
    ("teacher", "别急，面积是下一问；先看极限：两边同除 sin x，取倒数就夹出结论。"),
    ("teacher", "换成单位圆来看更直观：正弦线、余弦线、正切线三段长度就是不等式。"),
    ("teacher", "角度取 30 度和 120 度两个例子，第二象限的符号别忘了变。"),
    ("student", "明白了，圆上三条线一比就出来。"),
    ("teacher", "最后换个统计视角：把班上四次测验的分数做箱体图，看离散程度。"),
    ("teacher", "再看知识点之间的联系，用桑基图把得分流向画出来。"),
    ("teacher", "这一节的脉络就是一条时间轴：从夹逼到导数到统计。"),
    ("student", "老师，课件能导出吗？我想课后复习。"),
    ("teacher", "下课我点一下导出，PDF 和 PPTX 都存在课件目录里。"),
]
PLOTS = [
    ("sin x 与 x", {"plot_type": "function",
                    "curves": [{"expr": "sin(x)", "name": "sin x"}, {"expr": "x", "name": "x"}],
                    "x_range": [-1.5, 1.5],
                    "shades": [{"x_from": 0, "x_to": 1, "label": "夹区"}]}),
    ("x=1 处切线", {"plot_type": "function",
                    "curves": [{"expr": "sin(x)", "name": "sin x"}], "x_range": [-1.5, 2.5],
                    "tangents": [{"curve": 0, "x": 1, "label": "切点"}]}),
    ("单位圆三角函数线", {"plot_type": "unitcircle",
                          "angles": [30, {"deg": 120, "label": "二象"}],
                          "show": ["sin", "cos", "tan"]}),
    ("心形线", {"plot_type": "polar", "curves": [{"expr": "1+cos(x)", "name": "心形"}],
                "theta_range": [0, 360]}),
    ("四次测验分布", {"plot_type": "stats", "shape": "box",
                      "series": [{"name": "甲班", "values": [62, 71, 78, 85, 90, 96]},
                                 {"name": "乙班", "values": [55, 66, 72, 80, 88, 99]}]}),
    ("知识流向", {"plot_type": "diagram", "shape": "sankey", "links": [
        {"from": "极限", "to": "导数", "value": 6}, {"from": "极限", "to": "积分", "value": 4},
        {"from": "导数", "to": "单调性", "value": 3}, {"from": "导数", "to": "切线", "value": 3}]}),
    ("本章脉络", {"plot_type": "timeline", "events": [
        {"t": 1, "label": "夹逼准则"}, {"t": 2, "label": "两个重要极限"},
        {"t": 3, "label": "导数定义", "note": "切线"}, {"t": 4, "label": "统计图示"}]}),
    ("三角形与外接圆", {"plot_type": "geometry",
                        "points": [{"x": 0, "y": 0, "label": "O"}, {"x": 3, "y": 0, "label": "A"},
                                   {"x": 1, "y": 2.5, "label": "B"}],
                        "segments": [{"a": "O", "b": "A"}, {"a": "A", "b": "B"}, {"a": "B", "b": "O"}],
                        "circles": [{"center": "O", "r": 2}]}),
    ("cos x 与 sin x", {"plot_type": "function",
                        "curves": [{"expr": "cos(x)", "name": "cos x"}, {"expr": "sin(x)", "name": "sin x"}],
                        "x_range": [0, 6.3]}),
    ("曲边梯形面积", {"plot_type": "function",
                      "curves": [{"expr": "x*x", "name": "x^2"}], "x_range": [0, 2],
                      "shades": [{"x_from": 0, "x_to": 2, "label": "曲边梯形"}]}),
    ("测验得分对比", {"plot_type": "stats", "shape": "bar",
                      "categories": ["一次", "二次", "三次", "四次"],
                      "series": [{"name": "甲班", "values": [62, 71, 78, 90]},
                                 {"name": "乙班", "values": [55, 66, 80, 88]}]}),
    ("导数学科树", {"plot_type": "diagram", "shape": "tree", "nodes": [
        {"id": "r", "text": "导数"},
        {"id": "a", "text": "定义", "parent": "r"},
        {"id": "a1", "text": "极限", "parent": "a"},
        {"id": "a2", "text": "切线", "parent": "a"},
        {"id": "b", "text": "运算", "parent": "r"},
        {"id": "b1", "text": "四则", "parent": "b"},
        {"id": "b2", "text": "复合", "parent": "b"},
        {"id": "c", "text": "应用", "parent": "r"},
        {"id": "c1", "text": "单调性", "parent": "c"}]}),
]

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


# ---------------------------------------------------------------- 服务端 + 讲课
def start_server(port):
    t = __import__("threading").Thread(
        target=lambda: APP.run(host="127.0.0.1", port=port, threaded=True, debug=False,
                               use_reloader=False),
        daemon=True, name="p8-server")
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


def teach(base, tok, cloud):
    """按真实节奏上完这节课：卡片上板 -> 字幕/画图交替 -> 指认，全部走真链路。"""
    h = {"Authorization": "Bearer " + tok}
    for kind, text in CARDS:
        cloud.call_tool("board_write", {"content": text, "kind": kind})
    ri = 0
    for pi, (title, spec) in enumerate(PLOTS):
        for _ in range(2):
            if ri < len(SENTENCES):
                role, text = SENTENCES[ri]
                ri += 1
                requests.post(base + "/api/board/speech",
                              json={"role": role, "text": text, "ts": int(time.time() * 1000)},
                              headers=h, timeout=6)
        cloud.call_tool("board_draw", {"title": title, "spec": spec})
        requests.post(base + "/api/board/speech",
                      json={"role": "teacher", "text": f"「{title}」这张图只看两件事：形状和关键点。",
                            "ts": int(time.time() * 1000)}, headers=h, timeout=6)
    while ri < len(SENTENCES):
        role, text = SENTENCES[ri]
        ri += 1
        requests.post(base + "/api/board/speech",
                      json={"role": role, "text": text, "ts": int(time.time() * 1000)},
                      headers=h, timeout=6)
    st = requests.get(base + "/api/board/state", headers=h, timeout=6).json()["data"]
    last_plot = [i for i in st["items"] if i["kind"] == "plot"][-1]
    cloud.call_tool("board_highlight", {"item_id": last_plot["id"]})
    return st


def say_more(base, tok, n=3):
    """脱钩期间继续来的口播字幕（真 HTTP 上报），用来验「不抢底」。"""
    h = {"Authorization": "Bearer " + tok}
    for k in range(n):
        requests.post(base + "/api/board/speech",
                      json={"role": "teacher", "text": f"脱钩期间新到的一句字幕 {k+1}",
                            "ts": int(time.time() * 1000)}, headers=h, timeout=6)


# ---------------------------------------------------------------- CDP 断言
async def run_cdp(base, tok, cdp_port, profile):
    """起 headless 浏览器并把黑板页开起来；返回 (Tab, proc)，Tab 由调用方负责关闭。"""
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
    # 真机上课的入口在 EXE preload 上（window.xzVoice）：这里按 preload 的口径注入同款桩，
    # 让「用真机小智」这条退化路径能在浏览器里被拍到（设备绑定已在库里置为真实 ESP32）。
    init = ("try{localStorage.setItem('ll_token', %s);localStorage.setItem('xz_voice_mode','hw');}catch(e){}"
            "window.xzVoice={openPanel:function(){},openAndStart:function(){},onState:function(){}};"
            % json.dumps(tok)) + "true"
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
            if await tb.ev("!!document.querySelector('#tb-stream') && "
                           "document.querySelectorAll('#tb-plots .tb-plotrow').length > 0"):
                booted = True
                break
        except RuntimeError:
            pass
        await asyncio.sleep(0.5)
    step(booted, "黑板页已开到有图有字幕的活页面")
    if not booted:
        await tb.__aexit__()
        proc.terminate()
        return None
    await asyncio.sleep(2.0)
    return tb, proc


JS_SNAPSHOT = """(() => {
  const q = s => document.querySelector(s);
  const st = q('#tb-stream'), host = q('#tb-plots');
  const rows = [...host.querySelectorAll('.tb-plotrow')];
  const live = rows.filter(e => e.querySelector('canvas'));
  const cold = rows.filter(e => !e.querySelector('canvas'));
  return {
    noPageScroll: document.documentElement.scrollHeight <= document.documentElement.clientHeight + 2,
    pollErr: window.__tbPollErr || null,
    streamGap: Math.round(st.scrollHeight - st.scrollTop - st.clientHeight),
    cardRows: st.querySelectorAll('.tb-card').length,
    sayRows: st.querySelectorAll('.tb-say').length,
    plotRows: rows.length,
    firstIsNewest: rows.length ? (rows[0].getAttribute('data-plot') === "%s") : false,
    secondDim: rows.length > 1 ? rows[1].className.includes('tb-dim') : true,
    liveCount: live.length,
    coldText: cold.length ? cold[0].textContent.replace(/\\s+/g, '').slice(0, 24) : '',
    plotCount: q('#tb-plot-count').textContent,
    banner: (q('#tb-banner') || {}).textContent || '',
    subFlex: q('#tb-zone-sub').style.flex,
    hintHidden: q('#tb-sub-hint').classList.contains('hidden'),
    backHidden: q('#tb-back-btn').classList.contains('hidden')
  };
})()"""


async def main() -> int:
    FIX.mkdir(parents=True, exist_ok=True)
    srv_port, cdp_port = free_port(), free_port()
    base = start_server(srv_port)
    tok, uid = make_user(base)
    step(True, "取证账号已注册", f"{USER} uid={uid}")

    # 真机路径前置：把该账号的绑定置成「已绑定的真实 ESP32」（不打小智云，只落库）
    XD._upsert(uid, "real", "AA:BB:CC:DD:EE:FF", "p8-" + uuid.uuid4().hex[:8], "bound", "")
    st0 = requests.get(base + "/api/board/xzdevice/status", headers={"Authorization": "Bearer " + tok},
                       timeout=6).json()["data"]
    step(bool(st0.get("bound")) and st0.get("dev_type") == "real", "取证账号已绑真实小智", str(st0)[:120])

    MB._db_get = lambda key: ""            # 不碰共享库里的真实接入点
    MB.RETRY_S = 1
    cloud = FakeCloud()
    cloud.start()
    MB._spawn(f"ws://127.0.0.1:{cloud.port}/mcp", USER)
    step(cloud.wait_bridge(timeout=60), "MCP 桥已连上假小智云")
    if not cloud.wait_bridge(timeout=1):
        return 2

    state = teach(base, tok, cloud)
    plots = [i for i in state["items"] if i["kind"] == "plot"]
    newest_id = str(plots[-1]["id"])
    step(len(plots) == len(PLOTS), "全部图经真工具链上板（任何一张被 DSL 拒收都会在这里红）",
         f"plots={len(plots)}/{len(PLOTS)} newest={newest_id}")

    profile = Path(__file__).resolve().parent / f"_p8_profile_{uuid.uuid4().hex[:6]}"
    got = await run_cdp(base, tok, cdp_port, profile)
    if not got:
        return 2
    tb, proc = got

    snap = await tb.ev(JS_SNAPSHOT % newest_id)
    print("SNAPSHOT:", json.dumps(snap, ensure_ascii=False))
    step(snap["pollErr"] is None, "轮询无异常（页面在持续刷新）", snap["pollErr"])
    step(snap["noPageScroll"], "页面本身不整页滚动")
    step(snap["streamGap"] <= 24, "当前句贴在区底", f"gap={snap['streamGap']}")
    step(snap["cardRows"] >= 4 and snap["sayRows"] >= 16, "板书卡片与字幕同流",
         f"cards={snap['cardRows']} say={snap['sayRows']}")
    step(snap["firstIsNewest"] and snap["secondDim"], "新图置顶、旧图下沉变暗",
         f"rows={snap['plotRows']} first={newest_id}")
    step(snap["liveCount"] <= 8 and snap["plotRows"] > 8 and "点开看图" in snap["coldText"],
         "冷图折叠、实例数封顶", f"live={snap['liveCount']} rows={snap['plotRows']} cold={snap['coldText']}")
    step("张图" in snap["plotCount"], "图区计数文案完整", snap["plotCount"])
    await tb.shot("p8_board_two_zone.png")

    # 冷图点开放大（同一 tick 断言，避免被下一次轮询打断）
    exp = await tb.ev("""(() => {
      const host = document.querySelector('#tb-plots');
      const cold = [...host.querySelectorAll('.tb-plotrow')].find(e => !e.querySelector('canvas'));
      if (!cold) return {skip: 'no cold row'};
      const id = cold.getAttribute('data-plot');
      cold.click();
      const now = [...host.querySelectorAll('.tb-plotrow')].find(e => e.getAttribute('data-plot') === id);
      return {id, dim: now.className.includes('tb-dim'), canvas: !!now.querySelector('canvas'),
              h: Math.round(now.getBoundingClientRect().height), btn: now.querySelector('button').textContent,
              live: host.querySelectorAll('canvas').length};
    })()""")
    step(bool(exp.get("canvas")) and not exp.get("dim") and exp.get("btn") == "收起",
         "点冷行即放大成大图", str(exp))
    await asyncio.sleep(1.6)
    if exp.get("skip"):
        step(False, "取证环境里存在冷行（图数必须多于 PLOT_LIVE_MAX）", str(exp))
    else:
        held = await tb.ev("""(() => { const r = [...document.querySelectorAll('.tb-plotrow')]
          .find(e => e.getAttribute('data-plot') === %s); return r ? !r.className.includes('tb-dim') : null; })()"""
            % json.dumps(str(exp["id"])))
        step(held is True, "放大态在下一次轮询后仍保持", f"id={exp.get('id')}")
    await tb.shot("p8_board_expand.png")

    # 上滑脱钩：新字幕不得抢底，且要抬起「回到最新」
    say_more(base, tok, 3)
    await tb.ev("""(() => { const s = document.querySelector('#tb-stream');
      s.scrollTop = Math.max(0, s.scrollHeight - s.clientHeight - 260); s.dispatchEvent(new Event('scroll')); })()""")
    await asyncio.sleep(0.6)
    say_more(base, tok, 3)
    await asyncio.sleep(2.4)
    det = await tb.ev("""(() => { const s = document.querySelector('#tb-stream');
      return {gap: Math.round(s.scrollHeight - s.scrollTop - s.clientHeight),
              back: !document.querySelector('#tb-back-btn').classList.contains('hidden')}; })()""")
    step(det["gap"] > 40 and det["back"], "上滑脱钩后新字幕不抢底、按钮抬起", str(det))
    await tb.shot("p8_board_detached.png")
    await tb.ev("document.querySelector('#tb-back-btn').click()")
    await asyncio.sleep(0.8)
    re = await tb.ev("""(() => { const s = document.querySelector('#tb-stream');
      return {gap: Math.round(s.scrollHeight - s.scrollTop - s.clientHeight),
              back: !document.querySelector('#tb-back-btn').classList.contains('hidden')}; })()""")
    step(re["gap"] <= 24 and not re["back"], "点「回到最新」重新贴底", str(re))

    # 拖拽分隔条（38 -> 55 -> 双击复位）
    drag = await tb.ev("""(() => { const dv = document.querySelector('#tb-divider'), wrap = document.querySelector('#tb-split');
      const b = wrap.getBoundingClientRect();
      const y = b.top + 0.55 * b.height;
      dv.dispatchEvent(new MouseEvent('mousedown', {bubbles: true, clientY: y}));
      document.dispatchEvent(new MouseEvent('mousemove', {bubbles: true, clientY: y}));
      document.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
      const got = document.querySelector('#tb-zone-sub').style.flex;
      const stored = localStorage.getItem('tb_split_ratio');
      dv.dispatchEvent(new MouseEvent('dblclick', {bubbles: true}));
      return {got, stored, reset: document.querySelector('#tb-zone-sub').style.flex}; })()""")
    got_pct = int(drag["got"].rstrip("%").split()[-1])
    step(53 <= got_pct <= 58 and drag["stored"] == str(got_pct) and drag["reset"] == "0 0 38%",
         "分隔条可拖、比例入库、双击复位", str(drag))

    # 真机模式提示（EXE preload 桩 + 已绑真实 ESP32）；pref=hw 要等一次状态接口往返才 repaint
    await tb.ev("document.querySelector('#tb-voice-btn').click()")
    await asyncio.sleep(1.5)
    hw = await tb.ev("""(() => {
      return {hidden: document.querySelector('#tb-sub-hint').classList.contains('hidden'),
              text: document.querySelector('#tb-sub-hint').textContent,
              voice: document.querySelector('#tb-voice-btn').textContent}; })()""")
    step(hw["hidden"] is False and "真机" in hw["text"] and hw["voice"] != "开始上课",
         "真机模式区顶提示「无口播字幕，课件只存图」", str(hw))
    await tb.shot("p8_board_hwmode.png")

    # 备课弹窗：三入口 + 自写主题 + 积分预估 + 取消
    prep = await tb.ev("""(() => { const q = s => document.querySelector(s);
      q('#tb-prep-btn').click();
      const tabs = [...q('#tb-prep-tabs').children];
      tabs[2].click();
      return {open: !q('#tb-prep-mask').classList.contains('hidden'), title: q('#tb-prep-title').textContent,
              tabs: tabs.map(b => b.textContent), freeHidden: q('#tb-prep-freebox').classList.contains('hidden'),
              ph: q('#tb-prep-free').placeholder}; })()""")
    step(prep["open"] and len(prep["tabs"]) == 3 and prep["freeHidden"] is False,
         "备课弹窗：知识点/错题/自写主题三入口", str(prep))
    await asyncio.sleep(1.2)
    cost = await tb.ev("document.querySelector('#tb-prep-cost').textContent")
    step("积分" in (cost or ""), "备课显示积分预估", cost)
    await tb.shot("p8_board_prep.png")
    await tb.ev("document.querySelector('#tb-prep-cancel').click()")

    # 课件抽屉：已归档页 + 缩略图 + 讲稿 + 导出 PDF/PPTX
    # 先把页面里的归档待办排空（图被顶走才烧 PNG 上传，这步走真链路）
    lkey = state.get("lesson_key") or ""
    pages, deadline = 0, time.time() + 240
    hh = {"Authorization": "Bearer " + tok}
    while time.time() < deadline:
        d = requests.get(base + "/api/board/lesson", headers=hh, timeout=6).json()["data"]
        pages = len(d.get("slides") or [])
        if pages >= len(PLOTS) - 1:
            break
        await asyncio.sleep(2)
    step(pages >= len(PLOTS) - 1, "图被顶走时已自动烧成课件页", f"pages={pages} lesson={lkey[:12]}")
    dr = await tb.ev("""(() => { document.querySelector('#tb-lesson-btn').click();
      const b = document.querySelector('#tb-drawer-body');
      return {open: !document.querySelector('#tb-drawer-mask').classList.contains('hidden'),
              sub: document.querySelector('#tb-drawer-sub').textContent, cards: b.children.length}; })()""")
    await asyncio.sleep(1.5)
    dr2 = await tb.ev("""(() => ({sub: document.querySelector('#tb-drawer-sub').textContent,
      cards: document.querySelector('#tb-drawer-body').children.length}))()""")
    step(dr["open"] and dr2["cards"] >= 5, "课件抽屉列出已归档页", f"{dr} {dr2}")
    await asyncio.sleep(2.0)
    # 缩略图是 loading="lazy"（产品行为：抽屉里滚到哪-load 到哪），所以必须真滚一滚才会加载
    imgs = await tb.ev("""(async () => { const box = document.querySelector('#tb-drawer-body');
      for (let y = 0; y <= box.scrollHeight; y += 260) { box.scrollTop = y; await new Promise(r => setTimeout(r, 70)); }
      box.scrollTop = 0; await new Promise(r => setTimeout(r, 1500));
      const im = [...box.querySelectorAll('img')];
      return {n: im.length, loaded: im.filter(i => i.naturalWidth > 0).length,
              w: im[0] ? im[0].naturalWidth : 0, h: im[0] ? im[0].naturalHeight : 0,
              cap: (box.textContent.match(/\u8bb2\u7a3f\uff1a[^]{0,30}/) || [''])[0]}; })()""", promise=True)
    step(imgs["loaded"] >= 5 and imgs["w"] == 1280 and "讲稿" in imgs["cap"],
         "归档 PNG 可显示且带烧进去的讲稿", str(imgs))
    await tb.shot("p8_board_drawer.png")

    for fmt in ("pdf", "pptx"):
        await tb.ev(f"document.querySelector('#tb-exp-{fmt}').click()")
        status, deadline = "", time.time() + 90
        while time.time() < deadline:
            await asyncio.sleep(2)
            status = await tb.ev("document.querySelector('#tb-drawer-status').textContent")
            if "已导出" in (status or "") or "失败" in (status or ""):
                break
        step("已导出" in status, f"导出 {fmt.upper()} 成功", status)
        files = list((config.VAULT_DIR / uid / "课件").rglob("*." + fmt))
        step(files and files[0].stat().st_size > 50000, f"{fmt.upper()} 落盘可查",
             f"{files[0].name} {files[0].stat().st_size} bytes" if files else "无文件")
        await tb.ev("document.querySelector('#tb-drawer-status').textContent = ''")

    # 下课归档：擦板前收课，确认课程与页都在库里
    st = requests.get(base + "/api/board/state", headers={"Authorization": "Bearer " + tok},
                      timeout=6).json()["data"]
    step(bool(st.get("lesson_key")), "本课 lesson_key 在 state 中带出", str(st.get("lesson_key"))[:40])
    closed = [i for i in st["items"] if i["kind"] == "plot"][:-1]   # 最后一张还挂着，未闭窗
    step(bool(closed) and all(i.get("caption") for i in closed),
         "被顶走的每一张图都闭上了讲稿（caption）",
         f"closed={len(closed)} missing={[i['id'] for i in closed if not i.get('caption')]}")

    await tb.send("Page.navigate", url="about:blank")
    await tb.__aexit__()
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
    shutil.rmtree(profile, ignore_errors=True)
    return 0


if __name__ == "__main__":
    code = 1
    try:
        code = asyncio.run(main())
    finally:
        print("\n==== P8 CDP(黑板两段式): " + ("ALL PASS" if not fails else f"FAIL({len(fails)}): " + " | ".join(fails)) + " ====")
        sys.exit(code if not fails else 2)
