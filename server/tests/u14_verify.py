# u14 E2E 验证：记错题翻卡复习（种新旧两类错题 → 总览推荐直达 → 翻卡/标记/完成页/巩固轮/列表切换 → 清理）
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
OUT = r"e:\LLM\LectureLearnLoop\server\logs\u14_verify.txt"
TOKEN = open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", encoding="utf-8").read().strip()
MOD = "U14PV" + uuid.uuid4().hex[:6]
SUBJECT = f"{MOD}_翻卡科"
SUBJECT2 = f"{MOD}_次科"   # 非第一学科直达回归（CodeReview Major-2）
PFX = "U14PV%"
QA = f"{MOD}翻卡题干A单选"   # 新格式：带选项，熟练度 20（裸中文选项，无字母前缀，同 LLM 真实产出）
QB = f"{MOD}翻卡题干B旧题"   # 存量降级：无选项，熟练度 50
QC = f"{MOD}次科直达题干C"   # 种在 SUBJECT2，熟练度 10

lines = []
errs = []
dialogs = []


def J(x):
    return json.dumps(x, ensure_ascii=False)


def step(name, ok, detail=""):
    lines.append(f"{'PASS' if ok else 'FAIL'} {name} {detail}")
    return ok


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
            ph = ",".join(str(int(i)) for i in pids)
            cur.execute("DELETE FROM knowledge_point_sources WHERE knowledge_point_id IN (" + ph + ")")
            cur.execute("DELETE FROM knowledge_points WHERE user_id = ? AND subject_name LIKE ?", (UID, PFX))
        for t in ("practice_records", "error_questions", "favorite_questions"):
            cur.execute(f"DELETE FROM {t} WHERE user_id = ? AND subject_name LIKE ?", (UID, PFX))
        cur.execute("DELETE FROM user_subjects WHERE user_id = ? AND subject_name LIKE ?", (UID, PFX))
        c.commit()
    finally:
        c.close()


_purge()
lines.append("PURGE -> done")

# ---- 1) 种数据：A 新格式带选项 prof=20，B 存量无选项 prof=50
requests.post(BASE + "/api/subjects", json={"subject_name": SUBJECT}, headers=H, timeout=15)
_exec("INSERT INTO knowledge_points (user_id, subject_name, point_name, core_description, mastery_score) VALUES (?,?,?,?,?)",
      (UID, SUBJECT, f"{MOD}点", "d", 30))
kp_id = _exec("SELECT id FROM knowledge_points WHERE user_id = ? AND subject_name = ? ORDER BY id DESC LIMIT 1",
              (UID, SUBJECT), fetch=True)[0][0]
OPTS_A = ["甲选项", "乙选项", "丙选项", "丁选项"]
_exec("INSERT INTO practice_records (user_id, subject_name, knowledge_point_id, question_content, user_answer, is_correct, question_type, options_json) "
      "VALUES (?,?,?,?,?,?,?,?)",
      (UID, SUBJECT, kp_id, QA, "A", 0, "single", json.dumps(OPTS_A, ensure_ascii=False)))
_exec("INSERT INTO practice_records (user_id, subject_name, knowledge_point_id, question_content, user_answer, is_correct) "
      "VALUES (?,?,?,?,?,?)", (UID, SUBJECT, kp_id, QB, "x", 0))
recs = {r[0]: r[1] for r in _exec(
    "SELECT question_content, id FROM practice_records WHERE user_id = ? AND subject_name = ?", (UID, SUBJECT), fetch=True)}
_exec("INSERT INTO error_questions (user_id, subject_name, knowledge_point_id, practice_record_id, review_status, current_proficiency, correct_answer, explanation) "
      "VALUES (?,?,?,?,?,?,?,?)", (UID, SUBJECT, kp_id, recs[QA], 0, 20, "B", f"{MOD}解析B是正解"))
_exec("INSERT INTO error_questions (user_id, subject_name, knowledge_point_id, practice_record_id, review_status, current_proficiency, correct_answer, explanation) "
      "VALUES (?,?,?,?,?,?,?,?)", (UID, SUBJECT, kp_id, recs[QB], 0, 50, "y", f"{MOD}旧题解析"))
api_errors = requests.get(BASE + "/api/kb/errors", headers=H, params={"subject": SUBJECT}, timeout=15).json()["data"]
ea = next((x for x in api_errors if x["question_content"] == QA), None)
eb = next((x for x in api_errors if x["question_content"] == QB), None)
step("SEED_API_OPTIONS", bool(ea) and ea.get("options") == OPTS_A
     and ea.get("question_type") == "single" and eb is not None and eb.get("options") is None,
     f"ea.type={ea and ea.get('question_type')} eb.opts={eb and eb.get('options')}")
eid_a = ea["id"]

# 第二学科（排序在 SUBJECT 之后）：直达旗标非第一学科回归用
requests.post(BASE + "/api/subjects", json={"subject_name": SUBJECT2}, headers=H, timeout=15)
_exec("INSERT INTO knowledge_points (user_id, subject_name, point_name, core_description, mastery_score) VALUES (?,?,?,?,?)",
      (UID, SUBJECT2, f"{MOD}次点", "d", 30))
kp2 = _exec("SELECT id FROM knowledge_points WHERE user_id = ? AND subject_name = ? ORDER BY id DESC LIMIT 1",
            (UID, SUBJECT2), fetch=True)[0][0]
_exec("INSERT INTO practice_records (user_id, subject_name, knowledge_point_id, question_content, user_answer, is_correct, question_type, options_json) "
      "VALUES (?,?,?,?,?,?,?,?)",
      (UID, SUBJECT2, kp2, QC, "错答", 0, "single", json.dumps(["丙选项", "丁选项"], ensure_ascii=False)))
rec_c = _exec("SELECT id FROM practice_records WHERE user_id = ? AND question_content = ? ORDER BY id DESC LIMIT 1",
              (UID, QC), fetch=True)[0][0]
_exec("INSERT INTO error_questions (user_id, subject_name, knowledge_point_id, practice_record_id, review_status, current_proficiency, correct_answer, explanation) "
      "VALUES (?,?,?,?,?,?,?,?)", (UID, SUBJECT2, kp2, rec_c, 0, 10, "D", f"{MOD}次科解析"))
eid_c = _exec("SELECT id FROM error_questions WHERE user_id = ? AND subject_name = ? ORDER BY id DESC LIMIT 1",
              (UID, SUBJECT2), fetch=True)[0][0]
lines.append("SEED_SUBJ2 -> eid_c=" + str(eid_c))

# ---- 2) Playwright 翻卡旅程
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.on("pageerror", lambda e: errs.append("pageerror: " + str(e)[:300]))
    pg.on("dialog", lambda d: (dialogs.append(d.type + ":" + d.message[:80]), d.dismiss()))
    pg.goto(BASE + "/login", wait_until="domcontentloaded")
    pg.evaluate("t => localStorage.setItem('ll_token', t)", TOKEN)
    pg.goto(BASE + "/", wait_until="networkidle")
    pg.wait_for_timeout(800)

    pg.evaluate("handleMenuClick('memory_overview')")
    got_recs = False
    for _ in range(90):  # P030：轮询特征禁固定 sleep
        got_recs = pg.evaluate("""subj => {
          const root = document.querySelector('[data-pm-page="memory_overview"]');
          const c = root && root.querySelector('[data-subject="' + CSS.escape(subj) + '"]');
          return !!(c && c.querySelector('[data-gorev]'));
        }""", SUBJECT)
        if got_recs:
            break
        pg.wait_for_timeout(1000)
    step("OVERVIEW_REC_BTN", got_recs, f"eid={eid_a}")

    # 直达：点推荐「去复习」→ memory_errors 卡片模式，队列首位=prof 最低（新题 A）
    pg.evaluate("""a => document.querySelector('[data-pm-page="memory_overview"] [data-gorev="' + a + '"]').click()""", str(eid_a))
    pg.wait_for_function("""qa => {
      const el = document.querySelector('[data-pm-page="memory_errors"] [data-role="flip-card"]');
      return !!el && (el.textContent || '').includes(qa);
    }""", arg=QA, timeout=60000)
    front = pg.evaluate("""qa => {
      const root = document.querySelector('[data-pm-page="memory_errors"]');
      const card = root.querySelector('[data-role="flip-card"]');
      const ff = card.querySelector('.pm-flip-face:not(.pm-flip-back)');
      const t = (ff.textContent || '').replace(/\\s+/g, ' ');
      return { hasA: t.includes(qa), optCount: ff.querySelectorAll('.rounded-clbtn').length,
               highlightOnFront: ff.querySelectorAll('.bg-cl-secondary-soft').length,
               noOldHint: !t.includes('该题未保存选项') };
    }""", QA)
    step("FRONT_CARD_A", front["hasA"] and front["optCount"] == 4 and front["highlightOnFront"] == 0 and front["noOldHint"], J(front))

    # 点卡翻面：背面正确项（B）高亮 + 答案解析可见
    pg.click('[data-pm-page="memory_errors"] [data-role="flip-card"]')
    pg.wait_for_timeout(700)
    back = pg.evaluate("""qa => {
      const card = document.querySelector('[data-pm-page="memory_errors"] [data-role="flip-card"]');
      const bk = card.querySelector('.pm-flip-back');
      const t = (bk.textContent || '').replace(/\\s+/g, ' ');
      return { flipped: card.classList.contains('is-flipped'), hasAns: t.includes('正确答案'),
               hasExp: t.includes('解析B是正解'), hl: bk.querySelectorAll('.bg-cl-secondary-soft').length };
    }""", QA)
    step("FLIP_BACK_A", back["flipped"] and back["hasAns"] and back["hasExp"] and back["hl"] == 1, J(back))

    # 标记已复习 → 移出队列，旧题 B 顶上并显示存量降级提示
    pg.click('[data-pm-page="memory_errors"] [data-nav="mark"]')
    pg.wait_for_function("""qb => {
      const el = document.querySelector('[data-pm-page="memory_errors"] [data-role="flip-card"]');
      return !!el && (el.textContent || '').includes(qb);
    }""", arg=QB, timeout=30000)
    second = pg.evaluate("""qb => {
      const root = document.querySelector('[data-pm-page="memory_errors"]');
      const card = root.querySelector('[data-role="flip-card"]');
      const t = (card.textContent || '').replace(/\\s+/g, ' ');
      const prog = (root.textContent.match(/第 \\d+ \\/ \\d+ 题/) || [''])[0];
      return { hasB: t.includes(qb), oldHint: t.includes('该题未保存选项'), prog };
    }""", QB)
    step("MARK_NEXT_OLD_HINT", second["hasB"] and second["oldHint"] and second["prog"] == "第 1 / 1 题", J(second))

    # 再标记 → 完成页
    pg.click('[data-pm-page="memory_errors"] [data-nav="mark"]')
    pg.wait_for_function("() => [...document.querySelectorAll('[data-pm-page=\"memory_errors\"] button')].some(x => (x.textContent||'').includes('再翻已复习的'))", timeout=30000)
    done = pg.evaluate("""() => {
      const root = document.querySelector('[data-pm-page="memory_errors"]');
      const t = (root.textContent || '').replace(/\\s+/g, ' ');
      return { doneText: t.includes('本学科错题全部复习完了'),
               againBtn: [...root.querySelectorAll('button')].some(x => (x.textContent||'').includes('再翻已复习的')) };
    }""")
    step("COMPLETE_PAGE", done["doneText"] and done["againBtn"], J(done))

    # 巩固轮：再翻已复习的 → 2 张卡回到队列，徽标切「巩固轮」
    pg.click('[data-pm-page="memory_errors"] [data-round="done"]')
    pg.wait_for_timeout(600)
    cons = pg.evaluate("""qa => {
      const root = document.querySelector('[data-pm-page="memory_errors"]');
      const card = root.querySelector('[data-role="flip-card"]');
      const t = (root.textContent || '').replace(/\\s+/g, ' ');
      return { backCard: !!card, badge: t.includes('巩固轮'), prog: (t.match(/第 \\d+ \\/ 2 题/) || [''])[0] };
    }""", QA)
    step("DONE_ROUND_RESTART", cons["backCard"] and cons["badge"] and cons["prog"] == "第 1 / 2 题", J(cons))

    # 切列表：errorRow 展开区含选项（索引字母前缀 + 正确项高亮）
    pg.click('[data-pm-page="memory_errors"] [data-modesw="list"]')
    pg.wait_for_timeout(600)
    lst = pg.evaluate(f"""qa => {{
      const root = document.querySelector('[data-pm-page="memory_errors"]');
      const rows = root.querySelectorAll('[data-eid]');
      const d = root.querySelector('[data-detail="{eid_a}"]');
      if (d) d.classList.remove('hidden');
      const t = d ? (d.textContent || '').replace(/\\s+/g, ' ') : '';
      return {{ rowCount: rows.length, prefixedOpts: t.includes('A. 甲选项') && t.includes('B. 乙选项'), hlText: t.includes('乙选项') && !t.includes('丙选项 ') , hl: d ? d.querySelectorAll('.bg-cl-secondary-soft').length : 0 }};
    }}""", QA)
    step("LIST_MODE_OPTIONS", lst["rowCount"] == 2 and lst["prefixedOpts"] and lst["hl"] == 1, J(lst))

    # 非第一学科直达：写旗标后直接进记错题页，初始学科必须落在 SUBJECT2（CodeReview Major-2 回归）
    pg.evaluate("""(a) => { localStorage.setItem('pm_pending_review', JSON.stringify({ subject: a[0], eid: String(a[1]), ts: Date.now() })); }""", [SUBJECT2, eid_c])
    pg.evaluate("handleMenuClick('memory_errors')")
    pg.wait_for_function("""qc => {
      const el = document.querySelector('[data-pm-page="memory_errors"] [data-role="flip-card"]');
      return !!el && (el.textContent || '').includes(qc);
    }""", arg=QC, timeout=60000)
    subj2 = pg.evaluate("""(a) => {
      // SPA 切页保留旧 DOM：全页 active chip 会包含首次直达的 SUBJECT；断言本次旗标落在 SUBJECT2 且无关学科不高亮
      const active = [...document.querySelectorAll('[data-subj]')].filter(x => (x.className || '').includes('bg-cl-primary')).map(x => x.getAttribute('data-subj'));
      const card = document.querySelector('[data-pm-page="memory_errors"] [data-role="flip-card"]');
      const t = (card.textContent || '').replace(/\\s+/g, ' ');
      return { active, hasQC: t.includes(a[1]) };
    }""", [SUBJECT, QC])
    step("DIRECT_JUMP_SUBJ2", SUBJECT in subj2["active"] and SUBJECT2 in subj2["active"] and subj2["hasQC"], J(subj2))

    b.close()

# ---- 3) 清理
_purge()
lines.append("CLEANUP -> done")
lines.append("DIALOGS -> " + J(dialogs))
lines.append("PAGE_ERRORS -> " + (J(errs[:5]) if errs else "NONE"))
fails = [l for l in lines if l.startswith("FAIL")]
lines.append("RESULT -> " + ("ALL_PASS" if not fails and not errs else f"FAIL:{len(fails)} errs:{len(errs)}"))
Path(OUT).write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
