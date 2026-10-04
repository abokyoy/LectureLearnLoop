# 批7 截图+交互：登录页 tab 切换/表单、悬浮窗渲染（非 Electron 提示态）、note-picker、capture
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:6001"
OUT = r"e:\LLM\LectureLearnLoop\server\logs\ui_b7_shot.txt"
SHOT_DIR = r"e:\LLM\LectureLearnLoop\design\walkthrough"

errs = []
lines = []

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1280, "height": 860})
    pg.on("pageerror", lambda e: errs.append("pageerror:" + str(e)))
    pg.on("console", lambda m: errs.append("console.error:" + m.text) if m.type == "error" else None)

    # 登录页：tab 切换 + 记住登录行显隐（登录/注册模式差异）
    pg.goto(BASE + "/login", wait_until="networkidle")
    pg.wait_for_timeout(1200)
    remember_visible_1 = pg.locator("#remember-row").is_visible()
    pg.click("#tab-register")
    confirm_visible = pg.locator("#field-confirm").is_visible()
    remember_visible_2 = pg.locator("#remember-row").is_visible()
    btn_text = pg.locator("#btn-submit").inner_text()
    pg.click("#tab-login")
    lines.append(f"login_tabs: remember_in_login={remember_visible_1} confirm_in_register={confirm_visible} remember_hidden_in_register={not remember_visible_2} reg_btn='{btn_text}'")
    pg.screenshot(path=SHOT_DIR + r"\b7_login.png")

    # 悬浮窗（浏览器无桥：应显示非桌面环境提示，页面正常渲染）
    pg.goto(BASE + "/overlay", wait_until="networkidle")
    pg.wait_for_timeout(1000)
    status = pg.locator("#status").inner_text()
    lines.append(f"overlay_status_text='{status[:40]}'")
    pg.screenshot(path=SHOT_DIR + r"\b7_overlay.png")

    # note-picker（无 token 应提示先登录；有 localStorage token 才拉列表）
    pg.goto(BASE + "/note-picker", wait_until="networkidle")
    pg.wait_for_timeout(1000)
    list_txt = pg.locator("#list").inner_text()
    lines.append(f"note_picker_no_token_hint={'未登录' in list_txt}")
    pg.screenshot(path=SHOT_DIR + r"\b7_note_picker.png")

    # capture（无桥背景图为空，仅验证提示条与页面存活）
    pg.goto(BASE + "/capture", wait_until="domcontentloaded")
    pg.wait_for_timeout(800)
    hint = pg.locator("#hint").inner_text()
    lines.append(f"capture_hint='{hint[:30]}'")
    pg.screenshot(path=SHOT_DIR + r"\b7_capture.png")

    lines.append("JS_ERRORS: " + (str(errs[:6]) if errs else "NONE"))
    b.close()

open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("done")
