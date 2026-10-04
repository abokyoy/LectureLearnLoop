# u6 补充：showAIPracticePanel 真实渲染可见性（不打桩，验证 base.html 面板在 SPA 上下文可用）
import json
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:6001"
OUT = r"e:\LLM\LectureLearnLoop\server\logs\u6_panel_probe.txt"
TOKEN = open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", encoding="utf-8").read().strip()

lines = []
errs = []
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.on("pageerror", lambda e: errs.append(str(e)[:200]))
    pg.goto(BASE + "/login", wait_until="domcontentloaded")
    pg.evaluate("t => localStorage.setItem('ll_token', t)", TOKEN)
    pg.goto(BASE + "/", wait_until="networkidle")
    pg.wait_for_timeout(800)
    pg.evaluate("handleMenuClick('online_course_notes')")
    # 脚本链含多个外部脚本串行下载，给足时间；并轮询尾块标志直到就绪或超时
    for _ in range(20):
        pg.wait_for_timeout(1000)
        if pg.evaluate("() => typeof window.handlePractice === 'function' && typeof window.llRunOnMenuText === 'function'"):
            break
    ready = pg.evaluate("""() => JSON.stringify({
      hp: typeof window.handlePractice, ll: typeof window.llRunOnMenuText,
      it: typeof window.initTextSelectionContextMenu, sf: typeof window.selectFile })""")
    lines.append("TAIL_BLOCK_READY -> " + str(ready))
    res = pg.evaluate("""() => {
      const out = {fns: {}, visible: []};
      ['openAIChatWindow','addAIPracticeMessage','showAIPracticePanel','handlePractice'].forEach(n => out.fns[n] = typeof window[n]);
      try {
        window.openAIChatWindow();
        window.showAIPracticePanel({id:'probe_p1', selectedText:'排序算法', questions:null, status:'generating'});
      } catch (e) { out.call_err = String(e); }
      // 扫描可见的面板类元素
      const ids = ['aiChatWindow','aiPracticePanel','practicePanel','aiChatMessages'];
      ids.forEach(i => { const el = document.getElementById(i);
        if (el) out.visible.push(i + ':' + (el.offsetParent !== null || el.getClientRects().length > 0 ? 'shown' : 'hidden')); });
      return JSON.stringify(out);
    }""")
    pg.wait_for_timeout(1200)
    lines.append("PANEL_PROBE -> " + str(res))
    lines.append("PAGE_ERRORS: " + (str(errs[:5]) if errs else "NONE"))
    pg.screenshot(path=r"e:\LLM\LectureLearnLoop\server\logs\u6_panel_probe.png")
    b.close()

open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("done")
