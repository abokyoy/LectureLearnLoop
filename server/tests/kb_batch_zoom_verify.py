# -*- coding: utf-8 -*-
"""框选层「缩放/平移 + 简化确认文案」定向断言（2026-10-15 用户反馈增强）。

覆盖：
1. 进入框选层默认开启框选（此前默认关闭、要先点开关才可画框 = 客户现场困惑点之一）
2. 放大/缩小按钮 + 百分比读数 + 滚轮缩放
3. 放大后框选的归一化坐标仍精确（rect 实时读取，缩放不改变坐标数学）
4. 关闭框选开关后拖拽 = 平移画布（scrollLeft 变化），不产生新框
5. 「完成」确认文案只讲积分与耗时，不再出现「版面分析 / N 次大模型」术语；点取消不提交
6. 全程无 pageerror；截图存档

运行前置：服务端已在 BASE（默认 6150，可用环境变量 LL_TEST_BASE 覆盖）运行。
不调用 VL：确认框一律 dismiss，本脚本零识别消耗。
"""
import base64
import io
import json
import os
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

BASE = os.getenv("LL_TEST_BASE", "http://127.0.0.1:6150")
SHOT_DIR = Path(r"e:\LLM\LectureLearnLoop\design\walkthrough")

lines, fails = [], []


def step(name, ok, extra=""):
    lines.append(f"{'PASS' if ok else 'FAIL'} {name} {extra}")
    if not ok:
        fails.append(name)
    print(lines[-1])


def _exec(sql, params=None):
    c = db_adapter.get_connection(str(config.DB_PATH))
    try:
        cur = c.cursor(); cur.execute(sql, params or ()); c.commit()
    finally:
        c.close()


# ---------- 独立测试用户 ----------
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

UNAME = "kbz_" + uuid.uuid4().hex[:8]
requests.post(BASE + "/api/auth/register", json={"username": UNAME, "password": "test123456"}, timeout=15)
TOKEN = requests.post(BASE + "/api/auth/login", json={"username": UNAME, "password": "test123456"}, timeout=15).json()["data"]["token"]
_seg = TOKEN.split(".")[1]
UID = json.loads(base64.urlsafe_b64decode(_seg + "=" * (-len(_seg) % 4)))["uid"]
_exec("DELETE FROM error_questions WHERE user_id = ? AND subject_name LIKE ?", (UID, "KBZ%"))

Z_PATH = Path(r"e:\LLM\LectureLearnLoop\server\logs\_kbz.png")
img = Image.new("RGB", (800, 600), "white")
d = ImageDraw.Draw(img)
try:
    font = ImageFont.truetype("arial.ttf", 40)
except Exception:
    font = ImageFont.load_default()
for i, t in enumerate(["Q1: Compute 2 + 3 = ?", "Q2: Compute 5 * 4 = ?", "Q3: Compute 9 - 2 = ?"]):
    d.text((40, 80 + i * 140), t, fill="black", font=font)
img.save(Z_PATH)

VAULT_SHOTS = Path(config.VAULT_DIR) / str(UID) / "截图"
VAULT_SHOTS.mkdir(parents=True, exist_ok=True)
shots_before = set(VAULT_SHOTS.glob("*"))

dialogs = []  # (message, action)
t0 = time.time()
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.set_default_timeout(60000)
    pageerrs = []
    pg.on("pageerror", lambda e: pageerrs.append(str(getattr(e, "message", "") or e)[:300]))

    def on_dialog(dlog):
        # 「开始识别」确认一律 dismiss（零 VL 消耗）；关闭弹窗等其它确认 accept 便于清理
        if "积分" in (dlog.message or ""):
            dialogs.append((dlog.message, "dismiss")); dlog.dismiss()
        else:
            dialogs.append((dlog.message, "accept")); dlog.accept()
    pg.on("dialog", on_dialog)

    def until(expr, loops=60, ms=400):
        for _ in range(loops):
            try:
                v = pg.evaluate(expr)
            except Exception:
                v = None
            if v:
                return v
            pg.wait_for_timeout(ms)
        return False

    def canvas_rect():
        return pg.evaluate("() => { const r = document.getElementById('kbo-canvas').getBoundingClientRect();"
                           "return [r.left, r.top, r.width, r.height]; }")

    def drag(x1, y1, x2, y2):
        pg.mouse.move(x1, y1); pg.mouse.down()
        pg.mouse.move(x2, y2, steps=6); pg.mouse.up()
        pg.wait_for_timeout(250)

    def boxes_norm():
        return pg.evaluate("""() => [...document.querySelectorAll('#kbo-canvas .kbo-box:not(.kbo-ghost)')]
            .map(b => [parseFloat(b.style.left), parseFloat(b.style.top), parseFloat(b.style.width), parseFloat(b.style.height)])""")

    def zpct():
        t = pg.evaluate("document.getElementById('kbo-zpct').textContent") or "0%"
        return int((t or "0").replace("%", "").strip() or 0)

    def badges():
        return pg.evaluate("() => Array.from(document.querySelectorAll('#kbo-canvas .kbo-n')).map(n => n.textContent.trim())")

    pg.goto(BASE + "/login", wait_until="domcontentloaded")
    pg.evaluate("t => localStorage.setItem('ll_token', t)", TOKEN)
    pg.goto(BASE + "/", wait_until="networkidle")
    pg.wait_for_timeout(800)

    # ---------- 进入框选层 ----------
    pg.evaluate("handleMenuClick('knowledge_base')")
    until("!!window.kbShowSubject && document.querySelectorAll('#kb-subject-grid [data-subj]').length > 0")
    pg.evaluate("kbShowSubject('KBZ_缩放科')")
    requests.post(BASE + "/api/subjects", json={"subject_name": "KBZ_缩放科"},
                  headers={"Authorization": "Bearer " + TOKEN}, timeout=15)
    pg.evaluate("kbShowSubject('KBZ_缩放科')")
    pg.click("#kb-tab-errors")
    until("document.getElementById('kb-add-btn').textContent.includes('新增错题')")
    pg.click("#kb-add-btn")
    until("!document.getElementById('kb-modal').classList.contains('hidden') && !!document.getElementById('kbm-tabs')")
    pg.click("#kbm-tabs [data-etab=batch]")
    until("!!document.getElementById('kbb-upload') && !document.getElementById('kbm-batch').classList.contains('hidden')")
    pg.set_input_files("#kbb-file", [str(Z_PATH)])
    ok = until("() => { var s = document.getElementById('kbb-sum').textContent;"
               "return s.includes('1 张图片') && s.includes('就绪 1'); }", loops=40)
    step("zx00 upload_ready", bool(ok))
    pg.click("#kbb-extract")
    ok = until("() => { var e = document.getElementById('kbo');"
               "return !e.classList.contains('hidden') && e.classList.contains('flex'); }")
    step("zx01_overlay_open", bool(ok))
    step("zx02_draw_on_by_default", bool(pg.evaluate(
        "() => document.getElementById('kbo-draw').classList.contains('cl-btn-primary') &&"
        " document.getElementById('kbo-canvas').classList.contains('kbo-drawing')")))
    step("zx03_zoom_btns_visible", bool(pg.evaluate(
        "() => ['kbo-zin','kbo-zout','kbo-zfit','kbo-zpct'].every(id => document.getElementById(id))")))
    until("() => { var im = document.getElementById('kbo-img');"
          "return im.complete && im.naturalWidth === 800 && im.clientHeight > 100; }", loops=40, ms=250)

    # ---------- 默认态直接画框（旧版必须先点开关） ----------
    r = canvas_rect(); L, T, W, Hh = r
    s1 = W / 800.0
    drag(L + 0.05 * W, T + 0.05 * Hh, L + 0.5 * W, T + 0.4 * Hh)
    bn = boxes_norm()
    n1 = len(bn) == 1 and all(abs(a - b) < 0.03 for a, b in zip(bn[0], [5.0, 5.0, 45.0, 35.0]))
    step("zx04_default_can_drag_box", bool(n1), str(bn))

    # ---------- 放大 ----------
    for _ in range(3):
        pg.click("#kbo-zin"); pg.wait_for_timeout(120)
    z_after_in = zpct()
    step("zx05_zoom_in_195", z_after_in == 195, f"zpct={z_after_in}%")
    w_px = pg.evaluate("document.getElementById('kbo-img').style.width")
    step("zx06_img_width_scaled", w_px.endswith("px") and int(w_px[:-2]) > W * 1.5, f"width={w_px}")

    # 放大态下框选坐标仍精确（canvas rect 已放大，归一化数学应不变）
    r = canvas_rect(); L, T, W, Hh = r
    drag(L + 0.6 * W, T + 0.6 * Hh, L + 0.85 * W, T + 0.85 * Hh)
    bn = boxes_norm()
    ok = len(bn) == 2 and all(abs(a - b) < 0.04 for a, b in zip(bn[1], [60.0, 60.0, 25.0, 25.0]))
    step("zx07_box_norm_correct_when_zoomed", bool(ok), str(bn))
    step("zx08_badges", badges() == ["1", "2"], str(badges()))
    pg.screenshot(path=str(SHOT_DIR / "b29_zoom_overlay.png"))

    # ---------- 滚轮缩小 ----------
    pg.mouse.move(L + W / 2, T + min(Hh, 400) / 2)
    pg.mouse.wheel(0, 240)  # deltaY>0 缩小
    pg.wait_for_timeout(300)
    z_wheel = zpct()
    step("zx09_wheel_zoom_out", 100 < z_wheel < 195, f"zpct={z_wheel}%")
    pg.click("#kbo-zfit"); pg.wait_for_timeout(250)
    step("zx10_fit_100", zpct() == 100, f"zpct={zpct()}%")

    # ---------- 放大 4x+ 后关闭框选 → 拖拽平移 ----------
    for _ in range(7):
        pg.click("#kbo-zin"); pg.wait_for_timeout(100)
    step("zx11_zoomed_large", zpct() > 300, f"zpct={zpct()}%")
    pg.click("#kbo-draw")  # 关闭框选
    pg.wait_for_timeout(200)
    step("zx12_draw_off", not pg.evaluate("document.getElementById('kbo-canvas').classList.contains('kbo-drawing')"))
    r = canvas_rect(); L, T, W, Hh = r
    # 放大 477% 后 canvas 宽远超视口：拖拽起点必须取 stage 可见区中心（保证落在 canvas 上且在窗口内）
    sr = pg.evaluate("() => { const s = document.getElementById('kbo-stage').getBoundingClientRect(); return [s.left, s.top, s.width, s.height]; }")
    before = pg.evaluate("() => { const s = document.getElementById('kbo-stage'); return [s.scrollLeft, s.scrollTop]; }")
    cx, cy = sr[0] + sr[2] / 2, sr[1] + min(sr[3] / 2, 300)
    drag(cx, cy, cx - 150, cy)  # 左拖 150px → 内容左移、scrollLeft 增大
    pg.wait_for_timeout(250)
    after = pg.evaluate("() => { const s = document.getElementById('kbo-stage'); return [s.scrollLeft, s.scrollTop]; }")
    step("zx13_pan_scroll_changed", after[0] - before[0] > 100, f"scroll {before} -> {after}")
    step("zx14_pan_no_new_box", len(boxes_norm()) == 2, str(boxes_norm()))

    # ---------- 简化确认文案（不提交，零 VL 消耗） ----------
    pg.click("#kbo-done")
    pg.wait_for_timeout(400)
    msg = next((m for m, a in reversed(dialogs) if "积分" in (m or "")), "")
    ok = ("积分" in msg and "版面分析" not in msg and "大模型" not in msg and "约 0.4" in msg)
    step("zx15_confirm_simple_text", ok, repr(msg[:80]))
    step("zx16_not_submitted", bool(until(
        "() => !document.getElementById('kbo').classList.contains('hidden')", loops=6, ms=200)))
    # 退出：返回列表 → 关弹窗（丢弃确认 accept）
    pg.click("#kbo-back"); pg.wait_for_timeout(300)
    pg.evaluate("document.querySelector('#kb-modal [data-mclose]').click()")
    pg.wait_for_timeout(400)
    step("zx17_no_pageerror", not pageerrs, str(pageerrs[:2]))

    b.close()

# ---------- 清理上传文件 ----------
for f in set(VAULT_SHOTS.glob("*")) - shots_before:
    try:
        os.remove(f)
    except OSError:
        pass

res_path = Path(r"e:\LLM\LectureLearnLoop\server\logs\kb_batch_zoom_verify.txt")
res_path.write_text("\n".join(lines) + f"\n\n{'ALL_PASS' if not fails else 'FAILED: ' + str(fails)}\n({time.time()-t0:.1f}s)\n", encoding="utf-8")
print("ALL_PASS" if not fails else "FAILED: " + str(fails))
