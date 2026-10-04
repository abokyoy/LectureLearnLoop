# u9 E2E 验证：记·科目统计首页（种探针科目 → UI 断言与 API 一致 → 跳转冒烟 → 清理）
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
OUT = r"e:\LLM\LectureLearnLoop\server\logs\u9_verify.txt"
TOKEN = open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", encoding="utf-8").read().strip()
MOD = "U9PV" + uuid.uuid4().hex[:6]
SUBJECT = f"{MOD}_探针科"
PFX = "U9PV%"

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
    """直连执行；fetch=True 返回全部行（游标在连接关闭前取完，避免 closed cursor）。"""
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

# ---- 1) 种探针数据
r = requests.post(BASE + "/api/subjects", json={"subject_name": SUBJECT}, headers=H, timeout=15)
lines.append("SEED_SUBJECT -> " + str(r.status_code))
_exec("INSERT INTO knowledge_points (user_id, subject_name, point_name, core_description, mastery_score) VALUES (?,?,?,?,?)",
      (UID, SUBJECT, f"{MOD}点弱", "d", 20))
_exec("INSERT INTO knowledge_points (user_id, subject_name, point_name, core_description, mastery_score) VALUES (?,?,?,?,?)",
      (UID, SUBJECT, f"{MOD}点评", "d", -1))
cur = _exec("SELECT id FROM knowledge_points WHERE user_id = ? AND subject_name = ? ORDER BY id", (UID, SUBJECT), fetch=True)
kp_ids = [x[0] for x in cur]
_exec("INSERT INTO practice_records (user_id, subject_name, knowledge_point_id, question_content, user_answer, is_correct) "
      "VALUES (?,?,?,?,?,?)", (UID, SUBJECT, kp_ids[0], f"{MOD}探针题干问法", "a", 0))
rec_id = _exec("SELECT id FROM practice_records WHERE user_id = ? AND question_content = ? ORDER BY id DESC LIMIT 1",
               (UID, f"{MOD}探针题干问法"), fetch=True)[0][0]
_exec("INSERT INTO error_questions (user_id, subject_name, knowledge_point_id, practice_record_id, review_status, current_proficiency) "
      "VALUES (?,?,?,?,?,?)", (UID, SUBJECT, kp_ids[0], rec_id, 0, 15))
lines.append("SEED_DATA -> rec=" + str(rec_id))

api = requests.get(BASE + "/api/memory/overview", headers=H, timeout=15).json()["data"]
probe = next((s for s in api["subjects"] if s["subject"] == SUBJECT), None)
lines.append("API_PROBE -> " + J(probe and {k: probe[k] for k in (
    "knowledge_total", "to_learn_count", "error_cards", "errors_pending", "avg_error_proficiency")}))

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

    dash_btn = pg.evaluate("""() => {
      const b = [...document.querySelectorAll('button')].find(x => (x.textContent||'').includes('开始记忆'));
      return b ? (b.getAttribute('onclick')||'NO-ONCLICK') : 'NO-BTN';
    }""")
    lines.append("DASH_MEM_BTN -> " + dash_btn)

    pg.evaluate("handleMenuClick('memory_overview')")
    ready = False
    for _ in range(90):  # P030：轮询特征禁固定 sleep
        ready = pg.evaluate("""() => {
          const root = document.querySelector('[data-pm-page="memory_overview"]');
          return !!(root && root.querySelector('[data-subject]'));
        }""")
        if ready:
            break
        pg.wait_for_timeout(1000)
    lines.append("PAGE_READY -> " + str(ready))

    card = pg.evaluate("""subj => {
      const root = document.querySelector('[data-pm-page="memory_overview"]');
      const c = root.querySelector('[data-subject="' + CSS.escape(subj) + '"]');
      if (!c) return { found: false };
      return { found: true, text: (c.textContent || '').replace(/\\s+/g, ' ').slice(0, 500),
               goErr: c.querySelectorAll('[data-go="memory_errors"], [data-gorev]').length,
               goPoint: c.querySelectorAll('[data-gopoint]').length };
    }""", SUBJECT)
    lines.append("PROBE_CARD -> " + J(card))
    if probe and card.get("found"):
        lines.append("CONSISTENCY -> " + J({
            "to_learn_shown": str(probe["to_learn_count"]) in card["text"],
            "weak_point_shown": (MOD + "点弱") in card["text"],
            "unrated_shown": ("未评估" in card["text"]) or (probe["to_learn_count"] == 0),
            "err_rec_button": card["goErr"] >= 1,
            "mem_rec_button": card["goPoint"] >= 1,
        }))

    entry = pg.evaluate("""() => [...document.querySelectorAll('[data-pm-page="memory_overview"] [data-go]')]
        .map(x => x.getAttribute('data-go')).filter((v,i,a) => a.indexOf(v) === i)""")
    lines.append("ENTRY_CARDS -> " + J(entry))

    # 侧边栏记父项 = memory_overview；子页高亮归组
    nav = pg.evaluate("() => { const a = document.querySelector('.cl-nav-item[data-cid=\"memory_overview\"]'); return a ? a.className : 'NO-EL'; }")
    lines.append("NAV_ACTIVE -> " + ("active" if "active" in str(nav) else "INACTIVE:" + str(nav)[:120]))

    # 跳子模式：点静态入口卡“去记错题”
    pg.evaluate("""() => document.querySelector('[data-pm-page="memory_overview"] [data-go="memory_errors"]').click()""")
    ok = False
    for _ in range(30):
        ok = pg.evaluate("() => document.querySelector('[data-pm-page=\"memory_errors\"]') !== null")
        if ok:
            break
        pg.wait_for_timeout(1000)
    lines.append("GOTO_memory_errors -> " + str(ok))
    nav2 = pg.evaluate("() => { const a = document.querySelector('.cl-nav-item[data-cid=\"memory_overview\"]'); return a ? a.className : 'NO-EL'; }")
    lines.append("NAV_ACTIVE_AFTER_SUB -> " + ("active" if "active" in str(nav2) else "INACTIVE:" + str(nav2)[:120]))
    b.close()

# ---- 3) 清理
_purge()
lines.append("CLEANUP -> done")
lines.append("DIALOGS -> " + J(dialogs))
lines.append("PAGE_ERRORS -> " + (J(errs[:5]) if errs else "NONE"))
Path(OUT).write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
