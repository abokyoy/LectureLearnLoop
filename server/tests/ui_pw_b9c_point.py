# 批9c：知识点直达验证
# 【已废弃 u10】旧行为「去练习→落脑图页自动弹详情层」已被 u10 独立直达页取代（禁止先跳脑图），
# 本脚本按旧契约断言，重跑必失败；新契约验证请用 tests/u10_verify.py。
# 练知识点页「去练习」→ 脑图页自动弹出该知识点详情练习层（非脑图首页）；记知识点页行级「巩固」同理；旗标消费不残留
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:6001"
OUT = r"e:\LLM\LectureLearnLoop\server\logs\ui_b9c_verify.txt"
SHOT = r"e:\LLM\LectureLearnLoop\design\walkthrough"
TOKEN = open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", encoding="utf-8").read().strip()

lines = []
errs = []


def get_practice_frame(pg, timeout_ms=40000):
    """脑图页是 iframe 片段（practice_materials_frame.html → /practice），轮询拿 frame"""
    import time
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        for f in pg.frames:
            if "/practice" in (f.url or ""):
                try:
                    if f.evaluate("typeof window.showKnowledgePointDetail === 'function'"):
                        return f
                except Exception:
                    pass
        pg.wait_for_timeout(500)
    return None


def open_layer_detail(frame):
    """详情层可见 + 标题 + 三动作按钮齐备（均在 iframe 内）"""
    vis = frame.evaluate("!document.getElementById('knowledgePointDetailLayer').classList.contains('hidden')")
    title = frame.evaluate("document.getElementById('detailTitle').textContent") if vis else ""
    btns = frame.evaluate("document.querySelectorAll('#masteryAssessmentBtn,#noteBasedPracticeBtn,#analogyPracticeBtn').length") if vis else 0
    return 1 if vis else 0, title, btns


with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.on("pageerror", lambda e: errs.append("pageerror:" + str(e)))
    pg.goto(BASE + "/login", wait_until="domcontentloaded")
    pg.evaluate("t => localStorage.setItem('ll_token', t)", TOKEN)
    pg.goto(BASE + "/", wait_until="networkidle")
    pg.wait_for_timeout(1000)

    # ---- 链路1：练 · 从知识点练 → 去练习 ----
    pg.evaluate("handleMenuClick('practice_knowledge')")
    pg.wait_for_timeout(1500)
    chips = pg.locator("[data-pm-page='practice_knowledge'] [data-role='subjects'] button")
    lines.append(f"subject_chips: {chips.count()}")
    cards = pg.locator("[data-pm-page='practice_knowledge'] [data-gopoint]")
    if cards.count() == 0 and chips.count():
        chips.first.click()
        pg.wait_for_timeout(1500)
        cards = pg.locator("[data-pm-page='practice_knowledge'] [data-gopoint]")
    lines.append(f"kp_cards: {cards.count()}")
    if cards.count():
        cards.first.click()
        frame = get_practice_frame(pg)
        pg.wait_for_timeout(1200)  # 就绪后再给消费延迟+详情拉取留时间
        lines.append(f"practice_frame_ready: {frame is not None}")
        if frame:
            vis, title, btns = open_layer_detail(frame)
            lines.append(f"practice_goes_to_detail_layer: {vis == 1} title='{title}' action_btns={btns}")
        pending = pg.evaluate("localStorage.getItem('pm_pending_point')")
        lines.append(f"pending_consumed: {pending is None}")
        pg.screenshot(path=SHOT + r"\b9c_point_detail.png")
        if frame:
            frame.evaluate("closeKnowledgePointDetail()")
            pg.wait_for_timeout(300)
            closed = frame.evaluate("document.getElementById('knowledgePointDetailLayer').classList.contains('hidden')")
            lines.append(f"layer_closable: {closed}")

    # ---- 链路2：记 · 知识点行级「巩固」 ----
    pg.evaluate("handleMenuClick('memory_knowledge')")
    pg.wait_for_timeout(1500)
    rows = pg.locator("[data-pm-page='memory_knowledge'] [data-gopoint]")
    if rows.count() == 0:
        mc = pg.locator("[data-pm-page='memory_knowledge'] [data-role='subjects'] button")
        if mc.count():
            mc.first.click()
            pg.wait_for_timeout(1500)
        rows = pg.locator("[data-pm-page='memory_knowledge'] [data-gopoint]")
    lines.append(f"memory_rows_with_btn: {rows.count()}")
    if rows.count():
        rows.first.click()
        frame2 = get_practice_frame(pg)
        pg.wait_for_timeout(1200)
        lines.append(f"memory_frame_ready: {frame2 is not None}")
        if frame2:
            vis, title, btns = open_layer_detail(frame2)
            lines.append(f"memory_goes_to_detail_layer: {vis == 1} title='{title}' btns={btns}")

    lines.append("JS_ERRORS: " + (str(errs[:5]) if errs else "NONE"))
    b.close()

open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("done")
