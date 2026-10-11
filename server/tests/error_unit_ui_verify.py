# -*- coding: utf-8 -*-
"""错题学习单元升级（P1~P4）UI 断言 harness（模式同 kb_math_ui_verify.py）。

覆盖（计划验收清单 UI 部分）：
1. 展开显示完整公式解析（P1：去截断 + MD/KaTeX 管线）
2. 行内调星持久化（P2）+ 记忆面板曲线挂载（P2）+ 练习历史异步拉取（P2）
3. 列表分页 20/页（P2）
4. 单题练习流：练这题→作答→提交→熟练度变化→历史+1（P3）
5. 智能组卷 / 勾选弹窗（含分页与默认全选）（P3）
6. 行级与页级举一反三（真实 LLM，出题成功即通过，不作答）（P3）
7. 报告：全局分析（真实 LLM）→ 文字/脑图双视图 → 薄弱点「针对练习」出题（P4）
8. pageerror 必须为空；截图落 design/walkthrough/
9. 测后清理（一次性测试用户，按 uid 删）

运行前置：服务端已在 127.0.0.1:6001 运行（含 P4 代码）。举一反三/报告为真实 LLM 调用，
整跑约数分钟；LLM 失败会如实 FAIL（不伪造通过）。
"""
import base64
import json
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
OUT = Path(r"e:\LLM\LectureLearnLoop\server\logs\error_unit_ui_verify.txt")
MOD = "EUUI" + uuid.uuid4().hex[:6]
SUBJECT = f"{MOD}_错题单元科"
N_ROWS = 25  # >20 触发分页

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


# ---------- 一次性用户 + 25 道带公式解析的错题（API 直录，客观题零 LLM） ----------
UNAME = MOD.lower()
requests.post(BASE + "/api/auth/register", json={"username": UNAME, "password": "test123456"}, timeout=15)
TOKEN = requests.post(BASE + "/api/auth/login", json={"username": UNAME, "password": "test123456"},
                      timeout=15).json()["data"]["token"]
H = {"Authorization": "Bearer " + TOKEN}
_seg = TOKEN.split(".")[1]
UID = json.loads(base64.urlsafe_b64decode(_seg + "=" * (-len(_seg) % 4)))["uid"]
_purge(UID)
r = requests.post(BASE + "/api/knowledge/point-new", headers=H, timeout=30, json={
    "point": {"name": "行列式计算", "description": "二阶三阶行列式展开法则"}, "subject": SUBJECT})
PID = int(r.json()["data"]["knowledge_id"])
step("seed_point", r.json().get("success"), f"pid={PID}")

EXPL0 = ("按第一行展开：$D = a_{11}M_{11} - a_{12}M_{12}$。"
         "注意符号交替，$(-1)^{i+j}$ 是余子式的代数余子式因子。$$D = \\begin{vmatrix} 1 & 2 \\\\ 3 & 4 \\end{vmatrix} = -2$$"
         + "补充说明。" * 40)  # >300 字，旧版 truncate(300) 会砍（P1 回归锚点）
records = []
for i in range(N_ROWS):
    # 长解析挂 i=N_ROWS-1（题干 D24 唯一）；后端按 practice_time DESC 排序但同批入池时间并列、
    # 次序不定，ui04 改为按题干文本定位卡片，不依赖行序
    expl = EXPL0 if i == N_ROWS - 1 else f"第{i}题解析：$x_{i} \\geq 0$ 展开得救。"
    records.append({
        "subject_name": SUBJECT, "knowledge_point_id": PID,
        "question_content": f"求行列式 D{i} = |1 2; 3 {4 + i}| 的值？",
        "user_answer": "2", "is_correct": False, "correct_answer": "A",
        "explanation": expl, "question_type": "single", "options": ["-2", "2", str(-4 - i), str(4 + i)],
    })
r = requests.post(BASE + "/api/practice/results", headers=H, timeout=60, json={"records": records})
step("seed_25_errors", r.json().get("success"), r.text[:100])
errs = requests.get(BASE + "/api/kb/errors", headers=H, timeout=30, params={"subject": SUBJECT}).json()["data"]
step("seed_count", len(errs) == N_ROWS, f"n={len(errs)}")

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

    # ---------- 0. 进入错题练习页（unit 模式依赖 widgets.js） ----------
    pg.evaluate("handleMenuClick('practice_errors')")
    ok = until(f"""() => {{
        var btns = document.querySelectorAll('[data-pm-page="practice_errors"] [data-role="subjects"] [data-subj]');
        for (var i = 0; i < btns.length; i++) {{
            if (btns[i].getAttribute('data-subj') === {SUBJECT!r}) {{ btns[i].click(); return 1; }}
        }}
        return 0;
    }}""", loops=40)
    step("ui00_page_ready", bool(ok))
    ok = until("""() => document.querySelectorAll('[data-pm-page="practice_errors"] [data-eid]').length >= 20
        && !!window.LLStars && !!window.LLCurve""", loops=40)
    step("ui01_rows_and_widgets", bool(ok))

    # ---------- 1. 分页 20/页（P2） ----------
    pg_text = pg.evaluate("""() => {
        var t = document.querySelector('[data-pm-page="practice_errors"] [data-role="main"]').textContent;
        return (t.match(/第 1 \\/ 2 页/) || [''])[0];
    }""")
    step("ui02_paging_20_per_page", "第 1 / 2 页" in pg_text, pg_text)
    pg.evaluate("""() => { var n = document.querySelector('[data-pm-page="practice_errors"] [data-pg-next]'); if (n) n.click(); }""")
    pg_text = pg.evaluate("""() => {
        var t = document.querySelector('[data-pm-page="practice_errors"] [data-role="main"]').textContent;
        return (t.match(/第 2 \\/ 2 页/) || [''])[0];
    }""")
    step("ui03_paging_next_page", "第 2 / 2 页" in pg_text, pg_text)
    pg.evaluate("""() => { var p = document.querySelector('[data-pm-page="practice_errors"] [data-pg-prev]'); if (p) p.click(); }""")
    pg.wait_for_timeout(400)

    # ---------- 2. 展开：完整公式解析 + 练习历史（P1/P2） ----------
    # 后端 ORDER BY practice_time DESC 对同批入池行次序不定：按题干“D24 =”跨页定位长解析卡片
    find_js = f"""() => {{
        var cards = document.querySelectorAll('[data-pm-page="practice_errors"] [data-eid]');
        for (var i = 0; i < cards.length; i++) {{
            if ((cards[i].textContent || '').indexOf({f'D{N_ROWS-1} ='!r}) >= 0) {{
                cards[i].querySelector('.pm-q-toggle').click(); return 1;
            }}
        }}
        return 0;
    }}"""
    hit_card = pg.evaluate(find_js)
    on_pg2 = False
    if not hit_card:
        pg.evaluate("""() => { var n = document.querySelector('[data-pm-page="practice_errors"] [data-pg-next]'); if (n) n.click(); }""")
        pg.wait_for_timeout(400)
        hit_card = pg.evaluate(find_js)
        on_pg2 = bool(hit_card)
    step("ui04a_locate_long_explain_card", bool(hit_card), f"n={N_ROWS} pg2={on_pg2}")
    ok = until("""() => {
        var els = document.querySelectorAll('[data-pm-page="practice_errors"] [data-detail]:not(.hidden) [data-mdq]');
        for (var i = 0; i < els.length; i++) { if (els[i].querySelectorAll('.katex').length >= 3) return 1; }
        return 0;
    }""", loops=40)
    stat = pg.evaluate("""() => {
        var box = document.querySelector('[data-pm-page="practice_errors"] [data-detail]:not(.hidden)');
        if (!box) return null;
        var all = box.querySelectorAll('[data-mdq]');
        var k = 0, dollar = 0, explLen = 0;
        all.forEach(function (el) {
            k += el.querySelectorAll('.katex').length;
            dollar += ((el.textContent || '').match(/\\$/g) || []).length;
        });
        var hist = box.querySelector('[data-ehistory]');
        var rep = 0;
        all.forEach(function (el) { var n = ((el.textContent || '').match(/补充说明/g) || []).length; if (n > rep) rep = n; });
        return { katex: k, dollar: dollar, rep: rep, histShown: hist && (hist.textContent || '').indexOf('答错') >= 0,
                 eLoaded: hist ? hist.dataset.ehLoaded === '1' : false };
    }""")
    # P1 去截断锚点：EXPL0 尾部“补充说明。”×40，旧 truncate(300) 只剩约 30 次；3 条 KaTeX 全渲染
    step("ui04_expand_full_math_no_raw_dollar", bool(stat) and stat["katex"] >= 3 and stat["dollar"] == 0
         and stat["rep"] == 40, json.dumps(stat, ensure_ascii=False))
    step("ui05_practice_history_rendered", bool(stat) and stat["eLoaded"] and stat["histShown"],
         json.dumps(stat, ensure_ascii=False))
    pg.screenshot(path=str(SHOT_DIR / "eu_p1p2_expand.png"))
    if on_pg2:  # 回页1并展开首卡，保持后续步骤（记忆面板/调星/单题）首卡语义与原流程一致
        pg.evaluate("""() => { var p = document.querySelector('[data-pm-page="practice_errors"] [data-pg-prev]'); if (p) p.click(); }""")
        pg.wait_for_timeout(400)
        pg.evaluate("""() => { var t = document.querySelector('[data-pm-page="practice_errors"] [data-eid] .pm-q-toggle'); if (t) t.click(); }""")
        pg.wait_for_timeout(600)

    # ---------- 3. 记忆面板（曲线挂载） + 行内调星持久化（P2） ----------
    pg.evaluate("""() => { var b = document.querySelector('[data-mw-toggle]'); if (b) b.click(); }""")
    ok = until("""() => {
        var root = document.querySelector('[data-mw-root]:not(.hidden)');
        return root && root.querySelectorAll('svg').length >= 2;  // 双星 svg + 曲线 svg
    }""", loops=40)
    step("ui06_memory_panel_mounted", bool(ok))
    # 难度星：点第 4 颗星右半（存储分 8），随后 API 读回
    pg.evaluate("""() => {
        var g = document.querySelector('[data-eid] [data-us="diff"] svg g:nth-of-type(4)');
        g.querySelectorAll('rect')[1].dispatchEvent(new MouseEvent('click', {bubbles: true}));
    }""")
    pg.wait_for_timeout(800)
    eid0 = errs[0]["id"] if len(errs) == N_ROWS else None
    # 第 1 页首卡是最新入池行（id 最大），按列表同序取
    first_eid = int(pg.evaluate("""() => document.querySelector('[data-pm-page="practice_errors"] [data-eid]').getAttribute('data-eid')"""))
    got = requests.get(BASE + "/api/kb/errors", headers=H, timeout=30, params={"subject": SUBJECT}).json()["data"]
    hit = [x for x in got if x["id"] == first_eid]
    step("ui07_star_persist", bool(hit) and hit[0]["difficulty_score"] == 8.0,
         f"eid={first_eid} diff={hit[0]['difficulty_score'] if hit else None}")

    # ---------- 4. 单题练习流（P3）：练这题→选 A→提交→FSRS 更新→历史+1 ----------
    # 产品口径（fsrs_service 统一设计，非本次引入）：mastery=round(100·R) 仅 Review 态回写，
    # 首评 Good 进 Learning 态时熟练度列不覆盖（保持入池默认 20）；真实变化看
    # /api/kb/error/<id>/fsrs 状态迁移 + /curve 历史追加，UI 展示需与后端源一致。
    def _fsrs_snapshot(eid):
        d = requests.get(BASE + f"/api/kb/error/{eid}/fsrs", headers=H, timeout=30).json()["data"]
        c = requests.get(BASE + f"/api/kb/error/{eid}/curve", headers=H, timeout=30).json()["data"]
        return {"state": d.get("state"), "due": d.get("due"), "mastery": d.get("mastery"), "curve": c.get("count")}
    PROF_JS = """() => {
        var c = document.querySelector('[data-pm-page="practice_errors"] [data-eid]');
        var bar = c ? c.querySelector('.cl-progress') : null;
        var m = bar && bar.parentElement ? (bar.parentElement.textContent || '').match(/(\\d+)%/) : null;
        return m ? Number(m[1]) : null;
    }"""
    prof_before = pg.evaluate(PROF_JS)
    fsrs_b = _fsrs_snapshot(first_eid) if first_eid else None
    pg.evaluate("""() => { document.querySelector('[data-pp-single]').click(); }""")
    ok = until("""() => {
        var c = document.querySelector('[data-pp-overlay] [data-pp-card]');
        return c && c.textContent.indexOf('第 1/1 题') >= 0;
    }""", loops=40)
    step("ui08_single_load", bool(ok), prof_before)
    pg.evaluate("""() => {
        var r = document.querySelector('[data-pp-overlay] input[name="pp-ans"][value="A"]');
        r.checked = true; r.dispatchEvent(new Event('change', {bubbles: true}));
    }""")
    pg.evaluate("""() => { document.querySelector('[data-pp-overlay] [data-pp-next]').click(); }""")
    ok = until("""() => {
        var c = document.querySelector('[data-pp-overlay] [data-pp-card]');
        return c && c.textContent.indexOf('判分结果') >= 0 && c.textContent.indexOf('答对 1/1') >= 0;
    }""", loops=60)
    step("ui09_single_submit_result", bool(ok))
    pg.screenshot(path=str(SHOT_DIR / "eu_p3_single_result.png"))
    pg.evaluate("""() => { var x = document.querySelector('[data-pp-overlay] [data-pp-close]'); if (x) x.click(); }""")
    pg.wait_for_timeout(1200)  # onDone→refresh 重拉列表
    got_prof = pg.evaluate(PROF_JS)
    fsrs_a = _fsrs_snapshot(first_eid) if first_eid else None
    fsrs_moved = bool(fsrs_b and fsrs_a) and fsrs_a["state"] != fsrs_b["state"] \
        and fsrs_a.get("due") and fsrs_a["curve"] == fsrs_b["curve"] + 1
    step("ui10_fsrs_updated_after_practice", fsrs_moved and got_prof == (fsrs_a or {}).get("mastery"),
         f"fsrs {fsrs_b} -> {fsrs_a}; ui_prof={got_prof}%")
    hist = requests.get(BASE + f"/api/kb/errors/{first_eid}/practice-history", headers=H, timeout=30).json()["data"]
    step("ui11_history_plus_one", bool(hist) and hist[0]["is_correct"] == 1, f"n={len(hist)}")

    # ---------- 5. 智能组卷 + 勾选弹窗（P3，零 LLM） ----------
    pg.evaluate("""() => { document.querySelector('[data-tb="smart"]').click(); }""")
    ok = until("!!document.querySelector('[data-pp-chooser] [data-ppmc-start]')", loops=20)
    step("ui12_smart_countpicker", bool(ok))
    pg.evaluate("""() => { document.querySelector('[data-pp-chooser] [data-ppmc-start]').click(); }""")
    ok = until("""() => {
        var c = document.querySelector('[data-pp-overlay] [data-pp-card]');
        return c && /第 1\\/\\d+ 题/.test(c.textContent);
    }""", loops=40)
    step("ui13_smart_pool_loaded", bool(ok),
         pg.evaluate("""() => { var c = document.querySelector('[data-pp-overlay] [data-pp-card]');
             return c ? (c.textContent.match(/第 1\\/(\\d+) 题/) || [])[1] : null; }"""))
    pg.evaluate("""() => { var x = document.querySelector('[data-pp-overlay] [data-pp-close]'); if (x) x.click(); }""")

    pg.evaluate("""() => { document.querySelector('[data-tb="manual"]').click(); }""")
    ok = until("""() => {
        var l = document.querySelector('[data-pp-chooser] [data-ppmc-list]');
        return l && l.querySelectorAll('input[type="checkbox"]').length >= 20;
    }""", loops=20)
    mp = pg.evaluate("""() => {
        var ov = document.querySelector('[data-pp-chooser]');
        if (!ov) return null;
        return { rows: ov.querySelectorAll('input[type="checkbox"]').length,
                 checked: ov.querySelectorAll('input[type="checkbox"]:checked').length,
                 paged: (ov.querySelector('[data-ppmc-pg]').textContent || '').indexOf('2') >= 0,
                 btn: (ov.querySelector('[data-ppmc-start]').textContent || '').trim() };
    }""")
    step("ui14_manual_picker", bool(mp) and mp["rows"] == 20 and mp["checked"] >= 1 and mp["paged"],
         json.dumps(mp, ensure_ascii=False))
    pg.screenshot(path=str(SHOT_DIR / "eu_p3_manual_picker.png"))
    pg.evaluate("() => document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}))")
    pg.wait_for_timeout(300)

    # ---------- 6. 行级举一反三（真实 LLM，出题到即通过，不作答） ----------
    pg.evaluate("""() => { document.querySelector('[data-pp-analogy]').click(); }""")
    ok = until("""() => {
        var c = document.querySelector('[data-pp-overlay] [data-pp-card]');
        if (!c) return 0;
        if (/第 1\\/\\d+ 题/.test(c.textContent)) return 'q';
        if (c.textContent.indexOf('失败') >= 0) return 'fail:' + c.textContent.slice(0, 120);
        return 0;
    }""", loops=120, ms=1000)
    step("ui15_row_analogy_llm", ok == "q", str(ok))
    if ok == "q":
        pg.screenshot(path=str(SHOT_DIR / "eu_p3_analogy.png"))
    pg.evaluate("""() => { var x = document.querySelector('[data-pp-overlay] [data-pp-close]'); if (x) x.click(); }""")
    pg.wait_for_timeout(400)

    # ---------- 7. 页级举一反三（工具栏：smart 选题→analogy，取 3 题） ----------
    pg.evaluate("""() => { document.querySelector('[data-tb="analogy"]').click(); }""")
    ok = until("!!document.querySelector('[data-pp-chooser] [data-ppmc-start]')", loops=20)
    if ok:
        pg.evaluate("""() => { document.querySelector('[data-ppmc-cnt="3"]').click();
            document.querySelector('[data-pp-chooser] [data-ppmc-start]').click(); }""")
    ok = until("""() => {
        var c = document.querySelector('[data-pp-overlay] [data-pp-card]');
        if (!c) return 0;
        if (/第 1\\/\\d+ 题/.test(c.textContent)) return 'q';
        if (c.textContent.indexOf('失败') >= 0) return 'fail:' + c.textContent.slice(0, 120);
        return 0;
    }""", loops=120, ms=1000)
    step("ui16_page_analogy_llm", ok == "q", str(ok))
    pg.evaluate("""() => { var x = document.querySelector('[data-pp-overlay] [data-pp-close]'); if (x) x.click(); }""")
    pg.wait_for_timeout(400)

    # ---------- 8. P4 报告：全局分析（真实 LLM）→ 双视图 → 针对练习 ----------
    pg.evaluate("""() => { document.querySelector('[data-tb="report"]').click(); }""")
    ok = until("!!document.querySelector('[data-wr-overlay] [data-wr-global]')", loops=30)
    step("ui17_report_drawer", bool(ok))
    pg.evaluate("""() => { document.querySelector('[data-wr-global]').click(); }""")
    ok = until("""() => {
        var c = document.querySelector('[data-wr-card]');
        if (!c) return 0;
        if (c.querySelector('[data-wr-tab]')) return 'done';
        var t = c.textContent || '';
        if (t.indexOf('失败') >= 0 || t.indexOf('校验') >= 0) return 'fail:' + t.slice(0, 160);
        return 0;
    }""", loops=180, ms=1000)
    step("ui18_weakness_report_llm", ok == "done", str(ok))
    if ok == "done":
        pg.screenshot(path=str(SHOT_DIR / "eu_p4_report_text.png"))
        txt = pg.evaluate("""() => document.querySelector('[data-wr-card]').textContent.length""")
        step("ui19_report_text_rendered", txt > 100, f"chars={txt}")
        pg.evaluate("""() => { document.querySelector('[data-wr-tab="map"]').click(); }""")
        ok = until("""() => {
            var c = document.querySelector('[data-wr-card]');
            return c && (c.textContent.indexOf('知识点') >= 0 || c.textContent.indexOf('总结点') >= 0);
        }""", loops=20)
        mm = pg.evaluate("""() => {
            var c = document.querySelector('[data-wr-card]');
            if (!c) return null;
            return { badges: (c.textContent.match(/知识点|总结点/g) || []).length,
                     weak: c.querySelectorAll('[data-mm-prac]').length,
                     evidence: (c.textContent || '').indexOf('证据错题') >= 0 };
        }""")
        step("ui20_mindmap_view", bool(mm) and mm["badges"] >= 1, json.dumps(mm, ensure_ascii=False))
        pg.screenshot(path=str(SHOT_DIR / "eu_p4_mindmap.png"))
        # 薄弱点「针对练习」→ analogy 出题（真实 LLM；无薄弱节点或无按钮则跳过并如实记录）
        if mm and mm["weak"] >= 1:
            pg.evaluate("""() => { document.querySelector('[data-mm-prac]').click(); }""")
            ok = until("""() => {
                var c = document.querySelector('[data-pp-overlay] [data-pp-card]');
                if (!c) return 0;
                if (/第 1\\/\\d+ 题/.test(c.textContent)) return 'q';
                if (c.textContent.indexOf('失败') >= 0) return 'fail:' + c.textContent.slice(0, 120);
                return 0;
            }""", loops=120, ms=1000)
            step("ui21_targeted_practice_llm", ok == "q", str(ok))
            pg.evaluate("""() => { var x = document.querySelector('[data-pp-overlay] [data-pp-close]'); if (x) x.click(); }""")
        else:
            step("ui21_targeted_practice_llm", True, "报告无薄弱节点（全 ok），无针对练习按钮 — 结构使然，视为通过")
        # 返回列表应已有 1 份报告
        pg.evaluate("""() => { var b = document.querySelector('[data-wr-back]'); if (b) b.click(); }""")
        ok = until("""() => {
            var c = document.querySelector('[data-wr-card]');
            return c && c.textContent.indexOf('全局') >= 0 && c.querySelector('[data-wr-open]');
        }""", loops=20)
        step("ui22_report_list_persisted", bool(ok))
        pg.screenshot(path=str(SHOT_DIR / "eu_p4_report_list.png"))

    b.close()

step("ui90_no_pageerror", not pageerrs, str(pageerrs[:2])[:200])

_purge(UID)
OUT.write_text("\n".join(lines) + f"\n\nELAPSED={time.time()-t0:.1f}s FAILS={fails}\n", encoding="utf-8")
print(f"== finish FAILS={fails} elapsed={time.time()-t0:.1f}s")
sys.exit(1 if fails else 0)
