# -*- coding: utf-8 -*-
# u13 E2E 验证：知识点详情页多题型答题模板（stub 桥，防真实 LLM 耗时烧积分）
# 覆盖：笔记练习答题轮播（单选/判断/填空/简答四种模板渲染）、未答拦截、回看保留答案、
#       提交参数正确性、判分结果页（分数+AI点评+错题提示）、头部掌握度刷新、举一反三空态。
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
OUT = r"e:\LLM\LectureLearnLoop\server\logs\u13_verify.txt"
TOKEN = open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", encoding="utf-8").read().strip()
MOD = "U13PV" + uuid.uuid4().hex[:6]
SUBJECT = f"{MOD}_探针科"
POINT = f"{MOD}模板验证点"
PFX = "U13PV%"

lines = []
errs = []


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

r = requests.post(BASE + "/api/subjects", json={"subject_name": SUBJECT}, headers=H, timeout=15)
lines.append("SEED_SUBJECT -> " + str(r.status_code))
_exec("INSERT INTO knowledge_points (user_id, subject_name, point_name, core_description, mastery_score) VALUES (?,?,?,?,?)",
      (UID, SUBJECT, POINT, f"{MOD}测试描述", 30))
pid = _exec("SELECT id FROM knowledge_points WHERE user_id = ? AND point_name = ?", (UID, POINT), fetch=True)[0][0]
lines.append("SEED -> pid=" + str(pid))

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.on("pageerror", lambda e: errs.append("pageerror: " + str(e)[:300]))
    pg.goto(BASE + "/login", wait_until="domcontentloaded")
    pg.evaluate("t => localStorage.setItem('ll_token', t)", TOKEN)
    pg.goto(BASE + "/", wait_until="networkidle")
    pg.wait_for_timeout(800)

    # —— 先进练总览（触发 pm_pages.js 动态注入，与真实用户旅程一致）——
    pg.evaluate("handleMenuClick('practice_overview')")
    ready = False
    for _ in range(90):  # P030：轮询特征禁固定 sleep
        ready = pg.evaluate("() => document.querySelector('[data-pm-page=\"practice_overview\"]') !== null")
        if ready:
            break
        pg.wait_for_timeout(1000)
    lines.append("OVERVIEW_READY -> " + str(ready))

    # —— 直达详情页 ——
    pg.evaluate("""([id, name]) => { pmUtil.goPracticePoint(id, name); }""", [str(pid), POINT])
    ok = False
    for _ in range(60):
        ok = pg.evaluate("""(name) => {
            const root = document.querySelector('[data-pm-page="knowledge_point"]');
            return !!(root && root.querySelector('h1') && (root.querySelector('h1').textContent || '').includes(name));
        }""", POINT)
        if ok:
            break
        pg.wait_for_timeout(1000)
    lines.append("DETAIL_READY -> " + str(ok))

    # —— stub 桥：8 题混合题型 + 提交判分回传参数留痕 ——
    pg.evaluate("""(point) => {
        const qs = [
            {type: 'single', question: point + '单选一号', options: ['甲','乙','丙','丁'], correct_answer: 'A', difficulty: '容易', explanation: '解一'},
            {type: 'judge', question: '判断二号', correct_answer: '正确', difficulty: '中等', explanation: '解二'},
            {type: 'fill', question: '填空三号 ______ 为答案', correct_answer: '甲', difficulty: '中等', explanation: '解三'},
            {type: 'short', question: '简答四号', correct_answer: '参考要点', difficulty: '困难', explanation: '解四'},
            {type: 'single', question: '单选五号', options: ['甲','乙','丙','丁'], correct_answer: 'B', difficulty: '容易', explanation: '解五'},
            {type: 'judge', question: '判断六号', correct_answer: '错误', difficulty: '中等', explanation: '解六'},
            {type: 'fill', question: '填空七号 ______', correct_answer: '乙', difficulty: '困难', explanation: '解七'},
            {type: 'single', question: '单选八号', options: ['甲','乙','丙','丁'], correct_answer: 'C', difficulty: '容易', explanation: '解八'}
        ];
        window.bridge.generatePointPractice = (pid2, src) => Promise.resolve(JSON.stringify(
            src === 'notes' ? {success: true, questions: qs} : {success: false, no_errors: true}));
        window.bridge.submitPointPractice = (pid2, qList, aList) => {
            window.__submitArgs = {pid: pid2, nq: qList.length, na: aList.length, ans: aList};
            return Promise.resolve(JSON.stringify({
                success: true, mastery_score: 66, correct_count: 5, total_count: 8, accuracy: 0.625,
                detailed_results: [
                    {question_index: 0, question: point + '单选一号', type: 'single', user_answer: 'A', correct_answer: 'A', is_correct: true, difficulty: '容易', explanation: '解一', comment: ''},
                    {question_index: 3, question: '简答四号', type: 'short', user_answer: '我的简答内容', correct_answer: '参考要点', is_correct: false, difficulty: '困难', explanation: '解四', comment: '要点覆盖不足'},
                    {question_index: 7, question: '单选八号', type: 'single', user_answer: 'C', correct_answer: 'C', is_correct: true, difficulty: '容易', explanation: '解八', comment: ''}
                ]}));
        };
    }""", POINT)

    # —— 逐题作答全流程 ——
    pg.evaluate("document.querySelector('[data-act=\"notes\"]').click()")
    q1 = False
    for _ in range(30):
        q1 = pg.evaluate("""(point) => {
            const p = document.querySelector('[data-pm-page="knowledge_point"] [data-role="practice-panel"]');
            return !!(p && !p.classList.contains('hidden')
                && (p.textContent || '').includes(point + '单选一号')
                && (p.textContent || '').includes('选择题'));
        }""", POINT)
        if q1:
            break
        pg.wait_for_timeout(500)
    lines.append("Q1_SINGLE_SHOWN -> " + str(q1))

    # 未答拦截：直接点下一题应弹提示且停留本题
    pg.evaluate("document.querySelector('[data-role=\"prac-next\"]').click()")
    blocked = pg.evaluate("""() => {
        const h = document.querySelector('[data-role="act-hint"]');
        return !!(h && (h.textContent || '').includes('请先作答本题'));
    }""")
    lines.append("UNANSWERED_BLOCKED -> " + str(blocked))

    pg.evaluate("document.querySelector('input[name=\"kp-prac\"][value=\"A\"]').click()")
    pg.evaluate("document.querySelector('[data-role=\"prac-next\"]').click()")
    q2 = pg.evaluate("""() => {
        const p = document.querySelector('[data-role="practice-panel"]');
        const t = p ? (p.textContent || '') : '';
        return t.includes('判断二号') && t.includes('判断题') && !!p.querySelector('input[value=\"正确\"]');
    }""")
    lines.append("Q2_JUDGE_SHOWN -> " + str(q2))
    pg.evaluate("document.querySelector('input[name=\"kp-prac\"][value=\"正确\"]').click()")
    pg.evaluate("document.querySelector('[data-role=\"prac-next\"]').click()")

    q3 = pg.evaluate("() => { const p = document.querySelector('[data-role=\"practice-panel\"]'); const t = p ? (p.textContent||'') : ''; return t.includes('填空三号') && !!p.querySelector('[data-role=\"prac-text\"]'); }")
    lines.append("Q3_FILL_SHOWN -> " + str(q3))
    pg.fill('[data-pm-page="knowledge_point"] [data-role="practice-panel"] input[data-role="prac-text"]', '甲')
    pg.evaluate("document.querySelector('[data-role=\"prac-next\"]').click()")

    q4 = pg.evaluate("() => { const p = document.querySelector('[data-role=\"practice-panel\"]'); const t = p ? (p.textContent||'') : ''; return t.includes('简答四号') && t.includes('简答题') && !!p.querySelector('textarea[data-role=\"prac-text\"]'); }")
    lines.append("Q4_SHORT_SHOWN -> " + str(q4))

    # 回看保留：上一题回到填空，答案应还在；再回简答继续作答
    pg.evaluate("document.querySelector('[data-role=\"prac-prev\"]').click()")
    kept = pg.evaluate("() => { const i = document.querySelector('[data-role=\"practice-panel\"] input[data-role=\"prac-text\"]'); return !!i && i.value === '甲'; }")
    lines.append("BACK_KEEPS_FILL -> " + str(kept))
    pg.evaluate("document.querySelector('[data-role=\"prac-next\"]').click()")
    pg.fill('[data-pm-page="knowledge_point"] [data-role="practice-panel"] textarea[data-role="prac-text"]', '我的简答内容')

    # 剩余 4 题快速作答到底
    pg.evaluate("document.querySelector('[data-role=\"prac-next\"]').click()")  # q5
    pg.evaluate("document.querySelector('input[name=\"kp-prac\"][value=\"B\"]').click()")
    pg.evaluate("document.querySelector('[data-role=\"prac-next\"]').click()")  # q6
    pg.evaluate("document.querySelector('input[name=\"kp-prac\"][value=\"错误\"]').click()")
    pg.evaluate("document.querySelector('[data-role=\"prac-next\"]').click()")  # q7
    pg.fill('[data-pm-page="knowledge_point"] [data-role="practice-panel"] input[data-role="prac-text"]', '乙')
    pg.evaluate("document.querySelector('[data-role=\"prac-next\"]').click()")  # q8
    q8 = pg.evaluate("() => { const p = document.querySelector('[data-role=\"practice-panel\"]'); const t = p ? (p.textContent||'') : ''; return t.includes('单选八号') && t.includes('8/8') && t.includes('提交作答'); }")
    lines.append("Q8_LAST_SUBMIT_BTN -> " + str(q8))
    pg.evaluate("document.querySelector('input[name=\"kp-prac\"][value=\"C\"]').click()")
    pg.evaluate("document.querySelector('[data-role=\"prac-next\"]').click()")  # 提交

    done = False
    for _ in range(30):
        done = pg.evaluate("""() => {
            const p = document.querySelector('[data-role="practice-panel"]');
            const t = p ? (p.textContent || '') : '';
            return t.includes('判分结果') && t.includes('66') && t.includes('答对 5/8');
        }""")
        if done:
            break
        pg.wait_for_timeout(500)
    lines.append("SUBMIT_RESULT_SHOWN -> " + str(done))

    probe = pg.evaluate("""() => {
        const r = {};
        const p = document.querySelector('[data-role="practice-panel"]');
        const t = p ? (p.textContent || '') : '';
        r.aiComment = t.includes('要点覆盖不足');       // 简答题 AI 点评展示
        r.wrongMark = t.includes('错题已入错题本');      // 结果页错题提示
        const ms = document.querySelector('[data-role="mastery-slot"]');
        r.headMastery = ms ? (ms.textContent || '').trim() : 'NO-EL';
        r.hint = (document.querySelector('[data-role="act-hint"]').textContent || '').trim();
        r.args = window.__submitArgs || null;
        return r;
    }""")
    lines.append("PROBE -> " + J(probe))
    argseq = (probe["args"] or {}).get("ans") if probe["args"] else None
    expect_ans = ["A", "正确", "甲", "我的简答内容", "B", "错误", "乙", "C"]
    lines.append("SUBMIT_ARGS_MATCH -> " + str(argseq == expect_ans))

    # —— 举一反三：stub 空态（no_errors）——
    pg.evaluate("document.querySelector('[data-act=\"analogy\"]').click()")
    empty = False
    for _ in range(30):
        empty = pg.evaluate("""() => {
            const p = document.querySelector('[data-role="practice-panel"]');
            return !!(p && (p.textContent || '').includes('暂无错题记录'));
        }""")
        if empty:
            break
        pg.wait_for_timeout(500)
    lines.append("ANALOGY_EMPTY_STATE -> " + str(empty))
    b.close()

_purge()
lines.append("PURGE_END -> done")
lines.append("PAGE_ERRORS -> " + (J(errs[:5]) if errs else "NONE"))
Path(OUT).write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
