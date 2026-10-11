# -*- coding: utf-8 -*-
"""手机拍照传图 UI 断言（2026-10-13）：PC 弹窗出二维码 → 模拟手机上传 → 编辑器见图。

覆盖：
1. 错题弹窗点「手机拍照」→ 二维码区显示、QR canvas/img 渲染、地址 URL 正确
2. 手机页可经小服务打开（token 免登录）
3. 模拟手机 POST 真实 PNG → PC 轮询在 ~10s 内把 ![手机拍照] 图插入 Vditor 编辑器
4. 多图连拍：第二张同样到达且顺序不丢
5. 关闭弹窗 → 会话立即失效：手机再传返回 410
6. 全程无 pageerror；测后清理测试用户 vault 图片与 DB

运行前置：主服务 6001 + photo-drop 小服务（随主服务启动）。
"""
import base64
import io
import json
import re
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
OUT = Path(r"e:\LLM\LectureLearnLoop\server\logs\photo_drop_ui_verify.txt")
MOD = "PDUI" + uuid.uuid4().hex[:6]
SUBJECT = f"{MOD}_拍照科"
PFX = MOD + "%"

lines, fails = [], []


def step(name, ok, extra=""):
    lines.append(f"{'PASS' if ok else 'FAIL'} {name} {extra}")
    if not ok:
        fails.append(name)
    print(lines[-1])


def _exec(sql, params=None):
    c = db_adapter.get_connection(str(config.DB_PATH))
    try:
        c.cursor().execute(sql, params or ())
        c.commit()
    finally:
        c.close()


def _purge(uid):
    for sql in [
        "DELETE FROM error_questions WHERE user_id = ? AND subject_name LIKE ?",
        "DELETE FROM practice_records WHERE user_id = ? AND subject_name LIKE ?",
        "DELETE FROM knowledge_points WHERE user_id = ? AND subject_name LIKE ?",
        "DELETE FROM user_subjects WHERE user_id = ? AND subject_name LIKE ?",
    ]:
        _exec(sql, (uid, PFX))


def png_b64(color):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (160, 120), color).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


# ---------- 独立测试用户 ----------
UNAME = "pdui_" + uuid.uuid4().hex[:8]
requests.post(BASE + "/api/auth/register", json={"username": UNAME, "password": "test123456"}, timeout=15)
TOKEN = requests.post(BASE + "/api/auth/login", json={"username": UNAME, "password": "test123456"}, timeout=15).json()["data"]["token"]
H = {"Authorization": "Bearer " + TOKEN}
_seg = TOKEN.split(".")[1]
UID = json.loads(base64.urlsafe_b64decode(_seg + "=" * (-len(_seg) % 4)))["uid"]
_purge(UID)
requests.post(BASE + "/api/subjects", json={"subject_name": SUBJECT}, headers=H, timeout=15)
step("login_test_user", True, f"uid={UID}")

VAULT_SHOTS = Path(config.VAULT_DIR) / UID / "截图"
shots_before = set(VAULT_SHOTS.glob("*")) if VAULT_SHOTS.exists() else set()

t0 = time.time()
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.set_default_timeout(60000)
    pageerrs, reqfails = [], []
    pg.on("pageerror", lambda e: pageerrs.append(str(getattr(e, "message", "") or e)[:200]))
    pg.on("requestfailed", lambda r: reqfails.append(r.url[:120]))
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

    pg.goto(BASE + "/login", wait_until="domcontentloaded")
    pg.evaluate("t => localStorage.setItem('ll_token', t)", TOKEN)
    pg.goto(BASE + "/", wait_until="networkidle")
    pg.wait_for_timeout(800)

    # ---------- 1. 打开错题新增弹窗 ----------
    pg.evaluate("handleMenuClick('knowledge_base')")
    until("!!document.getElementById('kb-subject-grid') && !!window.kbShowSubject && "
          "document.querySelectorAll('#kb-subject-grid [data-subj]').length > 0", loops=40)
    pg.evaluate(f"kbShowSubject({SUBJECT!r})")
    until("document.getElementById('kb-tabs').classList.contains('flex')")
    pg.click("#kb-tab-errors")
    until("document.getElementById('kb-add-btn').textContent.includes('新增错题')")
    pg.click("#kb-add-btn")
    ok = until("!document.getElementById('kb-modal').classList.contains('hidden') && !!document.getElementById('kbm-photo')")
    step("ui01 error_modal_with_photo_btn", bool(ok))

    # ---------- 2. 点「手机拍照」→ 二维码渲染 ----------
    pg.click("#kbm-photo")
    ok = until("!document.getElementById('kbm-photo-zone').classList.contains('hidden') && "
               "!!document.querySelector('#kbm-qr canvas, #kbm-qr img')")
    step("ui02_qr_rendered", bool(ok))
    url = pg.evaluate("() => document.getElementById('kbm-qr-url').textContent") or ""
    m = re.match(r"https?://([\d.]+):(\d+)/c/([0-9a-f]{16})$", url)
    step("ui03_qr_url_shape", bool(m), url)
    opts = pg.evaluate("() => document.getElementById('kbm-qr-addr').options.length") or 0
    step("ui04_addr_candidates", opts >= 1, f"opts={opts}")
    pg.screenshot(path=str(SHOT_DIR / "photo_drop_modal.png"))

    if not m:
        b.close()
        OUT.write_text("\n".join(lines) + f"\n\nTOTAL={len(lines)} FAIL={len(fails)+1} (no url, abort)\n", encoding="utf-8")
        sys.exit(1)
    port, token = m.group(2), m.group(3)
    phone = f"http://127.0.0.1:{port}"

    # ---------- 3. 模拟手机：打开页 → 传两张图（连拍） ----------
    r = requests.get(phone + f"/c/{token}", timeout=10)
    step("ui05_phone_page_200", r.status_code == 200 and "拍照录入错题" in r.text)
    r1 = requests.post(phone + f"/c/{token}/upload", json={"image_b64": png_b64((200, 60, 60))}, timeout=15)
    rel1 = (r1.json() or {}).get("rel", "")
    step("ui06_upload1_ok", r1.status_code == 200 and rel1.startswith("截图/手机_"), rel1)

    def editor_val():
        return pg.evaluate("() => { var m=document.getElementById('kbm-editor'); return m && m.__vd ? String(m.__vd.getValue()||'') : ''; }")

    ok = until(f"() => {{ var m=document.getElementById('kbm-editor'); var v = m && m.__vd ? String(m.__vd.getValue()||'') : ''; return v.indexOf({('手机拍照](' + rel1)!r}) >= 0; }}", loops=30, ms=700)
    step("ui07_pc_editor_got_img1", bool(ok), (editor_val() or "")[:90])

    r2 = requests.post(phone + f"/c/{token}/upload", json={"image_b64": png_b64((60, 160, 60))}, timeout=15)
    rel2 = (r2.json() or {}).get("rel", "")
    ok = until(f"() => {{ var m=document.getElementById('kbm-editor'); var v = m && m.__vd ? String(m.__vd.getValue()||'') : ''; return v.indexOf({('手机拍照](' + rel2)!r}) >= 0; }}", loops=30, ms=700)
    step("ui08_burst_img2_arrives", bool(ok) and rel2 != rel1, rel2)
    pg.screenshot(path=str(SHOT_DIR / "photo_drop_editor.png"))

    # ---------- 4. 关弹窗 → 会话立失效 ----------
    # JS 直接触发按钮（data-mclose 有遮罩层，pointer click 会被拦截）
    pg.evaluate("() => { var bs = [...document.querySelectorAll('#kb-modal [data-mclose]')]; var b = bs.find(x => x.tagName === 'BUTTON') || bs[bs.length - 1]; if (b) b.click(); return bs.length; }")
    pg.wait_for_timeout(1500)  # 等前端 DELETE 生效
    r3 = requests.post(phone + f"/c/{token}/upload", json={"image_b64": png_b64((60, 60, 200))}, timeout=15)
    step("ui09_closed_kills_session", r3.status_code == 410, f"status={r3.status_code}")

    step("ui10 no_pageerrors", not pageerrs, "; ".join(pageerrs[:3]))
    print("REQFAILS: " + json.dumps(reqfails[:6], ensure_ascii=False))
    b.close()

# ---------- 清理 ----------
if VAULT_SHOTS.exists():
    for f in set(VAULT_SHOTS.glob("*")) - shots_before:
        try:
            f.unlink()
        except OSError:
            pass
_purge(UID)

OUT.write_text("\n".join(lines) + f"\n\nTOTAL={len(lines)} FAIL={len(fails)} secs={round(time.time()-t0)}\n"
               + ("ALL_GREEN" if not fails else "RED: " + ",".join(fails)), encoding="utf-8")
print(f"TOTAL={len(lines)} FAIL={len(fails)}")
sys.exit(1 if fails else 0)
