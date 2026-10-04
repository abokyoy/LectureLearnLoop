# -*- coding: utf-8 -*-
"""c2 E2E 验证：记知识点翻卡化 + 记错题翻卡四档自评（FSRS）
旅程：种子数据 → 浏览器打开记知识点页（卡片模式）→ 翻面 → 自评 familiar →
      记错题页 → 翻面 → 自评 perfect（应自动标记已复习）→
      debug_trace.jsonl 断言两次 apply_review success → API 读回状态断言 → 清理。
"""
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
OUT = r"e:\LLM\LectureLearnLoop\server\logs\u15_c2_verify.txt"
TOKEN = open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", encoding="utf-8").read().strip()
H = {"Authorization": "Bearer " + TOKEN}
MOD = "U15C2" + uuid.uuid4().hex[:6]
SUBJECT = f"{MOD}_探针科"
PFX = "U15C2%"

lines = []
fails = []


def step(name, ok, extra=""):
    lines.append(("PASS " if ok else "FAIL ") + name + (" | " + str(extra) if extra else ""))
    if not ok:
        fails.append(name)


def _uid():
    import base64
    seg = TOKEN.split(".")[1]
    seg += "=" * (-len(seg) % 4)
    return json.loads(base64.urlsafe_b64decode(seg))["uid"]


UID = _uid()


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
            ph = ",".join(str(int(i)) for i in pids)
            cur.execute("DELETE FROM knowledge_point_sources WHERE knowledge_point_id IN (" + ph + ")")
            cur.execute("DELETE FROM practice_records WHERE user_id = ? AND subject_name LIKE ?", (UID, PFX))
            cur.execute("DELETE FROM kp_proficiency_history WHERE user_id = ? AND knowledge_point_id IN (" + ph + ")", (UID,))
            cur.execute("DELETE FROM knowledge_points WHERE user_id = ? AND subject_name LIKE ?", (UID, PFX))
        cur.execute("SELECT id FROM error_questions WHERE user_id = ? AND subject_name LIKE ?", (UID, PFX))
        eids = [x[0] for x in cur.fetchall()]
        if eids:
            eh = ",".join(str(int(i)) for i in eids)
            cur.execute("DELETE FROM error_proficiency_history WHERE error_question_id IN (" + eh + ")")
            cur.execute("DELETE FROM error_questions WHERE user_id = ? AND subject_name LIKE ?", (UID, PFX))
        cur.execute("DELETE FROM user_subjects WHERE user_id = ? AND subject_name LIKE ?", (UID, PFX))
        c.commit()
    finally:
        c.close()


# ---------- 种子：学科 + 2 知识点 + 1 道答错错题（走真实 practice-submit，全单选不触 LLM） ----------
_purge()
r = requests.post(BASE + "/api/subjects", json={"subject_name": SUBJECT}, headers=H, timeout=15)
step("seed_subject", r.status_code == 200 and r.json().get("success"), r.text[:120])
kp_ids = []
for i, (name, desc, m) in enumerate([
    (f"{MOD}薄弱点", f"{MOD}描述A：间隔重复自评测验", 30),
    (f"{MOD}较强点", f"{MOD}描述B", 90),
]):
    rr = requests.post(BASE + "/api/knowledge/point-new",
                       json={"point": {"name": name, "description": desc, "mastery_score": m}, "subject": SUBJECT},
                       headers=H, timeout=20)
    jj = rr.json()
    okk = jj.get("success")
    if okk:
        kp_ids.append(int(jj["data"]["knowledge_id"]))
    step(f"seed_point_{i}", okk, rr.text[:150])

# point-new 不收 mastery_score（默认 50），直写 DB 造最弱差（New 态行不被 decay_flush 覆盖，安全）
_exec("UPDATE knowledge_points SET mastery_score = 30 WHERE id = ? AND user_id = ?", (kp_ids[0], UID))
_exec("UPDATE knowledge_points SET mastery_score = 90 WHERE id = ? AND user_id = ?", (kp_ids[1], UID))

# 用第一个知识点答错一道单选 → 自动入错题池
q = [{"type": "single", "question": f"{MOD}Q1 必错单选", "options": ["a", "b", "c", "d"],
      "correct_answer": "A", "difficulty": "容易", "explanation": "e"}]
rp = requests.post(f"{BASE}/api/knowledge/points/{kp_ids[0]}/practice-submit",
                   json={"questions": q, "answers": ["C"]}, headers=H, timeout=60)
jp = rp.json()
step("seed_error_via_practice", jp.get("success") and jp["data"]["correct_count"] == 0, rp.text[:200])
errs = requests.get(BASE + "/api/kb/errors", params={"subject": SUBJECT}, headers=H, timeout=15).json()["data"]
eid = next((x["id"] for x in errs if str(x.get("question_content", "")).startswith(MOD)), None)
step("seed_error_found", eid is not None, f"eid={eid}")

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pageerrs = []
    pg.on("pageerror", lambda e: pageerrs.append("pageerror: " + str(e)[:300]))
    pg.goto(BASE + "/login", wait_until="domcontentloaded")
    pg.evaluate("t => localStorage.setItem('ll_token', t)", TOKEN)
    pg.goto(BASE + "/", wait_until="networkidle")
    pg.wait_for_timeout(600)

    def wait_page(cid, timeout_loops=90):
        pg.evaluate(f"handleMenuClick('{cid}')")
        for _ in range(timeout_loops):
            if pg.evaluate(f"() => document.querySelector('[data-pm-page=\"{cid}\"]') !== null"):
                pg.wait_for_timeout(1200)  # 学科/数据异步渲染
                return True
            pg.wait_for_timeout(400)
        return False

    # ---------- 记知识点页：卡片模式 + 翻面 + 自评 ----------
    ok = wait_page("memory_knowledge")
    step("kp_page_rendered", ok)
    # 选中探针学科 chip
    picked = pg.evaluate(f"""() => {{
        const b = [...document.querySelectorAll('[data-pm-page="memory_knowledge"] [data-subj]')]
            .find(x => x.getAttribute('data-subj') === '{SUBJECT}');
        if (b) b.click();
        return !!b;
    }}""")
    step("kp_pick_subject", picked)
    pg.wait_for_timeout(1500)
    # 最弱优先：第一卡应为「薄弱点」
    first = pg.evaluate("() => document.querySelector('[data-pm-page=\"memory_knowledge\"] [data-role=\"flip-card\"] .pm-flip-face p')?.textContent || ''")
    step("kp_weakest_first", MOD in first and "薄弱" in first, first[:60])
    flipped = pg.evaluate("""() => {
        const c = document.querySelector('[data-pm-page="memory_knowledge"] [data-role="flip-card"]');
        if (!c) return false;
        c.querySelector('.pm-flip-face').click();
        return c.classList.contains('is-flipped');
    }""")
    step("kp_card_flip", flipped)
    pg.wait_for_timeout(700)
    btns = pg.evaluate("() => document.querySelectorAll('[data-pm-page=\"memory_knowledge\"] [data-rate]').length")
    step("kp_rate_bar_4btns", btns == 4, f"count={btns}")
    pg.evaluate("""() => {
        const el = document.querySelector('[data-pm-page="memory_knowledge"] [data-rate="familiar"]');
        el && el.click();
    }""")
    pg.wait_for_timeout(1500)
    # 自评后自动下一卡（第 2 / 2 卡）
    pos = pg.evaluate("() => [...document.querySelectorAll('[data-pm-page=\"memory_knowledge\"] span')].map(s=>s.textContent).find(t=>/第 \\d+ \\/ \\d+ 卡/.test(t)) || ''")
    step("kp_auto_next_card", "2 / 2" in pos, pos)
    d1 = requests.get(f"{BASE}/api/knowledge/points/{kp_ids[0]}/detail", headers=H, timeout=15).json()["data"]["detail"]
    step("kp_mastery_persisted", d1["mastery_score"] is not None and int(d1["mastery_score"]) >= 0, f"mastery={d1['mastery_score']}")

    # ---------- 记错题页：背面自评 = 计分 + 自动标记已复习 ----------
    ok = wait_page("memory_errors")
    step("err_page_rendered", ok)
    picked = pg.evaluate(f"""() => {{
        const b = [...document.querySelectorAll('[data-pm-page="memory_errors"] [data-subj]')]
            .find(x => x.getAttribute('data-subj') === '{SUBJECT}');
        if (b) b.click();
        return !!b;
    }}""")
    step("err_pick_subject", picked)
    pg.wait_for_timeout(1500)
    flipped = pg.evaluate("""() => {
        const c = document.querySelector('[data-pm-page="memory_errors"] [data-role="flip-card"]');
        if (!c) return false;
        c.querySelector('.pm-flip-face').click();
        return c.classList.contains('is-flipped');
    }""")
    step("err_card_flip", flipped)
    pg.wait_for_timeout(700)
    btns = pg.evaluate("() => document.querySelectorAll('[data-pm-page=\"memory_errors\"] [data-rate]').length")
    step("err_rate_bar_4btns", btns == 4, f"count={btns}")
    pg.evaluate("""() => {
        const el = document.querySelector('[data-pm-page="memory_errors"] [data-rate="perfect"]');
        el && el.click();
    }""")
    pg.wait_for_timeout(2000)
    # 自评后本题移出待复习队列 → 出现"全部复习完"完成页
    done_txt = pg.evaluate("""() => {
        const el = document.querySelector('[data-pm-page="memory_errors"] [data-role="main"]');
        return el ? el.textContent : '';
    }""")
    step("err_auto_reviewed_completion", ("复习完" in done_txt) or ("再翻已复习的" in done_txt), done_txt[:80].replace("\n", " "))

    # 列表模式切换可用（知识点页）
    pg.evaluate("handleMenuClick('memory_knowledge')")
    pg.wait_for_timeout(1200)
    pg.evaluate("""() => {
        const b = [...document.querySelectorAll('[data-pm-page="memory_knowledge"] [data-modesw]')].find(x=>x.getAttribute('data-modesw')==='list');
        b && b.click();
    }""")
    pg.wait_for_timeout(800)
    has_list = pg.evaluate("""() => !!document.querySelector('[data-pm-page="memory_knowledge"] details')""")
    step("kp_list_mode_toggle", has_list)
    b.close()

step("no_page_errors", not pageerrs, "; ".join(pageerrs[:3]))

# ---------- debug_trace.jsonl：两次 apply_review success（kind 各一） ----------
tail = Path(r"e:\LLM\LectureLearnLoop\server\logs\debug_trace.jsonl").read_text(encoding="utf-8", errors="replace")[-60000:]
tr_kp = f'"kind": "kp"' in tail and '"ref_id": ' in tail
import re
kp_in = any('"apply_review"' in ln and '"kp"' in ln and str(kp_ids[0]) in ln for ln in tail.splitlines())
er_in = any('"apply_review"' in ln and '"error"' in ln and str(eid) in ln for ln in tail.splitlines())
step("trace_apply_review_kp", kp_in)
step("trace_apply_review_error", er_in)

# ---------- 后端状态断言 ----------
st = _exec("SELECT fsrs_state, fsrs_reps, mastery_score FROM knowledge_points WHERE id = ? AND user_id = ?", (kp_ids[0], UID), fetch=True)[0]
step("kp_fsrs_state", int(st[1]) >= 1 and st[0] is not None, f"state={st[0]} reps={st[1]} mastery={st[2]}")
st2 = _exec("SELECT review_status, fsrs_reps FROM error_questions WHERE id = ? AND user_id = ?", (eid, UID), fetch=True)[0]
step("err_reviewed_and_rated", int(st2[0]) == 1 and int(st2[1]) >= 1, f"review_status={st2[0]} reps={st2[1]}")

_purge()
lines.append("CLEANUP -> done")

result = "ALL_PASS" if not fails else "FAILS: " + ",".join(fails)
lines.append("RESULT -> " + result)
Path(OUT).write_text("\n".join(lines), encoding="utf-8")
print(result)
