# 诊断：SPA 二次进入学页时 replaceChild 抛 observer 重复声明的具体脚本块
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:6001"
OUT = r"e:\LLM\LectureLearnLoop\server\logs\u4_diag_observer.txt"
TOKEN = open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", encoding="utf-8").read().strip()

lines = []
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page()
    pg.on("pageerror", lambda e: lines.append("pageerror: " + str(e)[:200]))
    pg.goto(BASE + "/login", wait_until="domcontentloaded")
    pg.evaluate("t => localStorage.setItem('ll_token', t)", TOKEN)
    pg.goto(BASE + "/", wait_until="networkidle")
    pg.wait_for_timeout(1000)
    pg.evaluate("handleMenuClick('online_course_notes')")
    pg.wait_for_timeout(4000)

    # patch replaceChild 捕获错误脚本
    pg.evaluate("""() => {
      window.__scriptErr = [];
      const orig = Node.prototype.replaceChild;
      Node.prototype.replaceChild = function(n, o) {
        try { return orig.call(this, n, o); }
        catch (e) {
          window.__scriptErr.push('MSG=' + String(e && e.message).slice(0,150) + ' || TEXT=' + String(n.text || '').slice(0, 300).replace(/\\n/g, ' '));
          throw e;
        }
      };
      return 'patched';
    }""")

    # 二次进入：先切走再切回
    pg.evaluate("handleMenuClick('dashboard')")
    pg.wait_for_timeout(2000)
    pg.evaluate("handleMenuClick('online_course_notes')")
    pg.wait_for_timeout(5000)

    errs = pg.evaluate("window.__scriptErr || []")
    for e in errs:
        lines.append("SCRIPT_ERR_CAUGHT: " + str(e))
    if not errs:
        lines.append("NO replaceChild errors captured on 2nd entry")
    b.close()

open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("done")
