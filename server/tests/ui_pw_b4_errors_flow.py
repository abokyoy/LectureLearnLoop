# 批4 补验：先用真实 API 给测试账号造 2 道错题（is_correct=false 自动入错题库），
# 再用 Playwright 验证 practice_errors / memory_errors 的行展开、搜索、标记已复习全链路。
import json
import sys
import requests

BASE = "http://127.0.0.1:6001"
TOKEN = open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", encoding="utf-8").read().strip()
OUT = r"e:\LLM\LectureLearnLoop\server\logs\ui_b4_errors_flow.txt"
H = {"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"}

lines = []

# ---- 1. 造真实错题（走 /api/practice/results，与业务链路一致；学科名动态取，避免硬编码不匹配） ----
subs = requests.get(BASE + "/api/subjects", headers=H, timeout=15).json()
subject = (subs.get("data") or ["Python基础"])[0]
lines.append("subject_used: " + repr(subject))
pts = requests.get(BASE + "/api/knowledge/points?subject=" + requests.utils.quote(subject), headers=H, timeout=15).json()
if not pts.get("success") or not pts.get("data"):
    print("NO_KNOWLEDGE_POINTS", json.dumps(pts, ensure_ascii=False))
    sys.exit(1)
kp_id = pts["data"][0]["id"]
records = [
    {"subject_name": subject, "knowledge_point_id": kp_id,
     "question_content": "构造函数的作用是？（批4测试题A）", "user_answer": "错误回答A",
     "is_correct": False, "correct_answer": "对象初始化时自动执行", "explanation": "与类同名，用于建立对象初始状态"},
    {"subject_name": subject, "knowledge_point_id": kp_id,
     "question_content": "多态的分派依据是什么？（批4测试题B）", "user_answer": "错误回答B",
     "is_correct": False, "correct_answer": "运行时按对象实际类型分派", "explanation": "同一接口不同实现"},
]
r = requests.post(BASE + "/api/practice/results", headers=H, json={"records": records}, timeout=15).json()
lines.append("seed_results: " + json.dumps(r, ensure_ascii=False))

# ---- 2. Playwright 验证两页错题交互 ----
from playwright.sync_api import sync_playwright

errs = []
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.on("pageerror", lambda e: errs.append("pageerror:" + str(e)))
    pg.on("console", lambda m: errs.append("console.error:" + m.text) if m.type == "error" else None)
    pg.goto(BASE + "/login", wait_until="domcontentloaded")
    pg.evaluate("t => localStorage.setItem('ll_token', t)", TOKEN)
    pg.goto(BASE + "/", wait_until="networkidle")
    pg.wait_for_timeout(2000)

    def go(cid):
        pg.evaluate("cid => handleMenuClick(cid)", cid)
        pg.wait_for_timeout(2500)

    # practice_errors：行渲染 + 展开 + 搜索命中/未命中
    go("practice_errors")
    rows = pg.locator("[data-pm-page='practice_errors'] [data-eid]").count()
    lines.append(f"practice_errors: rows={rows}")
    pg.screenshot(path=r"e:\LLM\LectureLearnLoop\design\walkthrough\b4_practice_errors.png")
    if rows:
        pg.locator("[data-pm-page='practice_errors'] .pm-q-toggle").first.click()
        pg.wait_for_timeout(400)
        opened = pg.evaluate("() => { const d=document.querySelector('[data-pm-page=\"practice_errors\"] [data-detail]:not(.hidden)'); return !!d; }")
        lines.append(f"practice_errors: detail_open={opened}")
        pg.fill("[data-pm-page='practice_errors'] [data-role='search']", "测试题B")
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(500)
        lines.append(f"practice_errors: search_hit_rows={pg.locator('[data-pm-page=\"practice_errors\"] [data-eid]').count()}")
        pg.fill("[data-pm-page='practice_errors'] [data-role='search']", "zzz无")
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(500)
        lines.append(f"practice_errors: search_miss_empty={pg.locator('[data-pm-page=\"practice_errors\"] .cl-empty').count()}")
        pg.fill("[data-pm-page='practice_errors'] [data-role='search']", "")
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(500)

    # memory_errors：完成度概览 + 标记已复习真实写库
    go("memory_errors")
    rows2 = pg.locator("[data-pm-page='memory_errors'] [data-eid]").count()
    btns = pg.locator("[data-pm-page='memory_errors'] .pm-review-btn").count()
    stat0 = pg.locator("[data-pm-page='memory_errors'] [data-role='stat']").inner_text().replace("\n", " ")
    lines.append(f"memory_errors: rows={rows2} review_btns={btns} stat_before='{stat0}'")
    if btns:
        pg.locator("[data-pm-page='memory_errors'] .pm-review-btn").first.click()
        pg.wait_for_timeout(2500)
        stat1 = pg.locator("[data-pm-page='memory_errors'] [data-role='stat']").inner_text().replace("\n", " ")
        badge = pg.locator("[data-pm-page='memory_errors'] >> text=已复习").count()
        btns1 = pg.locator("[data-pm-page='memory_errors'] .pm-review-btn").count()
        lines.append(f"memory_errors: stat_after='{stat1}' reviewed_badges={badge} btns_after={btns1}")
    pg.screenshot(path=r"e:\LLM\LectureLearnLoop\design\walkthrough\b4_memory_errors.png")

    # 复习后 practice_knowledge 的相关错题面板联动
    go("practice_knowledge")
    if pg.locator(".pm-kp-errors").count():
        pg.locator(".pm-kp-errors").first.click()
        pg.wait_for_timeout(1500)
        txt = pg.locator("[data-kp-detail]").first.inner_text().replace("\n", " ")
        lines.append(f"practice_knowledge: kp_errors_panel='{txt[:120]}'")
    b.close()

lines.append("JS_ERRORS: " + (str(errs[:6]) if errs else "NONE"))
open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("done")
