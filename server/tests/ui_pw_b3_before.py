# 批3 走查：新壳下网课笔记页当前截图（改造前基线）
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:6001"
TOKEN = open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", encoding="utf-8").read().strip()
OUT = r"e:\LLM\LectureLearnLoop\design\walkthrough\b3_ocn_before.png"

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.goto(BASE + "/login", wait_until="domcontentloaded")
    pg.evaluate("t => localStorage.setItem('ll_token', t)", TOKEN)
    pg.goto(BASE + "/online_course", wait_until="networkidle")
    pg.wait_for_timeout(4000)  # 等 jsTree 加载渲染
    pg.screenshot(path=OUT)
    b.close()
print("shot saved:", OUT)
