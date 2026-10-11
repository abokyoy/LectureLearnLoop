# -*- coding: utf-8 -*-
"""错题公式显示 UI 断言（2026-10-13）：Playwright 全链路 + 截图识图核对。

覆盖：
1. 本地 vendor KaTeX（window.katex 0.16.9）与 md_render.js 公共件已挂载
2. 知识库错题列表：题干/答案/解析内 .katex 渲染产物存在，$ 原文与占位符不残留
3. 编辑弹窗（NoteVditor engine=KaTeX）：编辑器内公式即时渲染
4. pageerror 必须为空；截图落盘识图核对
5. 测后 DB 清理（独立测试用户 + 前缀学科）

运行前置：服务端已在 127.0.0.1:6001 运行且已重启（模板改动需 Jinja 重载）。
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
OUT = Path(r"e:\LLM\LectureLearnLoop\server\logs\kb_math_ui_verify.txt")
MOD = "MATH" + uuid.uuid4().hex[:6]
SUBJECT = f"{MOD}_公式科"
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
    _try_exec("DELETE FROM error_proficiency_history WHERE error_question_id IN "
              "(SELECT id FROM error_questions WHERE user_id = ? AND subject_name LIKE ?)", (uid, PFX))
    _try_exec("DELETE FROM error_questions WHERE user_id = ? AND subject_name LIKE ?", (uid, PFX))


# ---------- 样例公式错题（题干含用户真实样例 + 块级公式；答案/解析含 $） ----------
STEM = ("已知关于 x 的方程 x^2 + (2 - m)x - m - 2 = 0 的两个根均小于 2，求整数 m 的最小值。"
        "解：求根公式 $x = \\frac{-(2-m) \\pm \\sqrt{(2-m)^2 - 4 \\cdot (-(m+2))}}{2}$，"
        "即 $x_1 = -m$，$x_2 = 2$。由题意 $-m < 2$ 得 $m > -2$。"
        "$$x = \\frac{2 - m \\pm |m+2|}{2}$$ 综上 $m \\geq -1$。")
ANSWER = "$m \\geq -1$（最小值 $-1$）"
EXPLAIN = ("## 我的解答（如实转录）\n误以为只需 $-m < 2$。"
           "\n## 错因分析\n漏掉前提 $m \\geq -2$ 的讨论分支，未对 $|m+2|$ 分类去绝对值。")

# ---------- 登录一次性测试用户（API 直录错题，避开 UI 录入耗时） ----------
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
r = requests.post(BASE + "/api/kb/errors", json={
    "subject_name": SUBJECT, "question": STEM, "correct_answer": ANSWER, "explanation": EXPLAIN,
}, headers=H, timeout=20)
step("seed_math_error", r.status_code == 200 and r.json().get("success"), r.text[:120])

t0 = time.time()
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

    # ---------- 1. 进入知识库，组件挂载（本地 vendor，不依赖 CDN） ----------
    pg.evaluate("handleMenuClick('knowledge_base')")
    ok = until("!!document.getElementById('kb-subject-grid') && !!window.kbShowSubject")
    step("ui00_kb_fragment_ready", bool(ok))
    libs = pg.evaluate("""() => ({
        katex: typeof window.katex !== 'undefined' ? (window.katex.version || 'yes') : null,
        md: !!(window.MdRender && window.MdRender.extract && window.MdRender.applyMath)
    })""")
    step("ui01_katex_local", bool(libs.get("katex")) and libs.get("md"), json.dumps(libs))

    # ---------- 2. 知识库错题列表：题干/答案/解析公式渲染 ----------
    pg.evaluate(f"kbShowSubject({SUBJECT!r})")
    until("document.getElementById('kb-tabs').classList.contains('flex')")
    pg.click("#kb-tab-errors")
    ok = until("""() => {
        var md = document.querySelector('.kb-error-md[data-md]');
        return md && md.querySelectorAll('.katex').length >= 7;
    }""", loops=40)
    stem_stat = pg.evaluate("""() => {
        var md = document.querySelector('.kb-error-md[data-md]');
        if (!md) return null;
        return {
            katex: md.querySelectorAll('.katex').length,
            display: md.querySelectorAll('.katex-display').length,
            rawDollar: (md.textContent.match(/\\$/g) || []).length,
            eoo: md.textContent.indexOf('\\uE000') >= 0,
            frac: !!md.querySelector('.katex .frac, .katex .mfrac') || md.textContent.indexOf('2−m') >= 0
        };
    }""")
    step("ui02_stem_katex_rendered", bool(stem_stat) and stem_stat["katex"] >= 7 and stem_stat["display"] >= 1,
         json.dumps(stem_stat, ensure_ascii=False))
    step("ui03_no_raw_dollar_no_placeholder", bool(stem_stat) and stem_stat["rawDollar"] == 0 and not stem_stat["eoo"],
         json.dumps(stem_stat, ensure_ascii=False))
    ae = pg.evaluate("""() => {
        var a = document.querySelector('[data-ans]'), x = document.querySelector('[data-exp]');
        return { ansK: a ? a.querySelectorAll('.katex').length : -1,
                 expK: x ? x.querySelectorAll('.katex').length : -1,
                 ansDollar: a ? (a.textContent.match(/\\$/g) || []).length : -1,
                 expEoo: x ? (x.textContent || '').indexOf('\\uE000') >= 0 : true };
    }""")
    # 解析含 3 条公式（多段落容器，回归验证 TreeWalker 两阶段修复）；答案 2 条
    step("ui04_answer_explain_rendered", bool(ae) and ae["ansK"] >= 2 and ae["expK"] >= 3 and ae["ansDollar"] == 0 and not ae["expEoo"],
         json.dumps(ae))
    pg.screenshot(path=str(SHOT_DIR / "kb_math_list.png"))

    # ---------- 3. 编辑弹窗：NoteVditor KaTeX 即时渲染 ----------
    pg.evaluate("""() => { var b = document.querySelector('[data-er-edit]'); if (b) b.click(); }""")
    ok = until("!document.getElementById('kb-modal').classList.contains('hidden') && !!document.getElementById('kbm-editor')")
    step("ui05_edit_modal_open", bool(ok))
    ok = until("""() => {
        var ed = document.getElementById('kbm-editor');
        return ed && ed.querySelectorAll('.katex').length >= 7;
    }""", loops=40)  # Vditor 异步链加载 katex→mhchem→渲染，需轮询；题干 7 条公式（行内 6 + 块级 1）
    ed_stat = pg.evaluate("""() => {
        var ed = document.getElementById('kbm-editor');
        if (!ed) return null;
        var md = ed.__vd && ed.__vd.getValue ? String(ed.__vd.getValue() || '') : '';
        return { katex: ed.querySelectorAll('.katex').length, mdHasDollar: md.indexOf('$') >= 0 };
    }""")
    step("ui06_vditor_math_render", bool(ed_stat) and ed_stat["katex"] >= 7, json.dumps(ed_stat, ensure_ascii=False))
    step("ui07_md_source_kept", bool(ed_stat) and ed_stat["mdHasDollar"], "取值仍是 MD 原文（公式 $ 定界保留）")
    pg.screenshot(path=str(SHOT_DIR / "kb_math_editor.png"))

    # ---------- 4. 错题练习页（无 marked/DOMPurify 依赖）：公式回退分支也要渲染（CodeReview Critical-1 回归） ----------
    pg.evaluate("() => { var m=document.querySelector('[data-modal-close]'); if (m) m.click(); }")
    pg.evaluate("() => { var c=document.getElementById('kbm-cancel'); if (c) c.click(); }")
    pg.wait_for_timeout(500)
    pg.evaluate("handleMenuClick('practice_errors')")
    ok = until("""() => {
        var box = document.querySelector('[data-pm-page="practice_errors"] [data-role="subjects"] [data-subj]');
        return !!box;
    }""", loops=40)
    step("ui09a_practice_page_ready", bool(ok))
    pg.evaluate(f"""() => {{
        var btns = document.querySelectorAll('[data-role="subjects"] [data-subj]');
        for (var i = 0; i < btns.length; i++) {{
            if (btns[i].getAttribute('data-subj') === {SUBJECT!r}) {{ btns[i].click(); return 1; }}
        }}
        return 0;
    }}""")
    ok = until("""() => {
        var els = document.querySelectorAll('[data-mdq]');
        for (var i = 0; i < els.length; i++) {{ if (els[i].querySelectorAll('.katex').length >= 7) return 1; }}
        return 0;
    }}""", loops=40)
    pe = pg.evaluate("""() => {
        var el = document.querySelector('[data-mdq]');
        if (!el) return null;
        var t = el.textContent || '';
        return { katex: el.querySelectorAll('.katex').length,
                 dollar: (t.match(/\\$/g) || []).length, eoo: t.indexOf('\\uE000') >= 0 };
    }""")
    step("ui09b_practice_math_fallback_render", bool(pe) and pe["katex"] >= 7 and pe["dollar"] == 0 and not pe["eoo"],
         json.dumps(pe, ensure_ascii=False))
    pg.screenshot(path=str(SHOT_DIR / "kb_math_practice.png"))

    b.close()

step("ui08_no_pageerror", not pageerrs, str(pageerrs[:2])[:160])

_purge(UID)
OUT.write_text("\n".join(lines) + f"\n\nELAPSED={time.time()-t0:.1f}s FAILS={fails}\n", encoding="utf-8")
print(f"== finish FAILS={fails} elapsed={time.time()-t0:.1f}s")
sys.exit(1 if fails else 0)
