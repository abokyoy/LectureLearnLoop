# 批3 收缩按钮回归验证：点击折叠无 JS 异常 + 新建按钮隐藏 + 图标 href 翻转
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:6001"
TOKEN = open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", encoding="utf-8").read().strip()
OUT = r"e:\LLM\LectureLearnLoop\server\logs\ui_b3_collapse.txt"

errs = []
lines = []
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append("console.error:" + m.text) if m.type == "error" else None)
    pg.goto(BASE + "/login", wait_until="domcontentloaded")
    pg.evaluate("t => localStorage.setItem('ll_token', t)", TOKEN)
    pg.goto(BASE + "/online_course", wait_until="networkidle")
    pg.wait_for_timeout(4000)

    def use_href():
        return pg.evaluate("() => { const u=document.querySelector('#collapse-toggle-btn use'); return u?u.getAttribute('href'):null; }")
    def newfolder_visible():
        return pg.evaluate("() => { const btns=document.querySelectorAll('#file-structure .panel-actions button'); const b=btns[0]; return b ? !!b.offsetParent : null; }")

    lines.append("before: use=" + str(use_href()) + " newfolder_visible=" + str(newfolder_visible()))
    pg.click("#collapse-toggle-btn")
    pg.wait_for_timeout(600)
    lines.append("after collapse: use=" + str(use_href()) + " newfolder_visible=" + str(newfolder_visible()))
    pg.click("#collapse-toggle-btn")
    pg.wait_for_timeout(600)
    lines.append("after expand: use=" + str(use_href()) + " newfolder_visible=" + str(newfolder_visible()))
    lines.append("JS errors: " + (str(errs) if errs else "NONE"))
    b.close()

open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\n".join(lines))
