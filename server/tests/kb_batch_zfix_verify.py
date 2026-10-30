# -*- coding: utf-8 -*-
"""批量错题 z-index 兜底 + 遮罩防误关 定向断言（2026-10-14，客户现场两 bug 回归）。

场景复现（用户反馈）：
1. 框选层被「新增错题」弹窗盖住 → 根因是客户端缓存旧 cl.css（无 z-[92] 新类）。
   修复：#kbo z-index 硬编码进模板自有 <style>。本测试拦截 cl.css 删除 .z-[92]
   规则模拟旧缓存，断言 #kbo 计算样式 z-index 仍为 92 且命中测试在弹窗之上。
2. 框选/上传阶段点弹窗外遮罩 → 弹窗整体关闭、图片与框选层全消失、无确认。
   修复：closeModal 对已有图片/结果补丢弃确认。断言：点遮罩弹确认框、
   取消后弹窗与图片仍在；「返回列表」不触发该确认（不丢状态）。

运行前置：服务端已在 BASE（默认 6001，LL_TEST_BASE 可覆盖）运行。零大模型调用。
"""
import base64
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = os.getenv("LL_TEST_BASE", "http://127.0.0.1:6001")
OUT = Path(r"e:\LLM\LectureLearnLoop\server\logs\kb_batch_zfix_verify.txt")

lines, fails = [], []


def step(name, ok, extra=""):
    lines.append(f"{'PASS' if ok else 'FAIL'} {name} {extra}")
    if not ok:
        fails.append(name)
    print(lines[-1])


# ---------- 独立测试用户（零积分消耗：只上传+开框选，不提交识别） ----------
from PIL import Image  # noqa: E402

UNAME = "kz_" + uuid.uuid4().hex[:8]
requests.post(BASE + "/api/auth/register", json={"username": UNAME, "password": "test123456"}, timeout=15)
TOKEN = requests.post(BASE + "/api/auth/login", json={"username": UNAME, "password": "test123456"}, timeout=15).json()["data"]["token"]
H = {"Authorization": "Bearer " + TOKEN}
_seg = TOKEN.split(".")[1]
UID = json.loads(base64.urlsafe_b64decode(_seg + "=" * (-len(_seg) % 4)))["uid"]
requests.post(BASE + "/api/subjects", json={"subject_name": "KZ_层级科"}, headers=H, timeout=15)

IMG = Path(r"e:\LLM\LectureLearnLoop\server\logs\_kz_a.png")
Image.new("RGB", (300, 150), "white").save(IMG)

VAULT_SHOTS = Path(r"e:\LLM\LectureLearnLoop\server\data")  # 仅作兜底路径参考，实际按 uid 清理下方
t0 = time.time()
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.set_default_timeout(60000)
    pageerrs, dialogs = [], []
    pg.on("pageerror", lambda e: pageerrs.append(str(getattr(e, "message", "") or e)[:300]))
    pg.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))  # 默认取消：验证不丢失

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

    def goto_kb_batch():
        """进入 知识库→错题→新增错题→批量页签（复用于首轮与旧缓存轮）"""
        pg.goto(BASE + "/", wait_until="networkidle")
        pg.wait_for_timeout(800)
        pg.evaluate("handleMenuClick('knowledge_base')")
        until("!!window.kbShowSubject && document.querySelectorAll('#kb-subject-grid [data-subj]').length > 0")
        pg.evaluate("kbShowSubject('KZ_层级科')")
        pg.click("#kb-tab-errors")
        until("document.getElementById('kb-add-btn').textContent.includes('新增错题')")
        pg.click("#kb-add-btn")
        until("!document.getElementById('kb-modal').classList.contains('hidden') && !!document.getElementById('kbm-tabs')")
        pg.click("#kbm-tabs [data-etab=batch]")
        until("!!document.getElementById('kbb-upload')")

    # 先注册 localStorage 登录态
    pg.goto(BASE + "/login", wait_until="domcontentloaded")
    pg.evaluate("t => localStorage.setItem('ll_token', t)", TOKEN)

    # ================= 轮 1：正常 CSS，验证遮罩防误关 =================
    goto_kb_batch()
    pg.set_input_files("#kbb-file", [str(IMG)])
    ok = until("() => document.getElementById('kbb-sum').textContent.includes('就绪 1')", loops=40)
    step("z01_upload_ready", bool(ok))
    # 点弹窗外遮罩（面板居中，左侧空白即遮罩）→ 应弹确认，取消后一切仍在
    dialogs.clear()
    pg.mouse.click(60, 450)
    pg.wait_for_timeout(600)
    step("z02_mask_confirm_shown", any("丢弃" in m for m in dialogs), str(dialogs)[:120])
    step("z03_modal_kept_after_cancel", bool(pg.evaluate(
        "() => !document.getElementById('kb-modal').classList.contains('hidden') && "
        "document.getElementById('kbb-sum').textContent.includes('就绪 1')")))
    # 「提取错题」打开框选层 → 「返回列表」不应触发丢弃确认（回列表而非关窗）
    n_before = len(dialogs)
    pg.click("#kbb-extract")
    ok = until("() => { var e = document.getElementById('kbo'); "
               "return !e.classList.contains('hidden') && e.classList.contains('flex'); }")
    step("z04_overlay_open", bool(ok))
    pg.click("#kbo-back")
    pg.wait_for_timeout(400)
    step("z05_back_no_discard_dialog", len(dialogs) == n_before, str(dialogs[n_before:])[:120])
    step("z06_back_keeps_batch", bool(pg.evaluate(
        "() => !document.getElementById('kb-modal').classList.contains('hidden') && "
        "!!document.getElementById('kbb-sum') && "
        "document.getElementById('kbb-sum').textContent.includes('1')")))

    # ================= 轮 2：拦截 cl.css 删除 .z-[92]，模拟客户端旧缓存 =================
    css_txt = None
    orig = pg.request.get(BASE + "/static/css/cl.css")
    css_txt = orig.text()
    stripped = re.sub(r"\.z-\\\[92\\\]\s*\{[^}]*\}", "", css_txt)
    step("z07_rule_present_then_stripped", ".z-\\[92\\]" in css_txt and ".z-\\[92\\]" not in stripped)
    pg.route("**/static/css/cl.css**",
             lambda route: route.fulfill(body=stripped, content_type="text/css"))
    goto_kb_batch()  # reload 后路由拦截生效（旧缓存等价态）
    pg.set_input_files("#kbb-file", [str(IMG)])
    ok = until("() => document.getElementById('kbb-sum').textContent.includes('就绪 1')", loops=40)
    step("z08_upload_ready_cached_css", bool(ok))
    pg.click("#kbb-extract")
    ok = until("() => { var e = document.getElementById('kbo'); "
               "return !e.classList.contains('hidden') && e.classList.contains('flex'); }")
    step("z09_overlay_open_cached_css", bool(ok))
    z = pg.evaluate("getComputedStyle(document.getElementById('kbo')).zIndex")
    zm = pg.evaluate("getComputedStyle(document.getElementById('kb-modal')).zIndex")
    step("z10_kbo_above_modal", str(z) == "92" and str(zm) == "90", f"kbo={z} modal={zm}")
    # 命中测试：canvas 中心点最上层元素必须属于 #kbo（弹窗/遮罩不得拦截）
    hit = pg.evaluate("""() => { const r = document.getElementById('kbo-canvas').getBoundingClientRect();
        const el = document.elementFromPoint(r.left + r.width/2, r.top + r.height/2);
        return !!(el && (el.id === 'kbo' || el.closest('#kbo'))); }""")
    step("z11_hit_test_on_overlay", bool(hit))
    # 拖一个框确认可交互（旧缓存态下真实用户动作）
    rect = pg.evaluate("() => { const r = document.getElementById('kbo-canvas').getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; }")
    pg.evaluate("document.getElementById('kbo-img').complete && 1")
    until("() => { var im = document.getElementById('kbo-img'); return im.complete && im.naturalWidth === 300; }", loops=40, ms=250)
    rect = pg.evaluate("() => { const r = document.getElementById('kbo-canvas').getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; }")
    L, T, W, Hh = rect
    # 框选已默认开启；幂等保护：仅未开启时点一次
    if not pg.evaluate("document.getElementById('kbo-draw').classList.contains('cl-btn-primary')"):
        pg.click("#kbo-draw")
    pg.mouse.move(L + 20, T + 20); pg.mouse.down()
    pg.mouse.move(L + W - 30, T + Hh - 20, steps=6); pg.mouse.up()
    pg.wait_for_timeout(350)
    nb = pg.evaluate("document.querySelectorAll('#kbo-canvas .kbo-n').length")
    step("z12_can_draw_box_cached_css", nb == 1, f"boxes={nb}")
    pg.screenshot(path=r"e:\LLM\LectureLearnLoop\design\walkthrough\b28_zindex_cached_css.png")
    pg.unroute("**/static/css/cl.css**")

    b.close()

step("z90_no_pageerror", not pageerrs, str(pageerrs)[:300])

# ---------- 清理：测试用户错题/科目 + vault 上传图 ----------
def _exec(sql, params=None, fetch=False):
    from database import db_adapter
    import config
    c = db_adapter.get_connection(str(config.DB_PATH))
    try:
        cur = c.cursor(); cur.execute(sql, params or ())
        rows = cur.fetchall() if fetch else None; c.commit(); return rows
    finally:
        c.close()

_exec("DELETE FROM error_proficiency_history WHERE error_question_id IN "
      "(SELECT id FROM error_questions WHERE user_id = ?)", (str(UID),))
_exec("DELETE FROM error_questions WHERE user_id = ?", (str(UID),))
_exec("DELETE FROM practice_records WHERE user_id = ?", (str(UID),))
_exec("DELETE FROM user_subjects WHERE user_id = ?", (str(UID),))
import config  # noqa: E402
vd = Path(config.VAULT_DIR) / str(UID)
if vd.exists():
    import shutil
    shutil.rmtree(vd, ignore_errors=True)
IMG.unlink(missing_ok=True)

OUT.write_text("\n".join(lines) + f"\n耗时 {round(time.time()-t0,1)}s\n"
               + ("ALL_PASS\n" if not fails else f"FAILS: {fails}\n"), encoding="utf-8")
print("RESULT:", "ALL_PASS" if not fails else f"FAILS={fails}", f"elapsed={round(time.time()-t0,1)}s")
