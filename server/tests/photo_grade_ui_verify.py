# -*- coding: utf-8 -*-
"""简答题拍照判分（2026-10-15 用户需求）UI 断言 harness（模式同 error_unit_ui_verify.py）。

流程：真实用户链路——录入一道简答错题 → 「练这题」→ 作答区出现拍照上传按钮 →
上传 PIL 生成的手写解答照片（真实 /api/vault/screenshot 存 vault 截图/）→ 提交 →
真实视觉模型看图判分（与错题智能分析同链路）→ 结果面板显示点评与作答照片。

覆盖断言：
- pg01 简答卡带上传按钮/文件框；
- pg02 上传后缩略图经桥水合成 dataURL；
- pg03 视觉判分返回且判对（照片里明写 70°，与参考答案一致）；
- pg04 结果面板「你的答案」照片水合显示；
- pg05 判分走库：错题 FSRS 曲线 +1；
- pg90 无 pageerror。

运行前置：服务端已在 127.0.0.1:6001 运行（含拍照判分代码）。含 1 次真实视觉调用，
LLM 失败会如实 FAIL（不伪造通过）。
"""
import base64
import json
import shutil
import sys
import time
import uuid
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database import db_adapter  # noqa: E402
import config  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:6001"
SHOT_DIR = Path(r"e:\LLM\LectureLearnLoop\design\walkthrough")
OUT = Path(r"e:\LLM\LectureLearnLoop\server\logs\photo_grade_ui_verify.txt")
MOD = "PGUI" + uuid.uuid4().hex[:6]
SUBJECT = f"{MOD}_拍照判分科"
HAND_PNG = OUT.parent / f"pg_hand_answer_{MOD}.png"

lines, fails = [], []


def step(name, ok, extra=""):
    lines.append(f"{'PASS' if ok else 'FAIL'} {name} {extra}")
    if not ok:
        fails.append(name)
    print(lines[-1])


def _exec(sql, params=None):
    c = db_adapter.get_connection(str(config.DB_PATH))
    try:
        cur = c.cursor()
        cur.execute(sql, params or ())
        c.commit()
    finally:
        c.close()


def _try_exec(sql, params=None):
    try:
        _exec(sql, params)
    except Exception:  # noqa: BLE001 清理容错
        pass


def _purge(uid):
    for t in ("error_proficiency_history", "kp_proficiency_history", "fsrs_states",
              "error_questions", "practice_records", "weakness_reports"):
        _try_exec(f"DELETE FROM {t} WHERE user_id = ?", (uid,))


# ---------- 手写解答照片（34 字内中文行，白底黑字，视觉模型可辨识） ----------
def make_hand_png(path):
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new("RGB", (1100, 320), "white")
    d = ImageDraw.Draw(im)
    font = None
    for fp in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
               "C:/Windows/Fonts/simsun.ttc"):
        try:
            font = ImageFont.truetype(fp, 32)
            break
        except Exception:  # noqa: BLE001 逐字体兜底
            continue
    texts = ["解：因为 AB=AC，所以 ∠B=∠C（等腰三角形底角相等）",
             "又 ∠A=40°，三角形内角和 180°",
             "所以 ∠B=(180°-40°)/2=140°/2=70°",
             "答：∠B=70°"]
    y = 24
    for t in texts:
        d.text((28, y), t, fill="black", font=font)
        y += 68
    im.save(path)


make_hand_png(HAND_PNG)

# ---------- 一次性用户 + 一道简答错题（API 直录，零 LLM） ----------
UNAME = MOD.lower()
requests.post(BASE + "/api/auth/register", json={"username": UNAME, "password": "test123456"}, timeout=15)
TOKEN = requests.post(BASE + "/api/auth/login", json={"username": UNAME, "password": "test123456"},
                      timeout=15).json()["data"]["token"]
H = {"Authorization": "Bearer " + TOKEN}
_seg = TOKEN.split(".")[1]
UID = json.loads(base64.urlsafe_b64decode(_seg + "=" * (-len(_seg) % 4)))["uid"]
_purge(UID)
r = requests.post(BASE + "/api/knowledge/point-new", headers=H, timeout=30, json={
    "point": {"name": "等腰三角形内角", "description": "等腰三角形底角相等与内角和定理"},
    "subject": SUBJECT})
PID = int(r.json()["data"]["knowledge_id"])
step("seed_point", r.json().get("success"), f"pid={PID}")

r = requests.post(BASE + "/api/practice/results", headers=H, timeout=30, json={"records": [{
    "subject_name": SUBJECT, "knowledge_point_id": PID,
    "question_content": "在三角形 ABC 中，∠A=40°，AB=AC。求 ∠B 的度数？（写出解题过程）",
    "user_answer": "", "is_correct": False, "correct_answer": "70°",
    "explanation": "等腰三角形两底角相等，(180°-40°)/2=70°", "question_type": "short",
}]})
step("seed_short_error", r.json().get("success"), r.text[:80])
errs = requests.get(BASE + "/api/kb/errors", headers=H, timeout=30, params={"subject": SUBJECT}).json()["data"]
EID = errs[0]["id"] if errs else None
step("seed_one_row", bool(EID))


def _curve_count():
    c = requests.get(BASE + f"/api/kb/error/{EID}/curve", headers=H, timeout=30).json()["data"]
    return c.get("count")


t0 = time.time()
from playwright.sync_api import sync_playwright  # noqa: E402

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.set_default_timeout(60000)
    pageerrs = []
    pg.on("pageerror", lambda e: pageerrs.append(str(getattr(e, "message", "") or e)[:200]))
    pg.on("dialog", lambda dl: dl.accept())

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

    # ---------- 1. 进入错题练习页 → 练这题（简答卡） ----------
    pg.evaluate("handleMenuClick('practice_errors')")
    ok = until(f"""() => {{
        var btns = document.querySelectorAll('[data-pm-page="practice_errors"] [data-role="subjects"] [data-subj]');
        for (var i = 0; i < btns.length; i++) {{
            if (btns[i].getAttribute('data-subj') === {SUBJECT!r}) {{ btns[i].click(); return 1; }}
        }}
        return 0;
    }}""", loops=40)
    step("pg00_page_ready", bool(ok))
    # 行级按钮在卡片展开区：先展开首卡再点「练这题」（同 error_unit 流程）
    pg.evaluate("() => { var t = document.querySelector('[data-pm-page=\"practice_errors\"] [data-eid] .pm-q-toggle'); if (t) t.click(); }")
    pg.wait_for_timeout(600)
    ok = until("!!document.querySelector('[data-pm-page=\"practice_errors\"] [data-pp-single]')", loops=20)
    step("pg00b_single_btn_visible", bool(ok))
    pg.evaluate("() => document.querySelector('[data-pp-single]').click()")
    ok = until("""() => {
        var c = document.querySelector('[data-pp-overlay] [data-pp-card]');
        return c && c.textContent.indexOf('第 1/1 题') >= 0
            && !!c.querySelector('textarea[data-pp-text]');
    }""", loops=40)
    step("pg01_short_textarea", bool(ok))
    has_btn = pg.evaluate("""() => {
        var c = document.querySelector('[data-pp-overlay] [data-pp-card]');
        return !!(c && c.querySelector('[data-pp-photo]') && c.querySelector('[data-pp-photo-input]'));
    }""")
    step("pg01b_photo_controls", has_btn)

    # ---------- 2. 填文字 + 真实上传手写照片（file chooser 用户路径） ----------
    pg.fill("[data-pp-overlay] textarea[data-pp-text]", "我把完整解题过程写在纸上了，见照片。")
    with pg.expect_file_chooser() as fc_info:
        pg.click("[data-pp-overlay] [data-pp-photo]")
    fc_info.value.set_files(str(HAND_PNG))
    ok = until("""() => {
        var im = document.querySelector('[data-pp-overlay] [data-pp-photo-prev] img');
        var s = im ? (im.getAttribute('src') || '') : '';
        return s.indexOf('data:image') === 0 && s.length > 500 ? 1 : 0;
    }""", loops=40)
    step("pg02_upload_thumb", bool(ok))
    pg.screenshot(path=str(SHOT_DIR / "pg_practice_upload.png"))

    # ---------- 3. 提交 → 真实视觉模型看图判分 ----------
    before = _curve_count()
    pg.click("[data-pp-overlay] [data-pp-next]")
    ok = until("""() => {
        var c = document.querySelector('[data-pp-overlay] [data-pp-card]');
        if (!c) return 0;
        if (c.textContent.indexOf('判分结果') >= 0) return 'done';
        if (c.textContent.indexOf('失败') >= 0) return 'fail:' + c.textContent.slice(0, 160);
        return 0;
    }""", loops=180, ms=1000)
    step("pg03_vision_graded", ok == "done", str(ok))
    stat = pg.evaluate("""() => {
        var c = document.querySelector('[data-pp-overlay] [data-pp-card]');
        if (!c) return null;
        var t = c.textContent || '';
        var img = null, imgs = c.querySelectorAll('img');
        for (var i = 0; i < imgs.length; i++) {
            var s = imgs[i].getAttribute('src') || '';
            if (s.indexOf('data:image') === 0 && s.length > 500) { img = 1; break; }
        }
        return { right: t.indexOf('答对 1/1') >= 0, comment: t.indexOf('AI 点评') >= 0,
                 photoShown: !!img, has70: t.indexOf('70') >= 0 };
    }""")
    step("pg03b_graded_correct_by_photo", bool(stat) and stat["right"] and stat["comment"],
         json.dumps(stat, ensure_ascii=False))
    # 结果面板照片经桥异步水合，轮询等待（与列表图同一条 /api/vault/image 链）
    ok = until("""() => {
        var c = document.querySelector('[data-pp-overlay] [data-pp-card]');
        if (!c) return 0;
        var imgs = c.querySelectorAll('img');
        for (var i = 0; i < imgs.length; i++) {
            var s = imgs[i].getAttribute('src') || '';
            if (s.indexOf('data:image') === 0 && s.length > 500) return 1;
        }
        return 0;
    }""", loops=30)
    step("pg04_result_photo_shown", bool(ok))
    if not ok:  # 取证：卡内 img 与 mdq 插槽状态（区分产品缺口 vs 断言口径）
        diag = pg.evaluate("""() => {
            var c = document.querySelector('[data-pp-overlay] [data-pp-card]');
            if (!c) return null;
            var out = [];
            c.querySelectorAll('img').forEach(function (im) {
                var s = im.getAttribute('src') || '';
                out.push({ head: s.slice(0, 48), len: s.length, alt: im.getAttribute('alt'),
                           inMdq: !!im.closest('[data-mdq]'), done: im.closest('[data-mdq]') ? im.closest('[data-mdq]').getAttribute('data-done') : null });
            });
            return { imgs: out, pyb: !!window.pybridge, uaHtml: (function () {
                var el = c.querySelector('[data-mdq]');
                var best = '';
                c.querySelectorAll('[data-mdq]').forEach(function (x) { var h = x.innerHTML; if (h.indexOf('img') >= 0 && h.length > best.length) best = h; });
                return best.slice(0, 300); })() };
        }""")
        step("pg04_diag", True, json.dumps(diag, ensure_ascii=False)[:600])
    pg.screenshot(path=str(SHOT_DIR / "pg_result_vision.png"))
    pg.evaluate("() => { var x = document.querySelector('[data-pp-overlay] [data-pp-close]'); if (x) x.click(); }")
    pg.wait_for_timeout(1200)

    # ---------- 4. 判分走库：曲线历史 +1（答对 rating 正常进 FSRS 复习） ----------
    after = _curve_count()
    step("pg05_curve_plus_one", (before or 0) + 1 == (after or 0), f"{before}->{after}")

    b.close()

step("pg90_no_pageerror", not pageerrs, str(pageerrs[:2])[:200])

_purge(UID)
try:
    shutil.rmtree(Path(config.VAULT_DIR) / str(UID), ignore_errors=True)  # 一次性用户 vault（含上传照片）
except Exception:  # noqa: BLE001
    pass
HAND_PNG.unlink(missing_ok=True)
OUT.write_text("\n".join(lines) + f"\n\nELAPSED={time.time()-t0:.1f}s FAILS={fails}\n", encoding="utf-8")
print(f"== finish FAILS={fails} elapsed={time.time()-t0:.1f}s")
sys.exit(1 if fails else 0)
