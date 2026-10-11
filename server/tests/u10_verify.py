# u10 E2E 验证：知识点详情独立直达页
# 覆盖：直达不经过脑图、动态面包屑反映来源、详情渲染、评估答题全流程（stub 桥防真实 LLM）、
#       笔记练习空态、过期旗标空态、面包屑点击回退、窄栏高亮归组。种探针 → 断言 → 清理。
import base64
import json
import sys
import uuid
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database import db_adapter
import config

BASE = "http://127.0.0.1:6001"
OUT = r"e:\LLM\LectureLearnLoop\server\logs\u10_verify.txt"
TOKEN = open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", encoding="utf-8").read().strip()
MOD = "U10PV" + uuid.uuid4().hex[:6]
SUBJECT = f"{MOD}_探针科"
POINT = f"{MOD}排序算法"
PFX = "U10PV%"

lines = []
errs = []
dialogs = []


def J(x):
    return json.dumps(x, ensure_ascii=False)


def _uid(tk):
    seg = tk.split(".")[1]
    seg += "=" * (-len(seg) % 4)
    pl = json.loads(base64.urlsafe_b64decode(seg))
    return pl.get("uid") or pl.get("user_id")


H = {"Authorization": "Bearer " + TOKEN}
UID = _uid(TOKEN)


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


def _purge():
    c = db_adapter.get_connection(str(config.DB_PATH))
    try:
        cur = c.cursor()
        cur.execute("SELECT id FROM knowledge_points WHERE user_id = ? AND subject_name LIKE ?", (UID, PFX))
        pids = [x[0] for x in cur.fetchall()]
        if pids:
            cur.execute("DELETE FROM knowledge_point_sources WHERE knowledge_point_id IN ("
                        + ",".join(str(int(i)) for i in pids) + ")")
            cur.execute("DELETE FROM knowledge_points WHERE user_id = ? AND subject_name LIKE ?", (UID, PFX))
        cur.execute("DELETE FROM practice_records WHERE user_id = ? AND subject_name LIKE ?", (UID, PFX))
        cur.execute("DELETE FROM error_questions WHERE user_id = ? AND subject_name LIKE ?", (UID, PFX))
        cur.execute("DELETE FROM user_subjects WHERE user_id = ? AND subject_name LIKE ?", (UID, PFX))
        c.commit()
    finally:
        c.close()


_purge()
lines.append("PURGE -> done")

# ---- 1) 种探针数据：1 点（mastery=30）+ 1 条练习记录（答错，出最近练习列表）
r = requests.post(BASE + "/api/subjects", json={"subject_name": SUBJECT}, headers=H, timeout=15)
lines.append("SEED_SUBJECT -> " + str(r.status_code))
_exec("INSERT INTO knowledge_points (user_id, subject_name, point_name, core_description, mastery_score) VALUES (?,?,?,?,?)",
      (UID, SUBJECT, POINT, f"{MOD}测试描述", 30))
pid = _exec("SELECT id FROM knowledge_points WHERE user_id = ? AND point_name = ?", (UID, POINT), fetch=True)[0][0]
_exec("INSERT INTO practice_records (user_id, subject_name, knowledge_point_id, question_content, user_answer, is_correct) "
      "VALUES (?,?,?,?,?,?)", (UID, SUBJECT, pid, f"{MOD}探针题干", "a", 0))
lines.append("SEED -> pid=" + str(pid))

# ---- 2) Playwright UI 断言
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.on("pageerror", lambda e: errs.append("pageerror: " + str(e)[:300]))
    pg.on("dialog", lambda d: (dialogs.append(d.type + ":" + d.message[:80]), d.dismiss()))
    pg.goto(BASE + "/login", wait_until="domcontentloaded")
    pg.evaluate("t => localStorage.setItem('ll_token', t)", TOKEN)
    pg.goto(BASE + "/", wait_until="networkidle")
    pg.wait_for_timeout(800)

    # 先进练总览，制造真实导航轨迹（面包屑应反映「练·科目总览」来源）
    pg.evaluate("handleMenuClick('practice_overview')")
    ready = False
    for _ in range(90):  # P030：轮询特征禁固定 sleep
        ready = pg.evaluate("() => document.querySelector('[data-pm-page=\"practice_overview\"]') !== null")
        if ready:
            break
        pg.wait_for_timeout(1000)
    lines.append("OVERVIEW_READY -> " + str(ready))

    # 直达：goPracticePoint（与总览「去练习」按钮同一封装）
    # u10 CodeReview M-1 回归：连点两次（双片段注入消费同一旗标）仍须渲染详情而非空态
    pg.evaluate("""([id, name]) => { pmUtil.goPracticePoint(id, name); pmUtil.goPracticePoint(id, name); }""", [str(pid), POINT])
    ok = False
    for _ in range(90):
        ok = pg.evaluate("""(name) => {
            const root = document.querySelector('[data-pm-page="knowledge_point"]');
            return !!(root && root.querySelector('h1') && (root.querySelector('h1').textContent || '').includes(name));
        }""", POINT)
        if ok:
            break
        pg.wait_for_timeout(1000)
    lines.append("DETAIL_DIRECT -> " + str(ok))

    probe = pg.evaluate("""(point) => {
        const r = {};
        r.noMindmap = document.querySelector('[data-pm-page="practice_materials"]') === null;
        r.curPage = window.current_page;
        const crumb = document.querySelector('#kp-crumb');
        r.crumbText = crumb ? (crumb.textContent || '').replace(/\\s+/g, ' ') : 'NO-CRUMB';
        r.crumbFrom = crumb ? [...crumb.querySelectorAll('[data-crumb]')].map(x => x.getAttribute('data-crumb')) : [];
        const root = document.querySelector('[data-pm-page="knowledge_point"]');
        const txt = (root.textContent || '').replace(/\\s+/g, ' ');
        r.shown = { mastery30: txt.includes('30%'), desc: txt.includes('测试描述'),
                    statErr: txt.includes('道错题'), notesCell: txt.includes('篇关联笔记'),
                    recent: txt.includes('探针题干') };
        const nav = document.querySelector('.cl-nav-item[data-cid="practice_overview"]');
        r.navActive = nav ? nav.className.includes('cl-active') : false;
        r.trail = (window.__pmTrail || []).slice(-4);
        return r;
    }""", POINT)
    lines.append("PROBE -> " + J(probe))

    # —— 熟练度评估全流程（stub 桥，防真实 LLM 耗时烧积分）——
    pg.evaluate("""(point) => {
        const qs = [
            {question: point + '评估题干一', options: ['选一', '选二', '选三', '选四'], correct_answer: 'A', difficulty: '容易', explanation: '解析一'},
            {question: '评估题干二', options: ['甲', '乙', '丙', '丁'], correct_answer: 'B', difficulty: '困难', explanation: '解析二'}
        ];
        window.bridge.generateAssessmentQuestions = () => Promise.resolve(JSON.stringify({success: true, questions: qs}));
        window.bridge.submitMasteryAssessment = (pid2, qj, aj) => {
            window.__submitArgs = {pid: pid2, nq: JSON.parse(qj).length, ans: JSON.parse(aj)};
            return Promise.resolve(JSON.stringify({
                success: true, mastery_score: 88, correct_count: 2, total_count: 2, accuracy: 1.0,
                detailed_results: [
                    {question_index: 0, question: '题干一', user_answer: 'A', correct_answer: 'A', is_correct: true, difficulty: '容易', explanation: '解析一'},
                    {question_index: 1, question: '题干二', user_answer: 'C', correct_answer: 'B', is_correct: false, difficulty: '困难', explanation: '解析二'}
                ]}));
        };
        window.__kpName = point;
    }""", POINT)
    pg.evaluate("document.querySelector('[data-act=\"assess\"]').click()")
    q1 = False
    for _ in range(30):
        q1 = pg.evaluate("""() => {
            const p = document.querySelector('[data-pm-page="knowledge_point"] [data-role="assess-panel"]');
            return !!(p && !p.classList.contains('hidden') && (p.textContent || '').includes('评估题干一'));
        }""")
        if q1:
            break
        pg.wait_for_timeout(1000)
    lines.append("ASSESS_Q1_SHOWN -> " + str(q1))
    pg.evaluate("document.querySelector('input[name=\"kp-assess\"][value=\"A\"]').click()")
    pg.evaluate("document.querySelector('[data-role=\"assess-next\"]').click()")
    q2 = False
    for _ in range(30):
        q2 = pg.evaluate("() => { const p = document.querySelector('[data-role=\"assess-panel\"]'); return !!(p && (p.textContent || '').includes('评估题干二')); }")
        if q2:
            break
        pg.wait_for_timeout(1000)
    lines.append("ASSESS_Q2_SHOWN -> " + str(q2))
    pg.evaluate("document.querySelector('input[name=\"kp-assess\"][value=\"C\"]').click()")
    pg.evaluate("document.querySelector('[data-role=\"assess-next\"]').click()")  # 提交评估
    done = False
    for _ in range(30):
        done = pg.evaluate("""() => {
            const p = document.querySelector('[data-role="assess-panel"]');
            const t = p ? (p.textContent || '') : '';
            return t.includes('熟练度：') && t.includes('88');
        }""")
        if done:
            break
        pg.wait_for_timeout(1000)
    lines.append("ASSESS_RESULT -> " + str(done))
    head = pg.evaluate("""() => {
        const ms = document.querySelector('[data-role="mastery-slot"]');
        const pt = document.querySelector('[data-role="assess-panel"]').textContent || '';
        return { slot: ms ? (ms.textContent || '').trim() : 'NO-EL',
                 args: window.__submitArgs || null,
                 explain: pt.includes('解析二'),
                 // 2026-10-08 用户要求：评估判分结果页必须展示原题选项（绿色高亮正确答案、红色标注误选）
                 optionsShown: pt.includes('A. 选一') && pt.includes('B. 乙') && pt.includes('（你选的）') };
    }""")
    lines.append("ASSESS_HEAD_REFRESH -> " + J(head))

    # —— 基于笔记练习：无关联笔记 → 空态提示（u13 新契约：stub generatePointPractice 防真实 LLM）——
    pg.evaluate("window.bridge.generatePointPractice = () => Promise.resolve(JSON.stringify({success: false, no_notes: true, error: '无笔记'}))")
    pg.evaluate("document.querySelector('[data-act=\"notes\"]').click()")
    empty_notes = False
    for _ in range(30):
        empty_notes = pg.evaluate("""() => {
            const p = document.querySelector('[data-role="practice-panel"]');
            return !!(p && !p.classList.contains('hidden') && (p.textContent || '').includes('暂无关联笔记'));
        }""")
        if empty_notes:
            break
        pg.wait_for_timeout(1000)
    lines.append("NOTES_EMPTY_HINT -> " + str(empty_notes))

    # —— 面包屑点击回退到练总览 ——
    pg.evaluate("document.querySelector('#kp-crumb [data-crumb=\"practice_overview\"]').click()")
    back = False
    for _ in range(30):
        back = pg.evaluate("() => document.querySelector('[data-pm-page=\"practice_overview\"]') !== null")
        if back:
            break
        pg.wait_for_timeout(1000)
    lines.append("CRUMB_BACK -> " + str(back))
    trail_after = pg.evaluate("() => (window.__pmTrail || []).slice(-3)")
    lines.append("TRAIL_AFTER_BACK -> " + J(trail_after))

    # —— 过期旗标：直进详情页 → 空态（不幽灵弹出旧点）——
    # u13 回归轮次：先清 __kpLastConsumed 幂等缓存（10s 窗口为连点防断链设计，
    # 本步断言对象是过期 localStorage 旗标，须隔离缓存才能纯验证过期行为）
    pg.evaluate("window.__kpLastConsumed = null")
    pg.evaluate("""() => localStorage.setItem('pm_pending_point',
        JSON.stringify({id: '1', name: '陈旧点', ts: Date.now() - 60000}))""")
    pg.evaluate("handleMenuClick('knowledge_point')")
    stale = False
    for _ in range(30):
        stale = pg.evaluate("""() => {
            const root = document.querySelector('[data-pm-page="knowledge_point"]');
            return !!(root && (root.textContent || '').includes('没有选定知识点'));
        }""")
        if stale:
            break
        pg.wait_for_timeout(1000)
    lines.append("STALE_FLAG_EMPTY_STATE -> " + str(stale))
    b.close()

# ---- 3) 清理
_purge()
lines.append("CLEANUP -> done")
lines.append("DIALOGS -> " + J(dialogs))
lines.append("PAGE_ERRORS -> " + (J(errs[:5]) if errs else "NONE"))
Path(OUT).write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
