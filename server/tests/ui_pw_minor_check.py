# 批2 Minor 修复复验：1) llm_logs 直访时设置项点亮（别名归组） 2) 头像 title 携带账号信息
import json
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:6001"
TOKEN = open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", encoding="utf-8").read().strip()
OUT = r"e:\LLM\LectureLearnLoop\server\logs\ui_minor_verify.txt"

lines = []
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.goto(BASE + "/login", wait_until="domcontentloaded")
    pg.evaluate("t => localStorage.setItem('ll_token', t)", TOKEN)

    # 1) llm_logs 直访
    pg.goto(BASE + "/llm_logs", wait_until="networkidle")
    pg.wait_for_timeout(1500)
    active = pg.evaluate("() => { const el = document.querySelector('.cl-nav-item.cl-active'); return el ? el.getAttribute('data-cid') : null; }")
    lines.append(f"llm_logs direct: active_nav={active} (expect settings)")

    # 2) dashboard 头像 title
    pg.goto(BASE + "/", wait_until="networkidle")
    pg.wait_for_timeout(2500)
    title = pg.evaluate("() => { const el = document.getElementById('user-avatar-btn'); return el ? el.title : null; }")
    lines.append(f"dashboard avatar title={title!r} (expect non-empty with 用户设置)")

    b.close()

open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\n".join(lines))
