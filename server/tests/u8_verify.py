# u8 E2E 验证：练·科目统计首页（种探针科目 → UI 断言与 API 一致 → 跳转冒烟 → 清理）
import base64
import json
import sys
import uuid
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BASE = "http://127.0.0.1:6001"
OUT = r"e:\LLM\LectureLearnLoop\server\logs\u8_verify.txt"
TOKEN = open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", encoding="utf-8").read().strip()
MOD = "U8PV" + uuid.uuid4().hex[:6]
SUBJECT = f"{MOD}_探针科"

lines = []
errs = []
dialogs = []


def J(x):
    return json.dumps(x, ensure_ascii=False)


def _uid_from_jwt(tk):
    seg = tk.split(".")[1]
    seg += "=" * (-len(seg) % 4)
    pl = json.loads(base64.urlsafe_b64decode(seg))
    return pl.get("uid") or pl.get("user_id")


H = {"Authorization": "Bearer " + TOKEN}
UID = _uid_from_jwt(TOKEN)


def _purge_prefix():
    """开头清扫历史 U8PV 探针残留（每次运行前执行，保证可重跑）。"""
    c = db_adapter.get_connection(str(config.DB_PATH))
    try:
        c0 = c.cursor()
        c0.execute("SELECT id FROM knowledge_points WHERE user_id = ? AND subject_name LIKE ?", (UID, "U8PV%"))
        pids = [x[0] for x in c0.fetchall()]
        if pids:
            c0.execute("DELETE FROM knowledge_point_sources WHERE knowledge_point_id IN ("
                       + ",".join(str(int(i)) for i in pids) + ")")
            c0.execute("DELETE FROM knowledge_points WHERE user_id = ? AND subject_name LIKE ?", (UID, "U8PV%"))
        c0.execute("DELETE FROM practice_records WHERE user_id = ? AND subject_name LIKE ?", (UID, "U8PV%"))
        c0.execute("DELETE FROM error_questions WHERE user_id = ? AND subject_name LIKE ?", (UID, "U8PV%"))
        c0.execute("DELETE FROM user_subjects WHERE user_id = ? AND subject_name LIKE ?", (UID, "U8PV%"))
        c.commit()
    finally:
        c.close()


from database import db_adapter
import config
_purge_prefix()
lines.append("PURGE_PREFIX -> done")

# ---- 1) HTTP 种探针数据：科目 + 2 知识点（1 个 -1 未评）+ 1 条练习记录
r = requests.post(BASE + "/api/subjects", json={"subject_name": SUBJECT}, headers=H, timeout=15)
lines.append("SEED_SUBJECT -> " + str(r.status_code))
r = requests.post(BASE + "/api/knowledge/batch-save", json={
    "filePath": f"u8pv_{MOD}.md", "subject": SUBJECT,
    "knowledgePoints": [{"name": f"{MOD}点甲", "description": "d"}, {"name": f"{MOD}点乙", "description": "d"}],
}, headers=H, timeout=20)
sd = r.json().get("data") or {}
lines.append("SEED_POINTS -> saved=" + str(sd.get("saved_count")))

conn = db_adapter.get_connection(str(config.DB_PATH))
try:
    cur = conn.cursor()
    cur.execute("SELECT id FROM knowledge_points WHERE user_id = ? AND subject_name = ? ORDER BY id", (UID, SUBJECT))
    ids = [x[0] for x in cur.fetchall()]
    cur.execute("UPDATE knowledge_points SET mastery_score = 30 WHERE id = ?", (ids[0],))  # 乙/甲评分，另一保持 -1
    cur.execute(
        "INSERT INTO practice_records (user_id, subject_name, knowledge_point_id, question_content, user_answer, is_correct) "
        "VALUES (?,?,?,?,?,?)", (UID, SUBJECT, ids[0], "u8探针题", "ans", 0))
    conn.commit()
    lines.append("SEED_SCORES -> ids=" + J(ids))
finally:
    conn.close()

api = requests.get(BASE + "/api/practice/overview", headers=H, timeout=15).json()["data"]
probe = next((s for s in api["subjects"] if s["subject"] == SUBJECT), None)
lines.append("API_PROBE -> " + J(probe and {k: probe[k] for k in (
    "knowledge_count", "unrated_count", "avg_mastery", "practice_count", "errors_pending", "recommend")}))

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

    # 2a) 工作台"开始练习"按钮指向总览
    dash_btn = pg.evaluate("""() => {
      const btns = [...document.querySelectorAll('button')];
      const b = btns.find(x => (x.textContent||'').includes('开始练习'));
      return b ? (b.getAttribute('onclick')||'') : 'NO-BTN';
    }""")
    lines.append("DASH_BTN -> " + dash_btn)

    # 2b) 进入练习总览（点侧边栏练父项）
    pg.evaluate("handleMenuClick('practice_overview')")
    ready = False
    for _ in range(90):  # P030：脚本链竞态，轮询特征禁固定 sleep
        ready = pg.evaluate("""() => {
          const root = document.querySelector('[data-pm-page="practice_overview"]');
          return !!(root && root.querySelector('[data-subject]'));
        }""")
        if ready:
            break
        pg.wait_for_timeout(1000)
    lines.append("PAGE_READY -> " + str(ready))

    card = pg.evaluate("""subj => {
      const root = document.querySelector('[data-pm-page="practice_overview"]');
      const c = root.querySelector('[data-subject="' + CSS.escape(subj) + '"]');
      if (!c) return { found: false };
      return {
        found: true,
        text: (c.textContent || '').replace(/\\s+/g, ' ').slice(0, 400),
        recBtns: c.querySelectorAll('[data-gopoint]').length,
        metrics: [...c.querySelectorAll('.grid > div > div:first-child')].map(x => x.textContent.trim()),
      };
    }""", SUBJECT)
    lines.append("PROBE_CARD -> " + J(card))
    if probe and card.get("found"):
        cons = {
            "knowledge_count_in_text": str(probe["knowledge_count"]) in card["text"],
            "unrated_in_rec_or_line": ("未评估" in card["text"]) or (probe["unrated_count"] == 0),
            "point_name_shown": (MOD + "点甲") in card["text"] or (MOD + "点乙") in card["text"],
            "rec_btn_count>=1": card["recBtns"] >= 1,
        }
        lines.append("CONSISTENCY -> " + J(cons))

    # 2c) 子模式入口卡存在 + 点击"去练错题"跳转冒烟
    entry = pg.evaluate("""() => {
      const go = [...document.querySelectorAll('[data-pm-page="practice_overview"] [data-go]')].map(b => b.getAttribute('data-go'));
      return go;
    }""")
    lines.append("ENTRY_CARDS -> " + J(entry))
    # u8 评审 MINOR 修复验证：静态卡去重后，点一张入口卡只允许发 1 次 loadContent
    pg.evaluate("""() => { window.__navCount = 0;
      const orig = window.bridge.loadContent;
      window.bridge.loadContent = function (cid) { window.__navCount++; return orig.apply(this, arguments); }; }""")
    pg.evaluate("""() => {
      document.querySelector('[data-pm-page="practice_overview"] [data-go="practice_errors"]').click();
    }""")
    pg.wait_for_timeout(800)
    lines.append("NAV_CLICK_COUNT -> " + str(pg.evaluate("window.__navCount")))
    ok_err = False
    for _ in range(30):
        ok_err = pg.evaluate("() => document.querySelector('[data-pm-page=\"practice_errors\"]') !== null")
        if ok_err:
            break
        pg.wait_for_timeout(1000)
    lines.append("GOTO_practice_errors -> " + str(ok_err))
    hl = pg.evaluate("() => { const a = document.querySelector('.cl-nav-item[data-cid=\"practice_overview\"]'); return a ? a.className : 'NO-EL'; }")
    lines.append("NAV_ACTIVE -> " + ("active" if "active" in str(hl) else "INACTIVE:" + str(hl)[:120]))

    # 2d) 回总览点推荐"去练习"：u10 新契约 = 写旗标直达 knowledge_point 详情页（不经过脑图），
    #     旗标由详情页 boot 消费后即删（None = 消费成功），页面片段须是 knowledge_point 而非 practice_materials
    pg.evaluate("handleMenuClick('practice_overview')")
    for _ in range(60):
        has = pg.evaluate("() => !!document.querySelector('[data-pm-page=\"practice_overview\"] [data-gopoint]')")
        if has:
            break
        pg.wait_for_timeout(1000)
    pg.evaluate("localStorage.removeItem('pm_pending_point')")
    pg.evaluate("""() => document.querySelector('[data-pm-page="practice_overview"] [data-gopoint]').click();""")
    ok_kp = False
    for _ in range(60):
        ok_kp = pg.evaluate("() => !!document.querySelector('[data-pm-page=\"knowledge_point\"]')")
        if ok_kp:
            break
        pg.wait_for_timeout(1000)
    flag = pg.evaluate("() => localStorage.getItem('pm_pending_point')")
    lines.append("GOPPOINT_FLAG_CONSUMED -> " + str(flag is None))
    still_mm = pg.evaluate("() => !!document.querySelector('[data-pm-page=\"practice_materials\"]')")
    lines.append("GOPPOINT_NAV -> " + str(ok_kp and not still_mm))
    b.close()

# ---- 3) 清理探针数据（仅本科）
conn = db_adapter.get_connection(str(config.DB_PATH))
try:
    cur = conn.cursor()
    cur.execute("SELECT id FROM knowledge_points WHERE user_id = ? AND subject_name = ?", (UID, SUBJECT))
    pids = [x[0] for x in cur.fetchall()]
    if pids:
        cur.execute("DELETE FROM knowledge_point_sources WHERE knowledge_point_id = ANY(%s)"
                    if False else "DELETE FROM knowledge_point_sources WHERE knowledge_point_id IN ("
                    + ",".join(str(int(i)) for i in pids) + ")")
    cur.execute("DELETE FROM knowledge_points WHERE user_id = ? AND subject_name = ?", (UID, SUBJECT))
    cur.execute("DELETE FROM practice_records WHERE user_id = ? AND subject_name = ?", (UID, SUBJECT))
    cur.execute("DELETE FROM error_questions WHERE user_id = ? AND subject_name = ?", (UID, SUBJECT))
    cur.execute("DELETE FROM user_subjects WHERE user_id = ? AND subject_name = ?", (UID, SUBJECT))
    conn.commit()
    lines.append("CLEANUP -> done points=" + J(pids))
finally:
    conn.close()

lines.append("DIALOGS -> " + J(dialogs))
lines.append("PAGE_ERRORS -> " + (J(errs[:5]) if errs else "NONE"))
Path(OUT).write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
