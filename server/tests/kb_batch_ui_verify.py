# -*- coding: utf-8 -*-
"""知识库「批量新增错题」UI 真实动线断言（2026-10-14，Playwright headless + 截图落盘）。

动线（用户口述需求逐步核对）：
1. 错题页签 → 新增错题弹窗出现「单题录入 | 批量录入」双页签；批量页签隐藏「保存」按钮
2. 本地多选 2 图上传 → 列表就绪/勾选/删除按钮可见
3. 提取错题 → 全屏框选层：开启框选 → 拖拽画矩形 3 框（含 1 个 <24px 小框）→ 删除中间框
   → 徽章编号 1,3 不重排 → 再画 1 小框 → 编号 4；下一张图编号从 1 独立起算
4. 完成（confirm 自动接受）→ 进度条推进 → 结果列表：成功题默认勾选、失败题置灰「过小」
5. 入库 2 题 → API 校验错题记录；界面回上传态
6. 切回单题页签 → 「保存」按钮恢复可见（CodeReview Critical-1 回归）
7. 全程 pageerror 必须为空；截图存档 design/walkthrough

积分与外呼：测试用户 admin_adjust +200 积分；本批 4 框中仅 2 个成功框真实调用
Paddle+VL（各 1 积分/题），2 个小框在服务侧裁剪即失败，零外呼零扣分。

运行前置：服务端已在 BASE（默认 6001，可用环境变量 LL_TEST_BASE 覆盖）运行。
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

BASE = os.getenv("LL_TEST_BASE", "http://127.0.0.1:6001")
SHOT_DIR = Path(r"e:\LLM\LectureLearnLoop\design\walkthrough")
OUT = Path(r"e:\LLM\LectureLearnLoop\server\logs\kb_batch_ui_verify.txt")
MOD = "KBB" + uuid.uuid4().hex[:6]
SUBJECT = f"{MOD}_批量科"
PFX = MOD + "%"

lines, fails = [], []
META = {"stage_note": ""}


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


def _purge(uid):
    _exec("DELETE FROM error_proficiency_history WHERE error_question_id IN "
          "(SELECT id FROM error_questions WHERE user_id = ? AND subject_name LIKE ?)", (uid, PFX))
    _exec("DELETE FROM error_questions WHERE user_id = ? AND subject_name LIKE ?", (uid, PFX))
    _exec("DELETE FROM practice_records WHERE user_id = ? AND subject_name LIKE ?", (uid, PFX))
    _exec("DELETE FROM user_subjects WHERE user_id = ? AND subject_name LIKE ?", (uid, PFX))


# ---------- 独立测试用户 + 积分 ----------
from PIL import Image, ImageDraw, ImageFont  # noqa: E402
import credits_service as credits  # noqa: E402

UNAME = "kbb_" + uuid.uuid4().hex[:8]
requests.post(BASE + "/api/auth/register", json={"username": UNAME, "password": "test123456"}, timeout=15)
TOKEN = requests.post(BASE + "/api/auth/login", json={"username": UNAME, "password": "test123456"}, timeout=15).json()["data"]["token"]
H = {"Authorization": "Bearer " + TOKEN}
_seg = TOKEN.split(".")[1]
UID = json.loads(base64.urlsafe_b64decode(_seg + "=" * (-len(_seg) % 4)))["uid"]
credits.admin_adjust(str(UID), 200, "批量错题 UI 动线测试积分", "agent_kbb_ui")
step("login_test_user", True, f"uid={UID} 积分+200")
_purge(UID)
requests.post(BASE + "/api/subjects", json={"subject_name": SUBJECT}, headers=H, timeout=15)

VAULT_SHOTS = Path(config.VAULT_DIR) / str(UID) / "截图"
VAULT_SHOTS.mkdir(parents=True, exist_ok=True)
shots_before = set(VAULT_SHOTS.glob("*")) if VAULT_SHOTS.exists() else set()

# 图 A：720x160 含英文算式（成功框真识别对象）；图 B：200x120 空白（仅验证翻页+独立编号）
A_PATH = Path(r"e:\LLM\LectureLearnLoop\server\logs\_kbb_a.png")
B_PATH = Path(r"e:\LLM\LectureLearnLoop\server\logs\_kbb_b.png")
imgA = Image.new("RGB", (720, 160), "white")
dA = ImageDraw.Draw(imgA)
try:
    font = ImageFont.truetype("arial.ttf", 44)
except Exception:
    font = ImageFont.load_default()
dA.text((30, 55), "Compute 2 + 3 = ?", fill="black", font=font)
imgA.save(A_PATH)
Image.new("RGB", (200, 120), "white").save(B_PATH)

t0 = time.time()
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.set_default_timeout(60000)
    pageerrs, reqfails = [], []
    pg.on("pageerror", lambda e: pageerrs.append(str(getattr(e, "message", "") or e)[:300]))
    pg.on("requestfailed", lambda r: reqfails.append(r.url[:120] + " :: " + str(r.failure)))
    pg.on("dialog", lambda dlog: dlog.accept())

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

    def canvas_rect():
        return pg.evaluate("() => { const r = document.getElementById('kbo-canvas').getBoundingClientRect();"
                           "return [r.left, r.top, r.width, r.height]; }")

    def drag_box(x1, y1, x2, y2):
        pg.mouse.move(x1, y1); pg.mouse.down()
        pg.mouse.move(x2, y2, steps=6); pg.mouse.up()
        pg.wait_for_timeout(250)

    def badges():
        return pg.evaluate("() => Array.from(document.querySelectorAll('#kbo-canvas .kbo-n')).map(n => n.textContent.trim())")

    pg.goto(BASE + "/login", wait_until="domcontentloaded")
    pg.evaluate("t => localStorage.setItem('ll_token', t)", TOKEN)
    pg.goto(BASE + "/", wait_until="networkidle")
    pg.wait_for_timeout(800)

    # ---------- 1. 进入知识库 → 错题页签 → 新增错题 → 双页签 ----------
    pg.evaluate("handleMenuClick('knowledge_base')")
    ok = until("!!window.kbShowSubject && document.querySelectorAll('#kb-subject-grid [data-subj]').length > 0")
    step("ui01 kb_page_ready", bool(ok))
    pg.evaluate(f"kbShowSubject({SUBJECT!r})")
    pg.click("#kb-tab-errors")
    ok = until("document.getElementById('kb-add-btn').textContent.includes('新增错题')")
    step("ui02 errors_tab", bool(ok))
    pg.click("#kb-add-btn")
    ok = until("!document.getElementById('kb-modal').classList.contains('hidden') && !!document.getElementById('kbm-tabs')")
    step("ui03 err_modal_two_tabs", bool(ok))
    step("ui04_single_tab_default", bool(pg.evaluate(
        "() => !document.getElementById('kbm-single').classList.contains('hidden') && "
        "document.getElementById('kbm-batch').classList.contains('hidden') && "
        "!document.getElementById('kb-modal-ok').classList.contains('hidden')")))
    pg.click("#kbm-tabs [data-etab=batch]")
    ok = until("!document.getElementById('kbb-upload') && true" if False else
               "!!document.getElementById('kbb-upload') && !document.getElementById('kbm-batch').classList.contains('hidden')")
    hidden_ok = pg.evaluate("document.getElementById('kb-modal-ok').classList.contains('hidden')")
    step("ui05_batch_tab_shown_save_hidden", bool(ok) and bool(hidden_ok))
    pg.screenshot(path=str(SHOT_DIR / "b24_batch_tab.png"))

    # ---------- 2. 本地多选上传 2 图 ----------
    pg.set_input_files("#kbb-file", [str(A_PATH), str(B_PATH)])
    ok = until("() => { var s = document.getElementById('kbb-sum').textContent; "
               "return s.includes('2 张图片') && s.includes('就绪 2'); }", loops=40)
    cards = pg.evaluate("document.querySelectorAll('#kbb-list [data-bc]').length")
    step("ui06_upload_two_ready", bool(ok), f"sum_cards={cards}")
    step("ui07_checked_by_default", cards == 2 and pg.evaluate(
        "Array.from(document.querySelectorAll('#kbb-list [data-bc]')).every(c => c.checked)"))

    # ---------- 3. 提取错题 → 全屏框选 ----------
    pg.click("#kbb-extract")
    ok = until("() => { var e = document.getElementById('kbo'); "
               "return !e.classList.contains('hidden') && e.classList.contains('flex'); }")
    step("ui08_overlay_open", bool(ok))
    info1 = pg.evaluate("document.getElementById('kbo-info').textContent")
    step("ui09_overlay_info", "第 1 / 2 张" in (info1 or ""), info1)
    # 等图 A 真正解码完成再取 rect/起笔（headless 下 img 异步解码，拖拽中途画布变尺寸会使坐标错位）
    ok = until("() => { var im = document.getElementById('kbo-img'); "
               "return im.complete && im.naturalWidth === 720 && im.clientHeight > 100; }",
               loops=40, ms=250)
    step("ui09b_image_a_loaded", bool(ok))
    # 框选开关已改为进入即默认开启；这里做幂等保护：仅当未开启时才点一次
    if not pg.evaluate("document.getElementById('kbo-draw').classList.contains('cl-btn-primary')"):
        pg.click("#kbo-draw")  # 开启框选
    rect = canvas_rect()
    L, T, W, Hh = rect[0], rect[1], rect[2], rect[3]
    scale = W / 720.0  # 图 A 自然宽 720，显示按比例
    drag_box(L + 10 * scale, T + 10 * scale, L + 520 * scale, T + 150 * scale)      # 框1 成功区
    drag_box(L + 20 * scale, T + 30 * scale, L + 34 * scale, T + 44 * scale)        # 框2 14px 小框（起笔在框1内，服务端判过小）
    drag_box(L + 100 * scale, T + 30 * scale, L + 520 * scale, T + 150 * scale)     # 框3 覆盖同一文字区（与框1重叠，修复后框内起笔可记录）
    got = badges()
    step("ui10_three_boxes", got == ["1", "2", "3"], str(got))
    # 删除框2 → 编号不重排（剩 1,3）
    pg.evaluate("() => document.querySelectorAll('#kbo-canvas .kbo-del')[1].click()")
    pg.wait_for_timeout(300)
    got = badges()
    step("ui11_delete_no_renumber", got == ["1", "3"], str(got))
    drag_box(L + 300 * scale, T + 40 * scale, L + 314 * scale, T + 54 * scale)      # 框4 小框（起笔在框1/3内）：验证新框拿 4
    got = badges()
    step("ui12_new_box_seq4", got == ["1", "3", "4"], str(got))
    pg.screenshot(path=str(SHOT_DIR / "b25_overlay_boxes.png"))
    # 下一张：图 B，编号从 1 独立起算；必须等 img 异步换源完成再取 rect（否则坐标错位到旧图尺寸）
    pg.click("#kbo-next")
    ok = until("() => { var im = document.getElementById('kbo-img'); "
               "return im.complete && im.naturalWidth === 200 && im.naturalHeight === 120 && im.clientHeight > 60; }",
               loops=40, ms=250)
    step("ui13_next_image_loaded", bool(ok))
    info2 = pg.evaluate("document.getElementById('kbo-info').textContent")
    step("ui13b_next_image", "第 2 / 2 张" in (info2 or ""), info2)
    rect = canvas_rect()
    L2, T2, W2 = rect[0], rect[1], rect[2]
    sb = W2 / 200.0  # 图 B 自然宽 200，显示按比例
    drag_box(L2 + 20 * sb, T2 + 20 * sb, L2 + 40 * sb, T2 + 40 * sb)  # 自然 20px < 24px → 服务端「过小」零外呼
    got_b = badges()
    step("ui14_image_b_seq1", got_b == ["1"], str(got_b))
    pg.evaluate("() => { var s = document.getElementById('kbo-hint'); return 1; }")
    until("document.getElementById('kbo-next').disabled === true")
    step("ui15_last_next_disabled", bool(pg.evaluate("document.getElementById('kbo-next').disabled")))

    # ---------- 4. 完成 → 进度 → 结果列表 ----------
    pg.click("#kbo-done")  # confirm 自动接受（含积分提示文案）
    ok = until("() => { var e = document.getElementById('kbo'); "
               "return e.classList.contains('hidden') && !!document.getElementById('kbp-bar'); }")
    step("ui16_running_progress", bool(ok))
    # 记录一次中间进度（VL 真实调用需几十秒/题；小框即刻失败）
    pg.wait_for_timeout(6000)
    mid = pg.evaluate("() => document.getElementById('kbp-text') ? document.getElementById('kbp-text').textContent : ''")
    META["stage_note"] += f"mid_progress=[{mid}] "
    # 终态：结果页出现（4 题预算，上限约 6min）
    ok = until("!!document.getElementById('kbb-res')", loops=190, ms=2000)
    step("ui17_result_list", bool(ok))
    if not ok:
        st = pg.evaluate("() => document.getElementById('kbm-batch').textContent.slice(0, 200)")
        META["stage_note"] += f"stuck_body=[{st}]"
    pg.screenshot(path=str(SHOT_DIR / "b26_batch_result.png"))
    res = pg.evaluate("""() => ({
        chk: document.querySelectorAll('#kbb-res [data-rc]').length,
        checked: Array.from(document.querySelectorAll('#kbb-res [data-rc]')).filter(c => c.checked).length,
        failTxt: (document.getElementById('kbb-res').textContent.match(/过小/g) || []).length,
        head: document.getElementById('kbm-batch').querySelector('p').textContent,
    })""")
    step("ui18_two_ok_two_failed", res["chk"] == 2 and res["failTxt"] >= 2 and "成功 2" in res["head"], json.dumps(res, ensure_ascii=False)[:200])
    step("ui19_default_all_checked", res["checked"] == 2 and res["head"].startswith("识别完成"))
    # 全选取消 → 入库按钮禁用 → 恢复勾选
    pg.click("#kbb-all")
    pg.wait_for_timeout(300)
    dis = pg.evaluate("document.getElementById('kbb-save').disabled")
    pg.click("#kbb-all")
    pg.wait_for_timeout(300)
    dis2 = pg.evaluate("document.getElementById('kbb-save').disabled")
    step("ui20_select_all_toggle", bool(dis) and not bool(dis2), f"uncheck_disabled={dis} recheck_disabled={dis2}")

    # ---------- 5. 入库 ----------
    pg.click("#kbb-save")
    ok = until("() => { var e = document.getElementById('kbb-list'); "
               "return e && e.children.length === 0; }", loops=60)
    errs = requests.get(BASE + "/api/kb/errors", params={"subject": SUBJECT}, headers=H, timeout=15).json()["data"]
    step("ui21_saved_2_errors", len(errs) == 2 and ok, f"api_count={len(errs)}")
    step("ui22_saved_content", all((e.get("question_content") or "").strip() for e in errs))
    pg.screenshot(path=str(SHOT_DIR / "b27_batch_after_save.png"))

    # ---------- 6. 关弹窗重开：单题页签「保存」恢复（Critical-1 回归） ----------
    pg.evaluate("document.querySelector('#kb-modal [data-mclose]').click()")
    pg.wait_for_timeout(400)
    pg.click("#kb-add-btn")
    ok = until("!document.getElementById('kb-modal').classList.contains('hidden') && !!document.getElementById('kbm-tabs')")
    vis = pg.evaluate("!document.getElementById('kb-modal-ok').classList.contains('hidden')")
    step("ui23_save_btn_restored", bool(ok) and bool(vis))
    pg.evaluate("document.querySelector('#kb-modal [data-mclose]').click()")
    pg.wait_for_timeout(300)

    b.close()

step("ui90_no_pageerror", not pageerrs, str(pageerrs)[:300])

# ---------- 清理：DB 测试数据 + vault 新增图片 ----------
_purge(UID)
for f in (set(VAULT_SHOTS.glob("*")) - shots_before):
    try:
        f.unlink()
    except OSError:
        pass
A_PATH.unlink(missing_ok=True); B_PATH.unlink(missing_ok=True)

OUT.write_text("\n".join(lines) + f"\nMETA: {META}\n耗时 {round(time.time()-t0,1)}s\n"
               + ("ALL_PASS\n" if not fails else f"FAILS: {fails}\n"), encoding="utf-8")
print("RESULT:", "ALL_PASS" if not fails else f"FAILS={fails}", f"elapsed={round(time.time()-t0,1)}s")
