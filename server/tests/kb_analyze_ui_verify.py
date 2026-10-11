# -*- coding: utf-8 -*-
"""错题智能分析 UI 断言（2026-10-13）：Playwright 全链路 + 截图识图回填核对。

覆盖（延续 kb_manage_ui_verify harness 配方：独立测试用户、dialog 自动接受、轮询看门狗、截图落盘）：
1. 错题弹窗打开 → 编辑器写入「题干 + 已存在的 vault 图片引用」（仿真几何题图）
2. 点【智能分析】→ 状态转「智能分析中」→ 轮询（真调 Paddle 版面 + 系统 VL，外网）
3. confirm 自动接受 → 断言回填：编辑器含 _fig 切片引用、【解析】以「## 我的解答」开头、【正确答案】非空
4. 截图落盘（回填后弹窗）；pageerror 必须为空
5. 测后 DB 直删 + 清理测试用户 vault 图片

运行前置：服务端已在 127.0.0.1:6001 运行（新代码 + VL .env 已加载）。
"""
import base64
import json
import sys
import time
import uuid
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database import db_adapter  # noqa: E402
import config  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:6001"
SHOT_DIR = Path(r"e:\LLM\LectureLearnLoop\design\walkthrough")
OUT = Path(r"e:\LLM\LectureLearnLoop\server\logs\kb_analyze_ui_verify.txt")
MOD = "AEUI" + uuid.uuid4().hex[:6]
SUBJECT = f"{MOD}_分析科"
PFX = MOD + "%"

lines, fails = [], []


def step(name, ok, extra=""):
    lines.append(f"{'PASS' if ok else 'FAIL'} {name} {extra}")
    if not ok:
        fails.append(name)
    print(lines[-1])


def _exec(sql, params=None, fetch=False):
    c = db_adapter.get_connection(str(config.DB_PATH))
    try:
        cur = c.cursor()
        cur.execute(sql, params or ())
        rows = cur.fetchall() if fetch else None
        c.commit()
        return rows
    finally:
        c.close()


def _try_exec(sql, params=None):
    try:
        _exec(sql, params)
    except Exception:  # noqa: BLE001 清理容错：表不存在/列差异不阻断测试
        pass


def _purge(uid):
    _try_exec("DELETE FROM error_proficiency_history WHERE error_question_id IN "
              "(SELECT id FROM error_questions WHERE user_id = ? AND subject_name LIKE ?)", (uid, PFX))
    _try_exec("DELETE FROM error_questions WHERE user_id = ? AND subject_name LIKE ?", (uid, PFX))
    _try_exec("DELETE FROM knowledge_point_sources WHERE knowledge_point_id IN "
              "(SELECT id FROM knowledge_points WHERE user_id = ? AND subject_name LIKE ?)", (uid, PFX))
    _try_exec("DELETE FROM knowledge_points WHERE user_id = ? AND subject_name LIKE ?", (uid, PFX))


# ---------- 登录一次性测试用户 ----------
UNAME = MOD.lower()
requests.post(BASE + "/api/auth/register", json={"username": UNAME, "password": "test123456"}, timeout=15)
TOKEN = requests.post(BASE + "/api/auth/login", json={"username": UNAME, "password": "test123456"},
                      timeout=15).json()["data"]["token"]
H = {"Authorization": "Bearer " + TOKEN}
_seg = TOKEN.split(".")[1]
UID = json.loads(base64.urlsafe_b64decode(_seg + "=" * (-len(_seg) % 4)))["uid"]
step("login_test_user", True, f"uid={UID}")
_purge(UID)
requests.post(BASE + "/api/subjects", json={"subject_name": SUBJECT}, headers=H, timeout=15)

# ---------- 造仿真几何题图，直接放入测试用户 vault 截图目录 ----------
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

VAULT_SHOTS = Path(config.VAULT_DIR) / UID / "截图"
VAULT_SHOTS.mkdir(parents=True, exist_ok=True)
shots_before = set(VAULT_SHOTS.glob("*"))
GEOM_NAME = f"geom_{MOD}.png"
geom = VAULT_SHOTS / GEOM_NAME
FONT = r"C:\Windows\Fonts\msyh.ttc"
W, Hh = 1200, 800
im = Image.new("RGB", (W, Hh), "white")
d = ImageDraw.Draw(im)
f_big = ImageFont.truetype(FONT, 34)
f_mid = ImageFont.truetype(FONT, 30)
d.text((40, 40), "如图所示，在三角形 ABC 中，AB = AC，", font=f_big, fill="black")
d.text((40, 100), "角 A = 40°，则角 B 的度数为 ____ 度。", font=f_big, fill="black")
A, B, C = (760, 180), (560, 470), (960, 470)
d.line([A, B, C, A], fill="black", width=4)
d.text((A[0] - 10, A[1] - 50), "A", font=f_mid, fill="black")
d.text((B[0] - 40, B[1] - 10), "B", font=f_mid, fill="black")
d.text((C[0] + 14, C[1] - 10), "C", font=f_mid, fill="black")
d.text((40, 560), "解：因为 AB = AC，", font=f_big, fill=(20, 20, 200))
d.text((40, 620), "所以角 B = 角 A = 40°。", font=f_big, fill=(20, 20, 200))
im.save(geom)
DRAFT_MD = f"题目如图。\n![题目](截图/{GEOM_NAME})\n我的解答：AB=AC 所以角B=角A=40°。"

t0 = time.time()
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.set_default_timeout(60000)
    pageerrs = []
    pg.on("pageerror", lambda e: pageerrs.append(str(getattr(e, "message", "") or e)[:200]))
    pg.on("dialog", lambda dl: dl.accept())  # 回填 confirm 自动接受

    def until(expr, arg=None, loops=60, ms=500):
        for _ in range(loops):
            try:
                v = pg.evaluate(expr, arg) if arg is not None else pg.evaluate(expr)
            except Exception:
                v = None
            if v:
                return v
            pg.wait_for_timeout(ms)
        return False

    pg.goto(BASE + "/login", wait_until="domcontentloaded")
    pg.evaluate("t => localStorage.setItem('ll_token', t)", TOKEN)
    pg.goto(BASE + "/", wait_until="networkidle")
    pg.wait_for_timeout(800)

    # ---------- 1. 错题弹窗 ----------
    pg.evaluate("handleMenuClick('knowledge_base')")
    until("!!document.getElementById('kb-subject-grid') && !!window.kbShowSubject")
    pg.evaluate(f"kbShowSubject({SUBJECT!r})")
    until("document.getElementById('kb-tabs').classList.contains('flex')")
    pg.click("#kb-tab-errors")
    until("document.getElementById('kb-add-btn').textContent.includes('新增错题')")
    step("ui01 errors_tab_ready", True)
    pg.click("#kb-add-btn")
    ok = until("!document.getElementById('kb-modal').classList.contains('hidden') && !!document.getElementById('kbm-editor')")
    step("ui02 error_modal_open", bool(ok))

    # ---------- 2. 写入题干（含 vault 图引用），编辑器就绪重试 ----------
    def set_editor(text, loops=20):
        for _ in range(loops):
            pg.evaluate("(t) => { var m=document.getElementById('kbm-editor');"
                        "if (m && m.__vd && m.__vd.setValue) { try{ m.__vd.setValue(t); }catch(e){} } return 1; }", text)
            pg.wait_for_timeout(400)
            got = pg.evaluate("() => { var m=document.getElementById('kbm-editor'); return m && m.__vd ? String(m.__vd.getValue()||'') : ''; }")
            if got.strip():
                return got
        return ""
    cur = set_editor(DRAFT_MD)
    step("ui03 draft_with_image_ref", "截图/" in cur, cur[:70])

    # ---------- 3. 点智能分析，真调管线（外网，上限 ~300s） ----------
    has_btn = pg.evaluate("() => !!document.getElementById('kbm-analyze')")
    step("ui04_analyze_button_present", bool(has_btn))
    pg.click("#kbm-analyze")
    until("() => { var s=document.getElementById('kb-modal-status').textContent; return s && s.indexOf('智能分析') >= 0; }", loops=10)
    st = pg.evaluate("() => document.getElementById('kb-modal-status').textContent")
    step("ui05_status_analyzing", "智能分析" in (st or ""), (st or "")[:60])

    # 轮询回填：done+confirm已接受 的判据（防竞态：explain 非空 或 状态消息已达终态）
    def analyze_state():
        e = pg.evaluate("() => String((document.getElementById('kbm-explain')||{}).value||'')") or ""
        if e.strip():
            return "filled"
        s = pg.evaluate("() => document.getElementById('kb-modal-status').textContent") or ""
        if any(k in s for k in ("已回填", "失败", "超时")):
            return "terminal:" + s[:40]
        return False
    ok = until(analyze_state, loops=185, ms=2000)  # 上限 370s（覆盖 VL 重试）
    exp_val = pg.evaluate("() => String((document.getElementById('kbm-explain')||{}).value||'')")
    ans_val = pg.evaluate("() => String((document.getElementById('kbm-answer')||{}).value||'')")
    ed_val = pg.evaluate("() => { var m=document.getElementById('kbm-editor'); return m && m.__vd ? String(m.__vd.getValue()||'') : ''; }")
    status_final = pg.evaluate("() => document.getElementById('kb-modal-status').textContent")
    # ui06 基于终态证据判定（回填成功与否看 explain 是否已写入 / 状态是否「已回填」），消除轮询末拍错过回填落地的竞态
    backfilled = bool((exp_val or "").strip()) or ("已回填" in (status_final or ""))
    step("ui06_backfill_done", bool(ok) or backfilled, f"state={ok} status={(status_final or '')[:60]}")
    step("ui07_stem_has_fig_slice", "_fig" in ed_val, ed_val[-90:])
    step("ui08_explain_solution_first", (exp_val or "").startswith("## 我的解答"), (exp_val or "")[:60])
    step("ui09_answer_filled", bool((ans_val or "").strip()), (ans_val or "")[:40])
    pg.screenshot(path=str(SHOT_DIR / "kbui_analyze_backfill.png"))

    b.close()

step("ui10_no_pageerror", not pageerrs, str(pageerrs[:2])[:160])

# ---------- 清理：DB + vault 新增图片（含切片） ----------
_purge(UID)
shots_after = set(VAULT_SHOTS.glob("*")) if VAULT_SHOTS.exists() else set()
for f in (shots_after - shots_before):
    try:
        f.unlink()
    except OSError:
        pass
if geom.exists():
    geom.unlink(missing_ok=True)
for f in VAULT_SHOTS.glob(f"geom_{MOD}_fig*"):
    f.unlink(missing_ok=True)

OUT.write_text("\n".join(lines) + f"\n\nELAPSED={time.time()-t0:.1f}s FAILS={fails}\n", encoding="utf-8")
print(f"== finish FAILS={fails} elapsed={time.time()-t0:.1f}s")
sys.exit(1 if fails else 0)
