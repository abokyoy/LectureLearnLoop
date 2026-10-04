# u7 冒烟：练习历史 → 开始练习 链路（种数据 + Playwright UI 断言 + 清理）
import json
import sys
import time
import uuid
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BASE = "http://127.0.0.1:6001"
OUT = r"e:\LLM\LectureLearnLoop\server\logs\u7_history_smoke.txt"
TOKEN = open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", encoding="utf-8").read().strip()
H = {"Authorization": "Bearer " + TOKEN}

PID = "u7hist-" + uuid.uuid4().hex[:8]
QTEXT = f"U7历史冒烟题目[{PID}]：请解释契约错配如何导致白页。1. 简答题"

lines = []
errs = []
dialogs = []

# ---- 1) 种一条练习历史（走正式桥端点，不直写库）
r = requests.post(BASE + "/api/practice/history", headers=H, json={
    "practice_id": PID, "questions": QTEXT, "selected_text": "U7历史冒烟材料：响应契约",
    "user_answers": "", "answer_history": "", "evaluation_result": "",
    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
})
j = r.json()
lines.append("SEED -> " + json.dumps({"status": r.status_code, "outer_ok": j.get("success"), "inner": j.get("data")}, ensure_ascii=False)[:200])
assert j.get("success")

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.on("pageerror", lambda e: errs.append("pageerror: " + str(e)[:300]))
    pg.on("dialog", lambda d: (dialogs.append(d.type + ":" + d.message[:120]), d.dismiss()))
    pg.goto(BASE + "/login", wait_until="domcontentloaded")
    pg.evaluate("t => localStorage.setItem('ll_token', t)", TOKEN)
    pg.goto(BASE + "/", wait_until="networkidle")
    pg.wait_for_timeout(1500)

    # 2) 打开 AI 窗，点击 练习历史 按钮
    r2 = pg.evaluate("""() => {
      window.openAIChatWindow();
      const btn = document.getElementById('practiceHistoryBtn');
      if (!btn) return 'NO-BTN';
      btn.click();
      return 'clicked';
    }""")
    lines.append("STEP2_OPEN_HISTORY -> " + str(r2))
    pg.wait_for_timeout(3000)

    # 3) 弹窗可见性 + 列表含种子记录
    r3 = pg.evaluate("""(pid) => {
      const modal = document.getElementById('practiceHistoryModal');
      const list = document.getElementById('practiceHistoryList');
      const items = list ? Array.from(list.querySelectorAll('.history-item')) : [];
      const hit = items.find(el => (el.dataset.practiceId || el.dataset.id) === pid);
      return JSON.stringify({
        modal_shown: modal ? modal.classList.contains('show') : null,
        item_count: items.length, seed_found: !!hit
      });
    }""", PID)
    lines.append("STEP3_MODAL -> " + str(r3))

    # 4) 选中种子项 → 点击 loadPracticeBtn（开始练习）
    r4 = pg.evaluate("""(pid) => {
      const list = document.getElementById('practiceHistoryList');
      const hit = Array.from(list.querySelectorAll('.history-item')).find(el => (el.dataset.practiceId || el.dataset.id) === pid);
      if (!hit) return 'NO-SEED-ITEM';
      hit.click();
      const sel = list.querySelectorAll('.history-item.selected').length;
      document.getElementById('loadPracticeBtn').click();
      return 'selected=' + sel + ' load_clicked';
    }""", PID)
    lines.append("STEP4_CLICK_LOAD -> " + str(r4))
    pg.wait_for_timeout(2500)

    # 5) 断言：题目区显示种子题干、练习容器可见、弹窗已关、无失败提示
    r5 = pg.evaluate("""(args) => {
      const qda = document.getElementById('questionDisplayArea');
      const pc = document.getElementById('practiceContainer');
      const modal = document.getElementById('practiceHistoryModal');
      const box = document.querySelector('.ll-alert-box');
      const t = String(qda ? qda.textContent : '');
      return JSON.stringify({
        qda_shown: qda ? qda.getClientRects().length > 0 : false,
        qda_has_seed: t.includes(args.q),
        qda_head: t.trim().slice(0, 80),
        practice_container_shown: pc ? getComputedStyle(pc).display : 'missing',
        modal_closed: modal ? !modal.classList.contains('show') : null,
        alert_if_any: box ? String(box.innerText).trim().slice(0, 150) : ''
      });
    }""", {"q": QTEXT[:20]})
    lines.append("STEP5_ASSERT -> " + str(r5))
    pg.screenshot(path=r"e:\LLM\LectureLearnLoop\server\logs\u7_history_smoke.png")
    b.close()

# ---- 6) 清理种子记录（直连库删除，仅本条）
try:
    from database import db_adapter
    import config
    conn = db_adapter.get_connection(str(config.DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM practice_sessions WHERE practice_id = ?", (PID,))
        conn.commit()
        lines.append("CLEANUP -> deleted rowcount=" + str(cur.rowcount))
    finally:
        conn.close()
except Exception as e:
    lines.append("CLEANUP_ERR -> " + str(e)[:200])

lines.append("DIALOGS: " + (str(dialogs[:8]) if dialogs else "NONE"))
lines.append("PAGE_ERRORS: " + (str(errs[:10]) if errs else "NONE"))
open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("done")
