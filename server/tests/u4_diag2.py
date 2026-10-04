# 诊断2：DOM 内联脚本 observer 声明形态（新/旧模板）+ 错误出现时机
from playwright.sync_api import sync_playwright

TOKEN = open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", encoding="utf-8").read().strip()
out = []
JS = """() => {
  const res = {scripts:0, constObs:[], varObs:[], mount:0};
  document.querySelectorAll('script:not([src])').forEach((s,i)=>{
    res.scripts++;
    const t = s.textContent || '';
    if (/const\\s+observer/.test(t)) res.constObs.push(i);
    if (/var\\s+observer/.test(t)) res.varObs.push(i);
    if (/window\\.importFiles/.test(t)) res.mount++;
  });
  return res;
}"""

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page()
    pg.on("pageerror", lambda e: out.append("PE: " + str(e)[:160]))
    pg.goto("http://127.0.0.1:6001/login", wait_until="domcontentloaded")
    pg.evaluate("t => localStorage.setItem('ll_token', t)", TOKEN)
    pg.goto("http://127.0.0.1:6001/", wait_until="networkidle")
    pg.wait_for_timeout(800)
    pg.evaluate("handleMenuClick('online_course_notes')")
    pg.wait_for_timeout(4000)
    out.append("AFTER-FIRST: " + str(pg.evaluate(JS)))
    pg.evaluate("handleMenuClick('dashboard')")
    pg.wait_for_timeout(2000)
    out.append("MID-DASH: " + str(pg.evaluate(JS)))
    pg.evaluate("handleMenuClick('online_course_notes')")
    pg.wait_for_timeout(5000)
    out.append("AFTER-SECOND: " + str(pg.evaluate(JS)))
    b.close()

open(r"e:\LLM\LectureLearnLoop\server\logs\u4_diag2.txt", "w", encoding="utf-8").write("\n".join(out) + "\n")
print("done")
