# 批3 验证：默认预览态 + 点击编辑后分段按钮应为橙字白底（非蓝）
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:6001"
TOKEN = open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", encoding="utf-8").read().strip()
SHOT = r"e:\LLM\LectureLearnLoop\design\walkthrough\b3_ocn_after.png"
SHOT_EDIT = r"e:\LLM\LectureLearnLoop\design\walkthrough\b3_ocn_edit.png"
OUT = r"e:\LLM\LectureLearnLoop\server\logs\ui_b3_verify.txt"

lines = []
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.goto(BASE + "/login", wait_until="domcontentloaded")
    pg.evaluate("t => localStorage.setItem('ll_token', t)", TOKEN)
    pg.goto(BASE + "/online_course", wait_until="networkidle")
    pg.wait_for_timeout(4000)
    pg.screenshot(path=SHOT)

    def bg_of(sel):
        return pg.evaluate("s => { const el=document.querySelector(s); return el?getComputedStyle(el).backgroundColor:null; }", sel)

    lines.append("preview-btn bg (default) = " + str(bg_of("#preview-btn")))
    # 点击编辑，验证 preview 变透明、edit 变白底（不应出现蓝色 59,130,246）
    try:
        pg.click("#edit-btn", timeout=5000)
        pg.wait_for_timeout(1200)
        lines.append("after click edit -> edit-btn bg = " + str(bg_of("#edit-btn")))
        lines.append("after click edit -> preview-btn bg = " + str(bg_of("#preview-btn")))
        pg.screenshot(path=SHOT_EDIT)
    except Exception as e:
        lines.append("edit click err: " + str(e))
    b.close()

open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\n".join(lines))
