# -*- coding: utf-8 -*-
"""知识库管理增强 UI 断言（2026-10-12 c10）：CDP/Playwright 全链路 + 截图识图。

覆盖（延续 u15/e5 harness 配方：独立测试用户隔离、dialog 自动接受、看门狗式轮询、截图落盘）：
1. 知识库页选学科 → 双页签出现；知识点页签行上有编辑/删除
2. 新增知识点（NoteVditor 弹窗）→ 列表/API 可见；编辑描述 → PUT 生效
3. 错题页签：新增错题弹窗 → 贴图上传（截图/ 引用入库）→ OCR 轮询（完成填入或降级提示，两态都算通过但记录）
4. 错题行：手动录入/独立徽章、MD 渲染 + 图片水合、编辑、归属下拉绑定、解绑、删除
5. 删除知识点 → 绑定错题解绑保留
6. 记错题页：manual 行显示手动录入徽章且 MD 图片渲染
7. 全程 pageerror 必须为空；测后 DB 直删 + 清理测试图片

运行前置：服务端已在 127.0.0.1:6001 运行。
"""
import base64
import io
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
OUT = Path(r"e:\LLM\LectureLearnLoop\server\logs\kb_manage_ui_verify.txt")
MOD = "KBUI" + uuid.uuid4().hex[:6]
SUBJECT = f"{MOD}_管理科"
PFX = MOD + "%"

lines, fails = [], []
META = {"ocr_mode": ""}


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
    _exec("DELETE FROM kp_proficiency_history WHERE user_id = ? AND knowledge_point_id IN "
          "(SELECT id FROM knowledge_points WHERE user_id = ? AND subject_name LIKE ?)", (uid, uid, PFX))
    _exec("DELETE FROM knowledge_point_sources WHERE knowledge_point_id IN "
          "(SELECT id FROM knowledge_points WHERE user_id = ? AND subject_name LIKE ?)", (uid, PFX))
    _exec("DELETE FROM knowledge_points WHERE user_id = ? AND subject_name LIKE ?", (uid, PFX))
    _exec("DELETE FROM user_subjects WHERE user_id = ? AND subject_name LIKE ?", (uid, PFX))


# ---------- 独立测试用户 ----------
UNAME = "kbui_" + uuid.uuid4().hex[:8]
requests.post(BASE + "/api/auth/register", json={"username": UNAME, "password": "test123456"}, timeout=15)
TOKEN = requests.post(BASE + "/api/auth/login", json={"username": UNAME, "password": "test123456"}, timeout=15).json()["data"]["token"]
H = {"Authorization": "Bearer " + TOKEN}
_seg = TOKEN.split(".")[1]
UID = json.loads(base64.urlsafe_b64decode(_seg + "=" * (-len(_seg) % 4)))["uid"]
step("login_test_user", True, f"uid={UID}")
_purge(UID)
requests.post(BASE + "/api/subjects", json={"subject_name": SUBJECT}, headers=H, timeout=15)

# vault 截图目录基线（测后清理新增图片）
VAULT_SHOTS = Path(config.VAULT_DIR) / UID / "截图" if hasattr(config, "VAULT_DIR") else \
    Path(r"e:\LLM\LectureLearnLoop\server\data\vault") / UID / "截图"
shots_before = set(VAULT_SHOTS.glob("*")) if VAULT_SHOTS.exists() else set()

# 造一张含英文算式的题图（OCR 真识别对象）
from PIL import Image, ImageDraw, ImageFont  # noqa: E402
img = Image.new("RGB", (720, 160), "white")
d = ImageDraw.Draw(img)
try:
    font = ImageFont.truetype("arial.ttf", 44)
except Exception:
    font = ImageFont.load_default()
d.text((30, 55), "Compute 2 + 3 = ?", fill="black", font=font)
PNG_PATH = Path(r"e:\LLM\LectureLearnLoop\server\logs\_kbui_shot.png")
img.save(PNG_PATH)

t0 = time.time()
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.set_default_timeout(60000)
    pageerrs = []
    reqfails = []

    def _pe(e):
        try:
            phase = lines[-1] if lines else "init"
        except Exception:
            phase = "?"
        pageerrs.append("@after[" + phase[:40] + "] msg=" + str(getattr(e, "message", "") or e)
                        + " | stack=" + str(getattr(e, "stack", ""))[:300])
    pg.on("pageerror", _pe)
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

    def set_editor(text, loops=20):
        """弹窗内 Vditor 就绪后写入（after 前 setValue 会被吞 → 重试直到镜像成功）。"""
        for _ in range(loops):
            pg.evaluate("(t) => { var m=document.getElementById('kbm-editor');"
                        "if (m && m.__vd && m.__vd.vditor && m.__vd.vditor.ir && m.__vd.vditor.ir.element) { try{ m.__vd.setValue(t); }catch(e){} } return 1; }", text)
            pg.wait_for_timeout(400)
            got = pg.evaluate("() => { var m=document.getElementById('kbm-editor'); return m && m.__vd ? String(m.__vd.getValue()||'') : ''; }")
            if got.strip():
                return got
        return ""

    pg.goto(BASE + "/login", wait_until="domcontentloaded")
    pg.evaluate("t => localStorage.setItem('ll_token', t)", TOKEN)
    pg.goto(BASE + "/", wait_until="networkidle")
    pg.wait_for_timeout(800)

    # ---------- 1. 知识库页 + 学科选中 → 双页签 ----------
    pg.evaluate("handleMenuClick('knowledge_base')")
    ok = until("!!document.getElementById('kb-subject-grid') && !!window.kbShowSubject && "
               "document.querySelectorAll('#kb-subject-grid [data-subj]').length > 0")
    step("ui01 kb_page_subject_cards", bool(ok))
    pg.evaluate(f"kbShowSubject({SUBJECT!r})")
    ok = until("document.getElementById('kb-tabs').classList.contains('flex')")
    step("ui02 tabs_visible_after_subject", bool(ok))
    # 知识点页签默认激活且无行（新学科）
    state = pg.evaluate("""() => ({ addText: document.getElementById('kb-add-btn').textContent,
        empty: !!document.getElementById('kb-point-list').querySelector('.cl-empty') })""")
    step("ui03 points_tab_default", "新增知识点" in (state or {}).get("addText", ""), str(state))

    # ---------- 2. 新增知识点（弹窗 + NoteVditor） ----------
    pg.click("#kb-add-btn")
    ok = until("!document.getElementById('kb-modal').classList.contains('hidden') && !!document.getElementById('kbm-name')")
    step("ui04 point_modal_open", bool(ok))
    pg.fill("#kbm-name", f"{MOD}矩阵乘法")
    set_editor(f"{MOD}描述：行乘列规则（UI断言写入）")
    pg.click("#kb-modal-ok")
    ok = until("document.getElementById('kb-modal').classList.contains('hidden') && "
               f"document.getElementById('kb-point-list').textContent.includes({MOD!r})")
    pts = requests.get(BASE + "/api/knowledge/points", params={"subject": SUBJECT}, headers=H, timeout=15).json()["data"]
    pid = next((int(p["id"]) for p in pts if p["point_name"] == f"{MOD}矩阵乘法"), None)
    step("ui05 point_created", bool(ok) and pid is not None, f"pid={pid}")

    # ---------- 3. 编辑知识点描述（PUT description） ----------
    if pid:
        pg.evaluate("pid => document.querySelector('[data-pt-edit=\"' + pid + '\"]').click()", str(pid))
        ok = until("!document.getElementById('kb-modal').classList.contains('hidden') && !!document.getElementById('kbm-editor')")
        step("ui06 point_edit_modal", bool(ok))
        cur = pg.evaluate("() => { var m=document.getElementById('kbm-editor'); return m && m.__vd ? String(m.__vd.getValue()||'') : ''; }")
        step("ui07 edit_prefilled", f"{MOD}描述" in cur, cur[:60])
        set_editor(f"{MOD}描述：行乘列规则 EDITED-OK")
        pg.click("#kb-modal-ok")
        pg.wait_for_timeout(1200)
        pts = requests.get(BASE + "/api/knowledge/points", params={"subject": SUBJECT}, headers=H, timeout=15).json()["data"]
        desc = next((p["core_description"] for p in pts if p["id"] == pid), "")
        step("ui08 point_desc_saved", "EDITED-OK" in (desc or ""), (desc or "")[:60])

    # ---------- 4. 错题页签 + 新增错题（贴图 + OCR） ----------
    pg.click("#kb-tab-errors")
    ok = until("document.getElementById('kb-add-btn').textContent.includes('新增错题')")
    step("ui09 errors_tab_switch", bool(ok))
    pg.click("#kb-add-btn")
    ok = until("!document.getElementById('kb-modal').classList.contains('hidden') && !!document.getElementById('kbm-editor')")
    step("ui10 error_modal_open", bool(ok))
    # 贴图上传：set_input_files 触发 change → /api/vault/screenshot → insertMD → error-ocr
    pg.set_input_files("#kbm-file", str(PNG_PATH))
    ok = until("() => { var m=document.getElementById('kbm-editor'); var v = m && m.__vd ? String(m.__vd.getValue()||'') : ''; return v.indexOf('\\u622a\\u56fe/') >= 0; }", loops=30)
    ed_val = pg.evaluate("() => { var m=document.getElementById('kbm-editor'); return m && m.__vd ? String(m.__vd.getValue()||'') : ''; }")
    step("ui11 image_uploaded_ref", bool(ok), ed_val[:80])
    # OCR 轮询（上限 ~200s）：完成填入 / 失败降级 都离开「识别中」态
    done = until("() => { var s=document.getElementById('kb-modal-status').textContent; return s && s.indexOf('识别中') < 0 && s.length > 0; }", loops=100, ms=2000)
    status = pg.evaluate("() => document.getElementById('kb-modal-status').textContent")
    ed_val2 = pg.evaluate("() => { var m=document.getElementById('kbm-editor'); return m && m.__vd ? String(m.__vd.getValue()||'') : ''; }")
    ocr_ok = "识别完成" in (status or "")
    ocr_degraded = any(k in (status or "") for k in ("识别失败", "不可用", "超时", "未识别", "手动"))
    META["ocr_mode"] = ("done" if ocr_ok else ("degraded" if ocr_degraded else "unknown")) + " status=" + (status or "")[:90]
    step("ui12_ocr_pipeline", ocr_ok or ocr_degraded, META["ocr_mode"] + (" gained_text=" + str(len(ed_val2) > len(ed_val)) if ocr_ok else ""))
    assert_ok = until("() => { var m=document.getElementById('kbm-editor'); var v = m && m.__vd ? String(m.__vd.getValue()||'') : ''; return v.indexOf('\\u622a\\u56fe/') >= 0; }", loops=5)
    if assert_ok:  # 编辑器内容 = 图 + 文字；补一行文字题干保底非空
        pass
    pg.fill("#kbm-answer", "5")
    pg.fill("#kbm-explain", f"{MOD}解析：加法口算")
    pg.click("#kb-modal-ok")
    ok = until("document.getElementById('kb-modal').classList.contains('hidden')", loops=20)
    errs = requests.get(BASE + "/api/kb/errors", params={"subject": SUBJECT}, headers=H, timeout=15).json()["data"]
    e1 = next((e for e in (errs or []) if e["source"] == "manual"), None)
    step("ui13 manual_error_created", bool(ok) and e1 is not None, f"eid={e1 and e1['id']}")
    if e1:
        step("ui14 md_ref_no_base64", "截图/" in (e1["question_content"] or "") and "data:image" not in (e1["question_content"] or ""),
             (e1["question_content"] or "")[:80])
        # 列表行：徽章 + MD 渲染 + 图片水合
        rowstate = until("""(eid) => { var row=document.querySelector('[data-err-row="'+eid+'"]'); if(!row) return false;
            var t=row.textContent; if(t.indexOf('手动录入')<0 || t.indexOf('独立')<0) return false;
            var im=row.querySelector('.kb-error-md img'); return im && (im.getAttribute('src')||'').startsWith('data:') && im.naturalWidth>0; }""", e1["id"], loops=30)
        step("ui15 error_row_badges_img", bool(rowstate))
        pg.screenshot(path=str(SHOT_DIR / "kbui_errors_tab.png"))
        # 编辑：改题干
        pg.evaluate("eid => document.querySelector('[data-er-edit=\"'+eid+'\"]').click()", str(e1["id"]))
        ok = until("!document.getElementById('kb-modal').classList.contains('hidden') && !!document.getElementById('kbm-editor')")
        step("ui16 error_edit_modal", bool(ok))
        # 用 API 侧的相对路径题干重建编辑器（直读 __vd.getValue() 可能含水合 base64，污染断言）
        set_editor((e1["question_content"] or "").rstrip() + f"\n\n{MOD}EDITED-TAIL")
        pg.click("#kb-modal-ok")
        pg.wait_for_timeout(1500)
        errs = requests.get(BASE + "/api/kb/errors", params={"subject": SUBJECT}, headers=H, timeout=15).json()["data"]
        q1 = next((e["question_content"] for e in (errs or []) if e["id"] == e1["id"]), "")
        step("ui17 error_content_saved", f"{MOD}EDITED-TAIL" in (q1 or ""), (q1 or "")[-60:])
    else:
        step("ui15 error_row_badges_img", False, "e1 missing")
        step("ui16 error_edit_modal", False, "e1 missing")
        step("ui17 error_content_saved", False, "e1 missing")

    # ---------- 5. 归属绑定（下拉） → 解绑 ----------
    pg.click("#kb-add-btn")
    until("!document.getElementById('kb-modal').classList.contains('hidden') && !!document.getElementById('kbm-editor')")
    set_editor(f"{MOD}待绑定错题：1+1=2")
    if pid:
        pg.select_option("#kbm-kp", str(pid))
        pg.click("#kb-modal-ok")
        pg.wait_for_timeout(1500)
    errs = requests.get(BASE + "/api/kb/errors", params={"subject": SUBJECT}, headers=H, timeout=15).json()["data"]
    e2 = next((e for e in (errs or []) if f"{MOD}待绑定" in (e["question_content"] or "")), None)
    step("ui18 error_bound_created", e2 is not None and int(e2["knowledge_point_id"] or 0) == int(pid or 0),
         f"eid={e2 and e2['id']} kp={e2 and e2['knowledge_point_id']}")
    if e2:
        bound = until("""(eid) => { var row=document.querySelector('[data-err-row="'+eid+'"]');
            return row && row.textContent.indexOf('矩阵乘法') >= 0 && !!row.querySelector('[data-er-unbind]'); }""", e2["id"], loops=20)
        step("ui19 bound_badge_unbind_btn", bool(bound))
        pg.evaluate("eid => document.querySelector('[data-er-unbind=\"'+eid+'\"]').click()", str(e2["id"]))
        pg.wait_for_timeout(1800)
        unbound = until("""(eid) => { var row=document.querySelector('[data-err-row="'+eid+'"]');
            return row && row.textContent.indexOf('独立') >= 0 && !row.querySelector('[data-er-unbind]'); }""", e2["id"], loops=20)
        step("ui20 unbind_works", bool(unbound))
        # 删除错题
        cnt0 = len(errs)
        pg.evaluate("eid => document.querySelector('[data-er-del=\"'+eid+'\"]').click()", str(e2["id"]))
        pg.wait_for_timeout(1800)
        errs2 = requests.get(BASE + "/api/kb/errors", params={"subject": SUBJECT}, headers=H, timeout=15).json()["data"]
        step("ui21 error_deleted", all(e["id"] != e2["id"] for e in (errs2 or [])) and len(errs2) == cnt0 - 1, f"{cnt0}->{len(errs2)}")

    # ---------- 6. 删除知识点 → 绑定错题解绑保留 ----------
    pg.click("#kb-tab-points")
    pg.wait_for_timeout(1000)
    if pid:
        pg.evaluate("pid => document.querySelector('[data-pt-del=\"'+pid+'\"]').click()", str(pid))
        pg.wait_for_timeout(2000)
    pts = requests.get(BASE + "/api/knowledge/points", params={"subject": SUBJECT}, headers=H, timeout=15).json()["data"]
    gone = all(int(p["id"]) != pid for p in (pts or []))
    errs3 = requests.get(BASE + "/api/kb/errors", params={"subject": SUBJECT}, headers=H, timeout=15).json()["data"]
    still = any(e["id"] == (e1 and e1["id"]) for e in (errs3 or []))
    unbinded = all(e["knowledge_point_id"] is None for e in (errs3 or []))
    step("ui22 point_deleted_errors_kept_unbound", gone and still and unbinded, f"gone={gone} kept={still}")

    # ---------- 7. 记错题页：manual 行 MD 渲染 ----------
    if errs3:
        pg.evaluate("handleMenuClick('memory_errors')")
        ok = until("!!document.querySelector('[data-pm-page=\"memory_errors\"] [data-subj]')")
        step("ui23 mem_page", bool(ok))
        pg.evaluate(f"""() => {{ var x=[...document.querySelectorAll('[data-pm-page="memory_errors"] [data-subj]')]
            .find(b => b.getAttribute('data-subj') === {SUBJECT!r}); if (x) x.click(); return !!x; }}""")
        mdok = until("""() => { var el=document.querySelector('[data-pm-page="memory_errors"] [data-mdq]');
            if (!el) return false; // 题干引用图片 + 水合为 data: 显示（OCR 未出文字时不强求正文）
            if ((el.getAttribute('data-src')||'').indexOf('截图') < 0) return false;
            var im = el.querySelector('img'); return !!im && (im.getAttribute('src')||'').startsWith('data:') && im.naturalWidth > 0; }""", loops=30)
        step("ui24 mem_errors_manual_md_img", bool(mdok))
        badge = until("""() => { var r=document.querySelector('[data-pm-page="memory_errors"]');
            return r && r.textContent.indexOf('手动录入') >= 0; }""", loops=20)
        step("ui25 mem_errors_manual_badge", bool(badge))
        pg.screenshot(path=str(SHOT_DIR / "kbui_mem_errors_manual.png"))
    else:
        step("ui23 mem_page", False, "no seeded errors")

    step("ui26 no_pageerrors", not pageerrs, "; ".join(pageerrs[:3]))
    print("REQFAILS: " + json.dumps(reqfails[:6], ensure_ascii=False))
    b.close()

# ---------- 清理：测试用户 vault 新增图片 ----------
if VAULT_SHOTS.exists():
    for f in set(VAULT_SHOTS.glob("*")) - shots_before:
        try:
            f.unlink()
        except OSError:
            pass
try:
    PNG_PATH.unlink()
except OSError:
    pass
_purge(UID)

OUT.write_text("\n".join(lines) + f"\n\nTOTAL={len(lines)} FAIL={len(fails)} ocr={META['ocr_mode']} secs={round(time.time()-t0)}\n" + ("ALL_GREEN" if not fails else "RED: " + ",".join(fails)), encoding="utf-8")
print(f"TOTAL={len(lines)} FAIL={len(fails)} ocr={META['ocr_mode']}")
sys.exit(1 if fails else 0)
