# 诊断3：打印含 observer 声明的脚本块身份与声明行上下文
from playwright.sync_api import sync_playwright

TOKEN = open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", encoding="utf-8").read().strip()
out = []
JS = """() => {
  const hits = [];
  document.querySelectorAll('script:not([src])').forEach((s,i)=>{
    const t = s.textContent || '';
    const m = t.match(/.{0,60}\\b(const|let|var)\\s+observer\\b.{0,80}/g);
    if (m) hits.push({i, head: t.slice(0,80).replace(/\\n/g,' '), decls: m.map(x=>x.replace(/\\n/g,' '))});
  });
  return hits;
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
    for h in pg.evaluate(JS):
        out.append(f"SCRIPT[{h['i']}] head={h['head']}")
        for d in h["decls"]:
            out.append("   DECL: " + d)
    b.close()

open(r"e:\LLM\LectureLearnLoop\server\logs\u4_diag3.txt", "w", encoding="utf-8").write("\n".join(out) + "\n")
print("done")
