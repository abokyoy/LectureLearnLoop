# 诊断：主壳是否定义 pmUtil/handleMenuClick + console/pageerror 捕获
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:6001"
TOKEN = open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", encoding="utf-8").read().strip()
out = []
errs = []
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.on("pageerror", lambda e: errs.append("pageerror: " + str(e)[:300]))
    pg.on("console", lambda m: out.append("console:" + m.type + ":" + m.text[:200]) if m.type in ("error",) else None)
    pg.goto(BASE + "/login", wait_until="domcontentloaded")
    pg.evaluate("t => localStorage.setItem('ll_token', t)", TOKEN)
    pg.goto(BASE + "/", wait_until="networkidle")
    pg.wait_for_timeout(3000)
    info = pg.evaluate("""() => ({
        pmUtil: typeof window.pmUtil,
        handleMenuClick: typeof window.handleMenuClick,
        PmPages: typeof window.PmPages,
        bridge: typeof window.bridge,
        scripts: [...document.querySelectorAll('script')].map(s => s.src.split('/').pop()).slice(-8),
        frags: [...document.querySelectorAll('[data-pm-page]')].map(x => x.getAttribute('data-pm-page')).slice(0, 5),
    })""")
    out.append("INFO -> " + json.dumps(info, ensure_ascii=False))
    out.append("ERRS -> " + json.dumps(errs[:8], ensure_ascii=False))
    b.close()
Path(r"e:\LLM\LectureLearnLoop\server\logs\u13_diag.txt").write_text("\n".join(out), encoding="utf-8")
print("\n".join(out))
