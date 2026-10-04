# 探针：脑图片段脚本链错误定位
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:6001"
OUT = r"e:\LLM\LectureLearnLoop\server\logs\ui_b9c_probe.txt"
TOKEN = open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", encoding="utf-8").read().strip()

msgs = []
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page()
    pg.on("console", lambda m: msgs.append(f"[{m.type}] {m.text[:300]}"))
    pg.on("pageerror", lambda e: msgs.append("PAGEERROR:" + str(e)[:400]))
    pg.goto(BASE + "/login", wait_until="domcontentloaded")
    pg.evaluate("t => localStorage.setItem('ll_token', t)", TOKEN)
    pg.goto(BASE + "/", wait_until="networkidle")
    pg.wait_for_timeout(1000)
    pg.evaluate("handleMenuClick('practice_materials')")
    pg.wait_for_timeout(20000)  # 给 CDN 充分时间
    fn = pg.evaluate("""() => ({
        showDetail: typeof window.showKnowledgePointDetail,
        closeDetail: typeof window.closeKnowledgePointDetail,
        showToast: typeof window.showToast,
        layer: !!document.getElementById('knowledgePointDetailLayer'),
        readyState: document.readyState,
    })""")
    msgs.append("FN_TYPES: " + repr(fn))
    b.close()

open(OUT, "w", encoding="utf-8").write("\n".join(msgs) + "\n")
print("done")
