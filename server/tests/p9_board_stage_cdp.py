"""
P9 黑板五期「主板书分支树 + 历史带」CDP 取证（2026-11-04）。

链路是真的，不往内存塞桩：
  进程内假小智云 -> 真 MCP 桥 -> board_show_problem / board_write / board_draw /
  board_highlight 工具上板（题17/题18 两道种子错题 = 两个枝根）；
  字幕走真 HTTP /api/board/speech（师/生两条角色）；
  headless Edge/Chrome（CDP）打开页面，逐条断言五期版式行为并截图存档。

覆盖五期 + v0.2.6 双栏口径：
  A 下区任何时候不空（开课前欢迎行）；
  B 题目上板分开成枝：左栏=当前 topic 分支文字流（根通栏+题卡+步骤+图 chalk 行），
    右栏画幅=当下正在讲的图（PPT 式停留），历史带可点旧枝回看、点旧图指哪换哪；
  C 左栏冷行「放大」=钉住该图进右栏，分支树不破；新图/新枝自动接管右栏；
  D live ECharts 实例闸：左栏零 live，右栏恒 <=1，右栏+历史带总数 <= PLOT_LIVE_MAX；
  E 〔锚点〕point 指认在左栏点亮（tb-anc-on + 激光 + tb-focus 双区）；
    v0.2.7 系列指认 E2：散点 point=1 指整组（回文带系列名+激光落重心+高亮不炸图）；
  F 上区字幕贴底 + 分隔条拖拽回归；
  G 换题闭窗归档：当前课课件页 >= 换题后图数-1，抽屉 PNG 可读且带讲稿。
  另：写题返回的建议图型行（_suggest_plot）在真链路上可见。

运行：python server/tests/p9_board_stage_cdp.py
产物：server/tests/fixtures/p9_stage_*.png
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
from knowledge_management import DatabaseManager   # noqa: E402
from services import mcp_bridge as MB              # noqa: E402
from test_xz_teacher_board import FakeCloud        # noqa: E402

APP = create_app()
USER = "p9cdp_" + uuid.uuid4().hex[:6]
PWD = "test123456"

STEM17 = "题17：lim(n→∞) (1+1/n)^n 的值是（）"
STEM18 = "题18：二次函数 y=x^2-2x 的图象开口方向与顶点坐标"

SENTENCES = [
    ("teacher", "先看第17题，重要极限二，别背答案，我们把它夹出来。"),
    ("student", "老师，这个通项是越来越大的吗？"),
    ("teacher", "对，单调递增又有上界，极限就存在。"),
    ("teacher", "把前几项画出来感受一下收敛的趋势。"),
    ("teacher", "再用单位圆看三角函数线，角度取两个象限的例子。"),
    ("teacher", "心形线是极坐标里的常客，形状记牢。"),
    ("student", "这些图和第17题有什么关系？"),
    ("teacher", "都是工具：箱线图看分布，桑基图看流向。"),
    ("teacher", "下面换第18题，二次函数配方，图象一画就明白。"),
    ("teacher", "开口方向看二次项系数，顶点用配方法。"),
    ("student", "顶点是 (1,-1) 吗？"),
    ("teacher", "对，我把抛物线画出来，阴影是曲边梯形面积。"),
    ("teacher", "再对比 cos 与 sin 两条曲线在同一坐标系里的样子。"),
    ("teacher", "数轴上把解集区间标出来，注意端点开闭。"),
    ("teacher", "最后用条形图对比四次测验得分，时间轴回顾本章脉络。"),
    ("teacher", "散点这张图记住：颜色就是分组，图上标了哪个点带标签。"),
    ("student", "老师，课件能导出吗？"),
]

PLOTS = [
    ("前几项趋势", {"plot_type": "function",
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
    # ---- 以下 8 张属题18枝（换题后当前课），取证拍冷置与归档 ----
    ("四次测验分布", {"plot_type": "stats", "shape": "box",
                      "series": [{"name": "甲班", "values": [62, 71, 78, 85, 90, 96]},
                                 {"name": "乙班", "values": [55, 66, 72, 80, 88, 99]}]}),
    ("抛物线 y=x^2-2x", {"plot_type": "function",
                         "curves": [{"expr": "x*x-2*x", "name": "x^2-2x"}], "x_range": [-1, 3]}),
    ("曲边梯形面积", {"plot_type": "function",
                      "curves": [{"expr": "x*x", "name": "x^2"}], "x_range": [0, 2],
                      "shades": [{"x_from": 0, "x_to": 2, "label": "曲边梯形"}]}),
    ("cos 与 sin 对比", {"plot_type": "function",
                         "curves": [{"expr": "cos(x)", "name": "cos x"}, {"expr": "sin(x)", "name": "sin x"}],
                         "x_range": [0, 6.3]}),
    ("知识流向", {"plot_type": "diagram", "shape": "sankey", "links": [
        {"from": "极限", "to": "导数", "value": 6}, {"from": "极限", "to": "积分", "value": 4},
        {"from": "导数", "to": "单调性", "value": 3}, {"from": "导数", "to": "切线", "value": 3}]}),
    ("解集数轴", {"plot_type": "numberline",
                  "intervals": [{"from": 1, "to": 3, "label": "解集"}]}),
    ("本章脉络时间轴", {"plot_type": "timeline", "events": [
        {"t": 1, "label": "夹逼准则"}, {"t": 2, "label": "两个重要极限"},
        {"t": 3, "label": "导数定义", "note": "切线"}, {"t": 4, "label": "统计图示"}]}),
    # v0.2.7 散点标注纪律种子图（监督/无监督事故复刻）：双系列真名+每系列真标注，
    # marks 前两位是系列级，供 E2 段系列指认取证（须保持全列表最后一张）
    ("监督对比无监督散点", {"plot_type": "stats", "shape": "scatter", "series": [
        {"name": "监督学习", "points": [
            {"x": 1, "y": 2, "label": "分类A"}, {"x": 2, "y": 3, "label": "分类B"},
            [1.6, 2.6]]},
        {"name": "无监督学习", "points": [
            {"x": 4, "y": 1, "label": "自己聚成堆"}, [4.6, 1.5], [5.2, 0.8]]}]}),
]
N_T1, N_T2 = 4, len(PLOTS) - 4           # 题17枝 4 张 / 题18枝 8 张

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
        daemon=True, name="p9-server")
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


def seed_errors(uid):
    """两道种子错题（题17/题18），走与 pytest 同款三连 INSERT，供真链路写题。"""
    subj = "取证学科P9" + uuid.uuid4().hex[:6]
    db = DatabaseManager(str(config.DB_PATH))
    conn = db.get_connection()
    cur = conn.execute(
        "INSERT INTO knowledge_points (user_id, subject_name, point_name, "
        "core_description, mastery_score) VALUES (?, ?, ?, ?, ?) RETURNING id",
        (uid, subj, "重要极限", "数列与函数极限", 40))
    kp = cur.fetchone()[0]
    ids = []
    for stem, opts, ans, expl in (
        (STEM17, ["1", "e", "∞", "0"], "B", "重要极限二 (1+1/n)^n→e"),
        (STEM18, ["向上 (1,1)", "向上 (1,-1)", "向下 (-1,-1)", "向下 (0,0)"],
         "B", "配方法 y=(x-1)^2-1，开口向上"),
    ):
        cur = conn.execute(
            "INSERT INTO practice_records (user_id, subject_name, knowledge_point_id, "
            "question_content, user_answer, is_correct, options_json) "
            "VALUES (?, ?, ?, ?, ?, 0, ?) RETURNING id",
            (uid, subj, kp, stem, "A", json.dumps(opts, ensure_ascii=False)))
        pr = cur.fetchone()[0]
        cur = conn.execute(
            "INSERT INTO error_questions (user_id, subject_name, knowledge_point_id, "
            "practice_record_id, current_proficiency, correct_answer, explanation) "
            "VALUES (?, ?, ?, ?, 20, ?, ?) RETURNING id",
            (uid, subj, kp, pr, ans, expl))
        ids.append(cur.fetchone()[0])
    conn.commit()
    return ids[0], ids[1]


def say(base, tok, role, text):
    requests.post(base + "/api/board/speech",
                  json={"role": role, "text": text, "ts": int(time.time() * 1000)},
                  headers={"Authorization": "Bearer " + tok}, timeout=6)


def teach(base, tok, cloud, err17, err18):
    """两题两枝按真实节奏上完：写题(自动枝根+题干+选项) -> 卡 -> 字幕/画图交替。
    返回题18 写工具的回文本（题干含「函数/图象」，应命中 _suggest_plot 建议行）。"""
    cloud.call_tool("board_show_problem", {"error_id": str(err17)})
    r18 = ""
    si = 0
    for pi, (title, spec) in enumerate(PLOTS):
        for _ in range(2):
            if si < len(SENTENCES):
                role, text = SENTENCES[si]
                si += 1
                say(base, tok, role, text)
        if pi == N_T1:      # 换题=开新枝（题18）：服务端自动换课键
            r18 = cloud.call_tool("board_show_problem", {"error_id": str(err18)})
            cloud.call_tool("board_write", {"content": "配方看〔开口方向〕与〔顶点坐标〕", "kind": "step"})
        if pi == 1:
            cloud.call_tool("board_write", {"content": "先确认通项〔单调递增〕且有上界", "kind": "step"})
        if pi == N_T1 + 1:
            cloud.call_tool("board_write", {"content": "y=(x-1)^2-1", "kind": "formula"})
        cloud.call_tool("board_draw", {"title": title, "spec": spec})
        say(base, tok, "teacher", f"「{title}」这张图只看两件事：形状和关键点。")
    while si < len(SENTENCES):
        role, text = SENTENCES[si]
        si += 1
        say(base, tok, role, text)
    return r18


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
                           "!!document.querySelector('#tb-timeline')"):
                booted = True
                break
        except RuntimeError:
            pass
        await asyncio.sleep(0.5)
    step(booted, "黑板页已打开（五期结构 #tb-board + #tb-timeline 就位）")
    if not booted:
        await tb.__aexit__()
        proc.terminate()
        return None
    await asyncio.sleep(2.0)
    return tb, proc


JS_STAGE = """(() => {
  const q = s => document.querySelector(s), qa = s => [...document.querySelectorAll(s)];
  const board = q('#tb-board'), band = q('#tb-timeline'), st = q('#tb-stream');
  const plotRows = qa('#tb-board .tb-kind-plot');
  const cold = plotRows.filter(e => !e.querySelector('canvas'));
  // 像素门（2026-11-06 白板事故）：数容器 .tbc-wrap 不能证明画布有内容——
  // detached 容器 init 出 0×0 canvas，容器照样在。必须实测 canvas 尺寸+亮色墨迹。
  const inkOf = (cv) => {
    if (!cv || !cv.width) return -1;
    try {
      const c = document.createElement('canvas');
      c.width = cv.width; c.height = cv.height;
      const g = c.getContext('2d');
      g.drawImage(cv, 0, 0);
      const d = g.getImageData(0, 0, c.width, c.height).data;
      let n = 0;
      for (let i = 0; i < d.length; i += 4 * 97) {
        if (d[i] > 120 && d[i + 1] > 120 && d[i + 2] > 120) n++;
      }
      return n;
    } catch (e) { return -2; }
  };
  // 双层画布图型（rough 覆盖层 + ECharts 底层）：墨迹可能只在其中一层，
  // 取 host 内全部 canvas 的最大者，不能只戳第一个
  const inkBest = (host) => {
    let best = { cvW: 0, ink: -1 };
    if (!host) return best;
    [...host.querySelectorAll('canvas')].forEach(cv => {
      const n = inkOf(cv);
      if (n > best.ink) best = { cvW: cv.width, ink: n };
    });
    return best;
  };
  return {
    pollErr: window.__tbPollErr || null,
    noPageScroll: document.documentElement.scrollHeight <= document.documentElement.clientHeight + 2,
    docH: document.documentElement.scrollHeight,
    cliH: document.documentElement.clientHeight,
    bodyH: document.body.scrollHeight,
    rootH: Math.round(q('#tb-root').getBoundingClientRect().height),
    splitH: Math.round(q('#tb-split').getBoundingClientRect().height),
    zoneSubH: Math.round(q('#tb-zone-sub').getBoundingClientRect().height),
    zonePlotH: Math.round(q('#tb-zone-plot').getBoundingClientRect().height),
    // per-level scrollHeight/rect chain: find the first node whose scroll box or
    // rect exceeds the viewport, plus body children rects for the icb-overflow case
    diagChain: (() => {
      const g = s => document.querySelector(s);
      const row = (k, n) => n ? { [k]: { sH: n.scrollHeight, top: Math.round(n.getBoundingClientRect().top), bot: Math.round(n.getBoundingClientRect().bottom) } } : { [k]: null };
      const out = {};
      Object.assign(out, row('html', document.documentElement), row('body', document.body));
      const shell = g('body > div');
      Object.assign(out, row('shell', shell), row('sidebar', g('aside, #sidebar, nav')));
      const mn = g('main');
      Object.assign(out, row('main', mn), row('header', g('main > :first-child')), row('contentArea', g('#content-area')));
      Object.assign(out, row('tbRoot', g('#tb-root')), row('sidebarInner', shell ? shell.firstElementChild : null));
      out.bodyKids = [...document.body.children].map(c => {
        const r = c.getBoundingClientRect();
        return (c.id || c.tagName) + ':' + Math.round(r.top) + '~' + Math.round(r.bottom);
      });
      return out;
    })(),
    // unfiltered sweep: every element whose rect starts below the viewport fold,
    // plus proof of whether the window itself can actually scroll down
    diagSweep: (() => {
      const cH = document.documentElement.clientHeight;
      const past = [];
      qa('body *').forEach(n => {
        const r = n.getBoundingClientRect();
        if (r.top > cH - 4) past.push((n.id || n.tagName) + '.' + String(n.className).slice(0, 44) + ' top=' + Math.round(r.top) + ' h=' + Math.round(r.height));
      });
      const before = window.scrollY;
      window.scrollTo(0, 99999);
      const maxY = window.scrollY;
      const at = document.elementsFromPoint(400, cH - 60).slice(0, 4).map(n => n.id || n.tagName + '.' + String(n.className).slice(0, 24));
      window.scrollTo(0, before);
      return { maxY, past: past.slice(0, 12), bottomEls: at };
    })(),
    boardScroll: (() => { const b = q('#tb-board'); return b.scrollHeight - b.clientHeight; })(),
    roots: qa('#tb-board .tb-stage-root').map(e => e.textContent.replace(/\\s+/g, '')),
    problemRows: qa('#tb-board .tb-kind-problem').length,
    optRows: qa('#tb-board .tb-kind-options').length,
    stepLabel: board.textContent.includes('第 1 步'),
    // live 实例数以挂载容器 .tbc-wrap 计（rough 覆盖层图型一个实例占 2 个 canvas，数 canvas 会误报）
    // ---- v0.2.6 双栏：左栏零 live，当下图住右栏画幅 ----
    stageCanvas: board.querySelectorAll('.tbc-wrap').length,
    figVisible: (() => { const r = q('#tb-col-figure'); return !!r && !r.classList.contains('hidden'); })(),
    figId: (() => { const f = q('#tb-figure [data-fig]'); return f ? f.getAttribute('data-fig') : null; })(),
    figCanvas: (() => { const h = q('#tb-figure'); return h ? h.querySelectorAll('.tbc-wrap').length : 0; })(),
    figInk: inkBest(q('#tb-figure')),
    stageInk: (() => { const cv = board.querySelector('.tb-kind-plot canvas');
      return { cvW: cv ? cv.width : 0, ink: inkOf(cv) }; })(),
    bandInk: inkBest(band),
    stagePlots: plotRows.length,
    bandCanvas: band.querySelectorAll('.tbc-wrap').length,
    bandTopics: qa('#tb-timeline [data-band^="topic:"]').length,
    bandPlots: qa('#tb-timeline [data-band^="plot:"]').length,
    coldCount: cold.length,
    plotBtns: plotRows.filter(e => e.querySelector('button')).length,
    coldText: cold.length ? cold[0].textContent.replace(/\\s+/g, '').slice(0, 24) : '',
    welcomeEl: !!q('#tb-board-welcome'),
    welcomeHidden: q('#tb-board-welcome') ? q('#tb-board-welcome').classList.contains('hidden') : true,
    welcomeText: q('#tb-board-welcome') ? q('#tb-board-welcome').textContent : '',
    teacherLines: st.querySelectorAll('.tb-say-teacher').length,
    studentLines: st.querySelectorAll('.tb-say-student').length,
    streamGap: Math.round(st.scrollHeight - st.scrollTop - st.clientHeight),
    plotCount: q('#tb-plot-count').textContent
  };
})()"""


async def wait_for(tb, expr, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if await tb.ev(expr):
                return True
        except RuntimeError:
            pass
        await asyncio.sleep(0.4)
    return False


async def main() -> int:
    FIX.mkdir(parents=True, exist_ok=True)
    srv_port, cdp_port = free_port(), free_port()
    base = start_server(srv_port)
    tok, uid = make_user(base)
    err17, err18 = seed_errors(uid)
    step(True, "取证账号与两道种子错题已就绪", f"{USER} uid={uid} err17={err17} err18={err18}")

    MB._db_get = lambda key: ""
    MB.RETRY_S = 1
    cloud = FakeCloud()
    cloud.start()
    MB._spawn(f"ws://127.0.0.1:{cloud.port}/mcp", USER)
    step(cloud.wait_bridge(timeout=60), "MCP 桥已连上假小智云")
    if not cloud.wait_bridge(timeout=1):
        return 2

    profile = Path(__file__).resolve().parent / f"_p9_profile_{uuid.uuid4().hex[:6]}"
    got = await open_page(base, tok, cdp_port, profile)
    if not got:
        return 2
    tb, proc = got
    try:
        return await assertions(tb, proc, base, tok, cloud, err17, err18, state=None)
    finally:
        await tb.send("Page.navigate", url="about:blank")
        await tb.__aexit__()
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)


async def assertions(tb, proc, base, tok, cloud, err17, err18, state=None) -> int:

    # ---- A 下区非空兜底：开课前主舞台是欢迎行，历史带空 ----
    snap0 = await tb.ev(JS_STAGE)
    print("SNAPSHOT0:", json.dumps(snap0, ensure_ascii=False))
    step(snap0["welcomeHidden"] is False and "课还没开始" in snap0["welcomeText"],
         "开课前下区不空：欢迎行在岗", snap0["welcomeText"])
    step(snap0["bandTopics"] + snap0["bandPlots"] == 0, "开课前历史带为空")
    await tb.shot("p9_stage_welcome.png")

    # ---- 真链路讲完两题 ----
    r18_text = teach(base, tok, cloud, err17, err18)
    step(True, "两题经真工具链上板", f"题18返回文本 {len(r18_text or '')} 字")
    ok = await wait_for(tb, "document.querySelectorAll('#tb-board .tb-kind-plot').length > 0")
    step(ok, "主板书已渲染出图卡行")
    await asyncio.sleep(2.0)

    h = {"Authorization": "Bearer " + tok}
    state = requests.get(base + "/api/board/state", headers=h, timeout=6).json()["data"]
    items = state["items"]
    topics = [i for i in items if i["kind"] == "topic"]
    plots = [i for i in items if i["kind"] == "plot"]
    step(len(plots) == len(PLOTS), f"全部 {len(PLOTS)} 张图上板（DSL 拒收会在这红）",
         f"plots={len(plots)}")
    step(len(topics) == 2, "两道题=两个枝根（分开来写）", f"topics={[t['id'] for t in topics]}")
    step("建议" in r18_text and "board_draw" in r18_text,
         "写题返回带建议配图行（函数关键词命中 _suggest_plot）", r18_text[-80:])

    # ---- B 主舞台=当前枝（题18）：根通栏 + 题干 + 选项 + 步骤 ----
    snap = await tb.ev(JS_STAGE)
    print("SNAPSHOT1:", json.dumps(snap, ensure_ascii=False))
    step(snap["pollErr"] is None, "轮询无异常（页面在持续刷新）", snap["pollErr"])
    step(snap["noPageScroll"], "页面本身不整页滚动",
         f"doc={snap['docH']}/{snap['cliH']} body={snap['bodyH']} root={snap['rootH']} split={snap['splitH']} sub={snap['zoneSubH']} plot={snap['zonePlotH']} boardOverflow={snap['boardScroll']} sweep={json.dumps(snap['diagSweep'], ensure_ascii=False)}")
    step(len(snap["roots"]) == 1 and "题18" in snap["roots"][0],
         "主舞台根=当前题18枝（通栏大字）", snap["roots"])
    step(snap["problemRows"] >= 1 and snap["optRows"] >= 1,
         "题干与选项写在下方主板书区", f"problem={snap['problemRows']} options={snap['optRows']}")
    step(snap["stepLabel"], "步骤卡带「第 N 步」序号", snap["stepLabel"])
    step(snap["welcomeHidden"] is True, "有板书后欢迎行让位")
    step(snap["figVisible"] and snap["figInk"]["cvW"] >= 50 and snap["figInk"]["ink"] >= 3,
         "右栏画幅 live 图有真像素（canvas 尺寸+亮色墨迹，白板回归门）", str(snap["figInk"]))
    step(snap["bandInk"]["cvW"] >= 50 and snap["bandInk"]["ink"] >= 1,
         "历史带 live 缩略图有真像素", str(snap["bandInk"]))
    step(snap["bandTopics"] == 2 and snap["bandPlots"] >= 8,
         "历史带收齐两枝根与旧图缩略", f"topics={snap['bandTopics']} plots={snap['bandPlots']}")
    scat_item = next((i for i in items if i["kind"] == "plot"
                      and "监督对比" in (i["text"] or "")), None)
    smk = (scat_item or {}).get("data", {}).get("marks") or []
    step(smk[:2] and smk[0].get("series") == 1 and smk[1].get("series") == 2
         and smk[0]["name"] == "监督学习" and smk[1]["name"] == "无监督学习",
         "散点 marks 前两位是系列级（series=1/2，真系列名）", str(smk[:2]))
    step(snap["teacherLines"] >= 10 and snap["studentLines"] >= 2,
         "上区纯字幕：师/生分行", f"师={snap['teacherLines']} 生={snap['studentLines']}")
    step("张图" in snap["plotCount"], "板书区计数文案完整", snap["plotCount"])

    # ---- D live 实例闸（v0.2.6 双栏）：左栏零 live，右栏恒 <=1 ----
    step(snap["stageCanvas"] == 0 and snap["stagePlots"] >= 6 and
         snap["plotBtns"] == snap["stagePlots"],
         "左栏纯文字流：零 live 画布，每张图行都带放大按钮",
         f"stageCanvas={snap['stageCanvas']} rows={snap['stagePlots']} btns={snap['plotBtns']}")
    step(snap["figCanvas"] <= 1 and snap["figCanvas"] + snap["bandCanvas"] <= 8,
         "右栏+历史带 live 实例总数不超闸值",
         f"fig={snap['figCanvas']} band={snap['bandCanvas']}")
    await tb.shot("p9_stage_branch.png")

    # ---- B2 点历史带旧枝回看：切到题17枝，右栏跟着换旧枝最新图 ----
    tid17 = str(topics[0]["id"])      # raw digits: json.dumps would nest quotes into the attr selector
    p17newest = [p for p in plots if p["parent_id"] == topics[0]["id"]][-1]["id"]
    sw = await tb.ev("""(() => {
      const b = document.querySelector('#tb-timeline [data-band="topic:%s"]');
      if (!b) return {skip: 'no topic17 thumb'};
      b.click();
      const roots = [...document.querySelectorAll('#tb-board .tb-stage-root')].map(e => e.textContent.replace(/\\s+/g, ''));
      const f = document.querySelector('#tb-figure [data-fig]');
      return {roots, probs: document.querySelectorAll('#tb-board .tb-kind-problem').length,
              figId: f ? f.getAttribute('data-fig') : null};
    })()""" % tid17)
    step(bool(sw.get("roots")) and "题17" in sw["roots"][0] and sw.get("probs", 0) >= 1,
         "点历史带旧枝根：左栏切回题17分支", str(sw))
    step(sw.get("figId") == str(p17newest),
         "回看旧枝时右栏自动换成该枝最新图（图随枝走）", str(sw.get("figId")))
    # 制造一次真 rev 变更（新字幕），验证回看态在完整重绘后仍不被抢回
    say(base, tok, "teacher", "回看保持断言触发帧")
    await asyncio.sleep(1.8)
    held = await tb.ev("[...document.querySelectorAll('#tb-board .tb-stage-root')].map(e => e.textContent).join('|')")
    step("题17" in (held or ""), "回看态在下一次轮询后仍保持（不被抢回）", held)
    await tb.shot("p9_stage_backtrack.png")

    # ---- B3 点当前枝根回到最新 ----
    tid18 = str(topics[1]["id"])
    back = await tb.ev("""(() => {
      const b = document.querySelector('#tb-timeline [data-band="topic:%s"]');
      if (!b) return {skip: 'no topic18 thumb'};
      b.click();
      const roots = [...document.querySelectorAll('#tb-board .tb-stage-root')].map(e => e.textContent.replace(/\\s+/g, ''));
      const f = document.querySelector('#tb-figure [data-fig]');
      return {roots, figId: f ? f.getAttribute('data-fig') : null};
    })()""" % tid18)
    step(bool(back.get("roots")) and "题18" in back["roots"][0], "点当前枝根回到最新分支", str(back))
    step(back.get("figId") == str(plots[-1]["id"]), "回到最新枝：右栏跟上题18最新图", str(back.get("figId")))

    # ---- C 左栏冷行「放大」=钉住进右栏，分支树不破；指哪张换哪张 ----
    cold_id = None
    for p in reversed(plots[:-1]):        # 当前枝里非最新的任意一张
        if p["parent_id"] == topics[1]["id"]:
            cold_id = p["id"]
            break
    newest18 = plots[-1]["id"]
    z = await tb.ev("""(() => {
      const row = document.querySelector('#tb-board [data-plot="%s"]');
      if (!row) return {skip: 'no cold row'};
      const btn = row.querySelector('button');
      if (!btn) return {skip: 'row without enlarge button'};
      btn.click();
      const f = document.querySelector('#tb-figure [data-fig]');
      return {id: f ? f.getAttribute('data-fig') : null,
              rows: document.querySelectorAll('#tb-board .tb-kind-plot').length,
              roots: document.querySelectorAll('#tb-board .tb-stage-root').length};
    })()""" % cold_id)
    if z.get("skip"):
        step(False, "取证环境里存在可放大的冷行", str(z))
    else:
        step(z["id"] == str(cold_id) and z["rows"] >= 6 and z["roots"] == 1,
             "冷图放大=钉进右栏画幅，左栏分支树不破", str(z))
        say(base, tok, "teacher", "放大保持断言触发帧")
        await asyncio.sleep(1.8)
        held2 = await tb.ev("""(() => { const f = document.querySelector('#tb-figure [data-fig]');
          if (!f) return {id: null, cvW: 0, ink: -1};
          const inkOne = (cv) => {
            if (!cv || !cv.width) return -1;
            try { const c = document.createElement('canvas');
              c.width = cv.width; c.height = cv.height;
              const g = c.getContext('2d'); g.drawImage(cv, 0, 0);
              const d = g.getImageData(0, 0, c.width, c.height).data; let n = 0;
              for (let i = 0; i < d.length; i += 4 * 97) {
                if (d[i] > 120 && d[i+1] > 120 && d[i+2] > 120) n++; }
              return n; } catch (e) { return -2; } };
          let best = {cvW: 0, ink: -1};
          // 双层画布（rough 覆盖 + ECharts 底）：取全部 canvas 的最大墨迹
          [...f.querySelectorAll('canvas')].forEach(cv => { const n = inkOne(cv);
            if (n > best.ink) best = {cvW: cv.width, ink: n}; });
          return {id: f.getAttribute('data-fig'), cvW: best.cvW, ink: best.ink}; })()""")
        step(held2["id"] == str(cold_id) and held2["cvW"] >= 50 and held2["ink"] >= 3,
             "钉图态在下一次轮询后仍保持且有真像素", str(held2))
    await tb.shot("p9_stage_zoom.png")
    await tb.ev("""(() => { window.__jsErr = [];
      window.addEventListener('error', e => window.__jsErr.push(String(e.message).slice(0, 160)));
      return true; })()""")
    # 指哪张换哪张：历史带点回当前枝最新图，右栏跟着换，左栏图行始终在
    await tb.ev("""document.querySelector('#tb-timeline [data-band="plot:%s"]').click()""" % newest18)
    rest = await tb.ev("""(() => { const f = document.querySelector('#tb-figure [data-fig]');
      return {id: f ? f.getAttribute('data-fig') : null,
              rows: document.querySelectorAll('#tb-board .tb-kind-plot').length}; })()""")
    errs = await tb.ev("window.__jsErr || []")
    step(rest["id"] == str(newest18) and rest["rows"] >= 6,
         "历史带点图：右栏指哪张换哪张，左栏图行恒在", f"{rest} jsErr={errs}")

    # ---- E 〔锚点〕point 指认落在主板书上 ----
    anchor_card = next((i for i in items if i["kind"] == "step" and "开口方向" in (i["text"] or "")), None)
    step(anchor_card is not None, "锚点步骤卡在板上（题18枝）", str(anchor_card and anchor_card["id"]))
    await tb.ev("""(() => { const L = document.querySelector('#tb-laser');
      window.__laserSeen = false;
      new MutationObserver(() => { if (L.classList.contains('tb-laser-on')) window.__laserSeen = true; })
        .observe(L, {attributes: true});
      return true; })()""")
    cloud.call_tool("board_highlight", {"item_id": anchor_card["id"], "point": 1})
    hit = await wait_for(tb, "document.querySelectorAll('#tb-board .tb-anc-on').length > 0", timeout=12)
    foc = await tb.ev("""(() => ({
      ancOn: document.querySelectorAll('#tb-board .tb-anc-on').length,
      stageFocus: document.querySelectorAll('#tb-board .tb-focus').length,
      streamFocus: document.querySelectorAll('#tb-stream .tb-focus').length,
      laser: !!window.__laserSeen }))()""")
    step(hit and foc["ancOn"] >= 1 and foc["stageFocus"] >= 1 and foc["laser"],
         "point=1 锚指认点亮主板书行（锚点+激光+讲课时高亮）", str(foc))

    # ---- E2 〔v0.2.7 系列指认〕散点 point=1 指整组：监督/无监督事故复刻取证 ----
    # 散点是最末一张图=当前枝最新图，teach 完右栏画幅正是它，焦点切换无需再钉图
    JS_FIG_INK = """(() => { const f = document.querySelector('#tb-figure');
      if (!f) return {cvW: 0, ink: -1};
      const inkOne = (cv) => {
        if (!cv || !cv.width) return -1;
        try { const c = document.createElement('canvas');
          c.width = cv.width; c.height = cv.height;
          const g = c.getContext('2d'); g.drawImage(cv, 0, 0);
          const d = g.getImageData(0, 0, c.width, c.height).data; let n = 0;
          for (let i = 0; i < d.length; i += 4 * 97) {
            if (d[i] > 120 && d[i+1] > 120 && d[i+2] > 120) n++; }
          return n; } catch (e) { return -2; } };
      let best = {cvW: 0, ink: -1};
      [...f.querySelectorAll('canvas')].forEach(cv => { const n = inkOne(cv);
        if (n > best.ink) best = {cvW: cv.width, ink: n}; });
      return best; })()"""
    await tb.ev("(() => { window.__laserSeen = false; return true; })()")
    hs = cloud.call_tool("board_highlight",
                         {"item_id": str(scat_item["id"]), "point": 1})
    okE2 = await wait_for(tb, "!!window.__laserSeen", timeout=12)
    e2 = await tb.ev("""(() => ({
      figId: (() => { const f = document.querySelector('#tb-figure [data-fig]');
                       return f ? f.getAttribute('data-fig') : null; })(),
      jsErr: window.__jsErr || [] }))()""")
    figI2 = await tb.ev(JS_FIG_INK)
    step("监督学习" in (hs or ""),
         "系列指认回文带系列名（激光指到图上的「监督学习」）", (hs or "")[-90:])
    step(okE2 and e2["figId"] == str(scat_item["id"]),
         "point=1 系列级 mark：激光落系列重心，右栏画幅就是散点卡",
         f"figId={e2['figId']} jsErr={e2['jsErr']}")
    step(not e2["jsErr"] and figI2["cvW"] >= 50 and figI2["ink"] >= 3,
         "highlightSeries（整组放大+其余压暗）不炸图，画幅仍有真像素",
         f"{figI2} errs={e2['jsErr']}")
    cloud.call_tool("board_highlight", {"item_id": str(scat_item["id"]), "point": 2})
    okE2b = await wait_for(tb, "!!window.__laserSeen", timeout=12)
    step(okE2b, "point=2 指到第二组（无监督学习）激光再落", "")
    await tb.shot("p9_stage_series_focus.png")

    # ---- F 上区字幕贴底 + 分隔条拖拽回归 ----
    snapF = await tb.ev(JS_STAGE)
    step(snapF["streamGap"] <= 24, "当前句贴在字幕区底", f"gap={snapF['streamGap']}")
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

    # ---- G 换题闭窗归档：当前课题18的图逐张被顶走 -> 烧成课件页 ----
    pages, deadline = 0, time.time() + 240
    while time.time() < deadline:
        d = requests.get(base + "/api/board/lesson", headers=h, timeout=6).json()["data"]
        pages = len(d.get("slides") or [])
        if pages >= N_T2 - 1:
            break
        await asyncio.sleep(2)
    step(pages >= N_T2 - 1, "换题后图被顶走时自动烧成课件页",
         f"pages={pages} expect>={N_T2 - 1} lesson={(state.get('lesson_key') or '')[:12]}")
    await tb.ev("document.querySelector('#tb-lesson-btn').click()")
    await asyncio.sleep(1.5)
    imgs = await tb.ev("""(async () => { const box = document.querySelector('#tb-drawer-body');
      for (let y = 0; y <= box.scrollHeight; y += 260) { box.scrollTop = y; await new Promise(r => setTimeout(r, 70)); }
      box.scrollTop = 0; await new Promise(r => setTimeout(r, 1500));
      const im = [...box.querySelectorAll('img')];
      return {n: im.length, loaded: im.filter(i => i.naturalWidth > 0).length,
              w: im[0] ? im[0].naturalWidth : 0,
              cap: (box.textContent.match(/\\u8bb2\\u7a3f\\uff1a[^]{0,30}/) || [''])[0]}; })()""", promise=True)
    step(imgs["loaded"] >= N_T2 - 1 and imgs["w"] == 1280 and "讲稿" in imgs["cap"],
         "课件抽屉：归档 PNG 可显示且带烧进去的讲稿", str(imgs))
    await tb.shot("p9_stage_drawer.png")
    return 0


if __name__ == "__main__":
    code = 1
    try:
        code = asyncio.run(main())
    except BaseException as e:                    # never let a throw masquerade as pass
        import traceback
        traceback.print_exc()
        fails.append("uncaught: " + repr(e)[:160])
    finally:
        print("\n==== P9 CDP(五期主板书): " + ("ALL PASS" if not fails and code == 0 else ("FAIL(" + str(len(fails)) + "): " + " | ".join(fails) if fails else "EARLY EXIT code=" + str(code))) + " ====")
        sys.exit(0 if not fails and code == 0 else 2)
