# 批5 验证：知识库页真实渲染 + 负数bug修复断言 + 建学科闭环（建后删，不污染数据）+ 批4 未评估徽章回归
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:6001"
TOKEN = open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", encoding="utf-8").read().strip()
OUT = r"e:\LLM\LectureLearnLoop\server\logs\ui_b5_verify.txt"

errs = []
lines = []
NEW_SUBJ = "批5测试学科"

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.on("pageerror", lambda e: errs.append("pageerror:" + str(e)))
    pg.on("console", lambda m: errs.append("console.error:" + m.text) if m.type == "error" else None)
    pg.goto(BASE + "/login", wait_until="domcontentloaded")
    pg.evaluate("t => localStorage.setItem('ll_token', t)", TOKEN)
    pg.goto(BASE + "/", wait_until="networkidle")
    pg.wait_for_timeout(2500)

    pg.evaluate("() => handleMenuClick('knowledge_base')")
    pg.wait_for_timeout(3000)

    # 1. 总览三卡（全 -1 数据下：平均掌握度必须显示 — 而非 -1%）
    s_subj = pg.locator("#kb-stat-subjects").inner_text()
    s_pts = pg.locator("#kb-stat-points").inner_text()
    s_mast = pg.locator("#kb-stat-mastery").inner_text()
    s_msub = pg.locator("#kb-stat-mastery-sub").inner_text()
    lines.append(f"stats: subjects='{s_subj}' points='{s_pts}' mastery='{s_mast}' sub='{s_msub}'")
    lines.append(f"neg_bug_fixed: mastery_has_no_negative={('-1' not in s_mast) and ('负' not in s_mast)}")

    # 2. 学科卡 + 点击筛选
    cards = pg.locator("#kb-subject-grid [data-subj]").count()
    lines.append(f"subject_cards={cards}")
    if cards:
        pg.locator("#kb-subject-grid [data-subj]").first.click()
        pg.wait_for_timeout(1500)
        title = pg.locator("#kb-list-title").inner_text()
        rows = pg.locator("#kb-point-list .cl-badge").count()
        unrated = pg.locator("#kb-point-list >> text=未评估").count()
        lines.append(f"after_card_click: title='{title}' badges={rows} unrated_badges={unrated}")
        ring = pg.evaluate("() => { const c=document.querySelector('#kb-subject-grid [data-subj]'); return c.className.includes('ring-1'); }")
        lines.append(f"selected_ring_applied={ring}")

    # 3. 建学科闭环（POST→卡片出现→DELETE 清理）
    pg.fill("#kb-new-subject", NEW_SUBJ)
    pg.click("form button[type=submit]")
    pg.wait_for_timeout(2500)
    after = pg.locator(f"#kb-subject-grid [data-subj=\"{NEW_SUBJ}\"]").count()
    lines.append(f"add_subject: new_card_present={after==1}")
    import requests
    H = {"Authorization": "Bearer " + TOKEN}
    d = requests.delete(BASE + "/api/subjects/" + requests.utils.quote(NEW_SUBJ), headers=H, timeout=15).json()
    lines.append(f"cleanup_delete: {d.get('success')}")

    pg.screenshot(path=r"e:\LLM\LectureLearnLoop\design\walkthrough\b5_knowledge_base.png", full_page=True)

    # 4. 批4 回归：practice_knowledge 未评估徽章（不再显示 掌握 0%）
    pg.evaluate("() => handleMenuClick('practice_knowledge')")
    pg.wait_for_timeout(2500)
    zero = pg.locator("[data-pm-page='practice_knowledge'] >> text=掌握 0%").count()
    unr = pg.locator("[data-pm-page='practice_knowledge'] >> text=未评估").count()
    lines.append(f"b4_regression: badge_0pct_count={zero} unrated_count={unr}")
    pg.screenshot(path=r"e:\LLM\LectureLearnLoop\design\walkthrough\b5_practice_knowledge.png")

    lines.append("JS_ERRORS: " + (str(errs[:6]) if errs else "NONE"))
    b.close()

open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("done")
