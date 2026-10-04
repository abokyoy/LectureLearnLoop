# 批4 练/记 4 页端到端验证：真实数据渲染 + 交互点击 + pageerror 监听 + 截图
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:6001"
TOKEN = open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", encoding="utf-8").read().strip()
OUT = r"e:\LLM\LectureLearnLoop\server\logs\ui_b4_verify.txt"
SHOT = r"e:\LLM\LectureLearnLoop\design\walkthrough\b4_{page}.png"

errs = []
lines = []

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.on("pageerror", lambda e: errs.append("pageerror:" + str(e)))
    pg.on("console", lambda m: errs.append("console.error:" + m.text) if m.type == "error" else None)
    pg.goto(BASE + "/login", wait_until="domcontentloaded")
    pg.evaluate("t => localStorage.setItem('ll_token', t)", TOKEN)
    pg.goto(BASE + "/", wait_until="networkidle")
    pg.wait_for_timeout(2500)

    def go(cid):
        pg.evaluate("cid => handleMenuClick(cid)", cid)
        pg.wait_for_timeout(2500)
        pg.screenshot(path=SHOT.format(page=cid), full_page=False)

    def q(expr):
        return pg.evaluate("e => { const n=document.querySelectorAll(e); return n.length; }", expr)

    # ---- 页1 practice_knowledge ----
    go("practice_knowledge")
    chips = q("[data-pm-page='practice_knowledge'] [data-subj]")
    cards = q("[data-pm-page='practice_knowledge'] [data-kp]")
    empty1 = q("[data-pm-page='practice_knowledge'] .cl-empty")
    lines.append(f"practice_knowledge: subjects_chips={chips} kp_cards={cards} empty={empty1}")
    if cards:
        pg.click("[data-pm-page='practice_knowledge'] .pm-kp-errors")
        pg.wait_for_timeout(1500)
        vis = pg.evaluate("() => { const d=document.querySelector('[data-kp-detail]'); return d ? !d.classList.contains('hidden') : null; }")
        lines.append(f"practice_knowledge: kp_errors_panel_open={vis}")
    # 假数据残留检查（旧硬编码特征串）
    fake = pg.evaluate("() => document.body.innerText.includes('智能推荐练习')")
    lines.append(f"practice_knowledge: fake_text_residue={fake}")

    # ---- 页2 practice_errors ----
    go("practice_errors")
    cards2 = q("[data-pm-page='practice_errors'] [data-eid]")
    empty2 = q("[data-pm-page='practice_errors'] .cl-empty")
    cnt2 = pg.evaluate("() => { const e=document.querySelector('[data-pm-page=\\'practice_errors\\'] [data-role=\\'count\\']'); return e?e.textContent:''; }")
    lines.append(f"practice_errors: rows={cards2} empty={empty2} count_badge='{cnt2}'")
    if cards2:
        pg.click("[data-pm-page='practice_errors'] .pm-q-toggle")
        pg.wait_for_timeout(400)
        vis = pg.evaluate("() => { const d=document.querySelector('[data-detail]'); return d ? !d.classList.contains('hidden') : null; }")
        lines.append(f"practice_errors: detail_expand={vis}")
        pg.fill("[data-pm-page='practice_errors'] [data-role='search']", "zzz不可能存在的关键词")
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(600)
        se = q('[data-pm-page="practice_errors"] .cl-empty')
        lines.append(f"practice_errors: after_search_empty_state={se}")
        pg.fill("[data-pm-page='practice_errors'] [data-role='search']", "")
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(600)

    # ---- 页3 memory_knowledge ----
    go("memory_knowledge")
    mastered = pg.evaluate("() => { const e=document.querySelector('[data-role=\\'mastered\\']'); return e?e.textContent:''; }")
    pct = pg.evaluate("() => { const e=document.querySelector('[data-role=\\'pct\\']'); return e?e.textContent:''; }")
    lines.append(f"memory_knowledge: mastered='{mastered}' overview_line='{pct}'")
    lines.append(f"memory_knowledge: fake_residue(156/92%)={'156' == mastered}")

    # ---- 页4 memory_errors（含真实「标记已复习」点击，仅测试账号数据）----
    go("memory_errors")
    stat = pg.evaluate("() => { const e=document.querySelector('[data-role=\\'stat\\']'); return e?e.innerText.replace(/\\n/g,' '):''; }")
    lines.append(f"memory_errors: stat='{stat}'")
    rows4 = q("[data-pm-page='memory_errors'] [data-eid]")
    btns = q("[data-pm-page='memory_errors'] .pm-review-btn")
    lines.append(f"memory_errors: rows={rows4} review_btns={btns}")
    if btns:
        pg.click("[data-pm-page='memory_errors'] .pm-q-toggle")
        pg.wait_for_timeout(300)
        pg.click("[data-pm-page='memory_errors'] .pm-review-btn")
        pg.wait_for_timeout(2000)
        stat_after = pg.evaluate("() => { const e=document.querySelector('[data-role=\\'stat\\']'); return e?e.innerText.replace(/\\n/g,' '):''; }")
        badge = pg.evaluate("() => { const b=document.querySelector('[data-pm-page=\\'memory_errors\\'] .cl-badge.text-cl-secondary'); return !!b; }")
        lines.append(f"memory_errors: after_review stat='{stat_after}' has_reviewed_badge={badge}")
        lines.append("memory_errors: NOTE 已真实标记 1 道测试错题 reviewed（仅 ui_walk_2026 测试账号）")

    lines.append("JS_ERRORS: " + (str(errs[:8]) if errs else "NONE"))
    b.close()

open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("done")
