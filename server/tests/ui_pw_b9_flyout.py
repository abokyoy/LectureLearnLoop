# 批9：侧边栏二级 flyout 菜单验证
# hover「练」→ 三点子项出现 → 点「从错题练」切页成功；hover「记」→ 点「记错题」；窄栏高亮归组；JS 零错误
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:6001"
OUT = r"e:\LLM\LectureLearnLoop\server\logs\ui_b9_verify.txt"
SHOT = r"e:\LLM\LectureLearnLoop\design\walkthrough"
TOKEN = open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", encoding="utf-8").read().strip()

lines = []
errs = []

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.on("pageerror", lambda e: errs.append("pageerror:" + str(e)))
    pg.on("console", lambda m: errs.append("console.error:" + m.text) if m.type == "error" else None)
    pg.goto(BASE + "/login", wait_until="domcontentloaded")
    pg.evaluate("t => localStorage.setItem('ll_token', t)", TOKEN)
    pg.goto(BASE + "/", wait_until="networkidle")
    pg.wait_for_timeout(1200)

    # 默认工作台：flyout 隐藏
    fly_practice = pg.locator("div.group:has(a[data-cid='practice_materials']) > div").first
    lines.append(f"flyout_hidden_by_default: {not fly_practice.is_visible()}")

    # hover「练」→ flyout 出现，含三个子项
    pg.hover("a[data-cid='practice_materials']")
    pg.wait_for_timeout(300)
    visible = fly_practice.is_visible()
    items = fly_practice.locator("a").all_inner_texts()
    lines.append(f"practice_flyout_visible: {visible}")
    lines.append(f"practice_items_3: {len(items) == 3} {items}")
    pg.screenshot(path=SHOT + r"\b9_flyout_practice.png")

    # 点「从错题练」→ 内容区切换为错题练习页（data-pm-page=practice_errors），面板移开后不报错
    fly_practice.locator("a", has_text="从错题练").click()
    pg.wait_for_timeout(1500)
    landed = pg.locator("[data-pm-page='practice_errors']").count()
    active_cid = pg.evaluate("document.querySelector('.cl-nav-item.cl-active') ? document.querySelector('.cl-nav-item.cl-active').getAttribute('data-cid') : ''")
    lines.append(f"goto_practice_errors: {landed >= 1} active_nav={active_cid} (expect practice_materials)")

    # hover「记」→ 点「记错题」
    pg.hover("a[data-cid='memory_knowledge']")
    pg.wait_for_timeout(300)
    fly_mem = pg.locator("div.group:has(a[data-cid='memory_knowledge']) > div").first
    lines.append(f"memory_flyout_visible: {fly_mem.is_visible()} items={fly_mem.locator('a').all_inner_texts()}")
    fly_mem.locator("a", has_text="记错题").click()
    pg.wait_for_timeout(1500)
    landed2 = pg.locator("[data-pm-page='memory_errors']").count()
    active_cid2 = pg.evaluate("document.querySelector('.cl-nav-item.cl-active') ? document.querySelector('.cl-nav-item.cl-active').getAttribute('data-cid') : ''")
    lines.append(f"goto_memory_errors: {landed2 >= 1} active_nav={active_cid2} (expect memory_knowledge)")
    pg.screenshot(path=SHOT + r"\b9_memory_errors.png")

    # 从知识点练
    pg.hover("a[data-cid='practice_materials']")
    pg.wait_for_timeout(300)
    fly_practice.locator("a", has_text="从知识点练").click()
    pg.wait_for_timeout(1500)
    lines.append(f"goto_practice_knowledge: {pg.locator('[data-pm-page=practice_knowledge]').count() >= 1}")

    lines.append("JS_ERRORS: " + (str(errs[:6]) if errs else "NONE"))
    b.close()

open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("done")
