# u7 复现：AI练习助手窗口 最大化→开始新练习→"白页"现场取证
import json
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:6001"
OUT = r"e:\LLM\LectureLearnLoop\server\logs\u7_repro.txt"
TOKEN = open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", encoding="utf-8").read().strip()

lines = []
errs = []
cons = []
dialogs = []

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.on("pageerror", lambda e: errs.append("pageerror: " + str(e)[:300]))
    pg.on("console", lambda m: cons.append(m.type + ":" + m.text[:150]) if m.type in ("error", "warning") else None)
    pg.on("dialog", lambda d: (dialogs.append(d.type + ":" + d.message[:100]), d.dismiss()))
    pg.goto(BASE + "/login", wait_until="domcontentloaded")
    pg.evaluate("t => localStorage.setItem('ll_token', t)", TOKEN)
    pg.goto(BASE + "/", wait_until="networkidle")
    pg.wait_for_timeout(1500)

    # 1) 打开 AI 助手窗口
    r1 = pg.evaluate("""() => {
      if (typeof window.openAIChatWindow !== 'function') return 'NO-FN';
      window.openAIChatWindow();
      const w = document.getElementById('aiChatWindow');
      if (!w) return 'NO-DOM';
      return JSON.stringify({ shown: w.getClientRects().length > 0, rect: (()=>{const r=w.getBoundingClientRect();return [r.x|0,r.y|0,r.width|0,r.height|0];})() });
    }""")
    lines.append("STEP1_OPEN -> " + str(r1))
    pg.wait_for_timeout(800)

    # 2) 找窗口内按钮清单（含 maximize / 欢迎页元素）
    r2 = pg.evaluate("""() => {
      const w = document.getElementById('aiChatWindow');
      if (!w) return 'NO-WINDOW';
      const btns = [];
      w.querySelectorAll('button,[id]').forEach(el => {
        const id = el.id || '';
        if (id) btns.push(id + '/' + (el.offsetParent !== null ? 'vis' : 'hid'));
      });
      return JSON.stringify(btns.slice(0, 80));
    }""")
    lines.append("STEP2_IDS -> " + str(r2))

    # 3) 尝试点击"开始新练习"（欢迎页按钮，通常无需先最大化）
    r3 = pg.evaluate("""() => {
      const btn = document.getElementById('welcomeNewPracticeBtn');
      if (!btn) return 'NO-BTN';
      const vis = btn.offsetParent !== null;
      btn.click();
      return 'clicked vis=' + vis;
    }""")
    lines.append("STEP3_CLICK_WELCOME -> " + str(r3))
    pg.wait_for_timeout(1500)

    # 4) 点击后现场：窗口尺寸/内容区可见性/文字量
    r4 = pg.evaluate("""() => {
      const w = document.getElementById('aiChatWindow');
      const rects = (()=>{ const r=w.getBoundingClientRect(); return [r.x|0,r.y|0,r.width|0,r.height|0]; })();
      const probe = {};
      ['aiChatMessages','aiPracticeMessages','welcomePracticeScreen','questionDisplayArea'].forEach(i => {
        const el = document.getElementById(i);
        probe[i] = el ? ((el.offsetParent !== null || el.getClientRects().length > 0 ? 'shown' : 'hidden') + ' len=' + String(el.textContent||'').trim().length) : 'missing';
      });
      // 白页判定：整个可视区正文覆盖率
      const bodyText = String(document.body.innerText || '').trim().length;
      return JSON.stringify({ winRect: rects, probe: probe, bodyTextLen: bodyText });
    }""")
    lines.append("STEP4_STATE -> " + str(r4))
    pg.screenshot(path=r"e:\LLM\LectureLearnLoop\server\logs\u7_repro_after_welcome.png")

    # 5) 模拟"练习历史→开始练习"入口：新练习按钮 startPracticeBtn（工具栏）
    r5 = pg.evaluate("""() => {
      const btn = document.getElementById('startPracticeBtn');
      if (!btn) return 'NO-START-BTN';
      const vis = btn.offsetParent !== null;
      btn.click();
      return 'clicked vis=' + vis;
    }""")
    lines.append("STEP5_START_BTN -> " + str(r5))
    pg.wait_for_timeout(2500)
    r6 = pg.evaluate("""() => {
      const w = document.getElementById('aiChatWindow');
      const rects = w ? (()=>{ const r=w.getBoundingClientRect(); return [r.x|0,r.y|0,r.width|0,r.height|0]; })() : null;
      const qda = document.getElementById('questionDisplayArea');
      return JSON.stringify({ winRect: rects, qda: qda ? ((qda.offsetParent!==null?'shown':'hidden') + ' ' + String(qda.textContent||'').trim().slice(0,60)) : 'missing' });
    }""")
    lines.append("STEP6_AFTER_START -> " + str(r6))
    pg.screenshot(path=r"e:\LLM\LectureLearnLoop\server\logs\u7_repro_after_start.png")

    # 7) 全屏快照：是否存在遮挡整屏的空白层
    r7 = pg.evaluate("""() => {
      const els = document.elementsFromPoint(720, 450);
      return JSON.stringify(els.slice(0, 6).map(e => (e.tagName + '#' + (e.id||'') + '.' + String(e.className||'').split(' ')[0])));
    }""")
    lines.append("STEP7_CENTER_STACK -> " + str(r7))

    # 8) 取自定义 alert 弹窗文本（失败原因）+ 再等异步生成完成后的面板状态
    r8 = pg.evaluate("""() => {
      const box = document.querySelector('.ll-alert-box');
      const alertText = box ? String(box.innerText || '').trim().slice(0, 300) : 'NO-ALERT-BOX';
      const qda = document.getElementById('questionDisplayArea');
      return JSON.stringify({ alert: alertText, qda_now: String(qda ? qda.textContent : '').trim().slice(0, 120) });
    }""")
    lines.append("STEP8_ALERT -> " + str(r8))
    # LLM 出题预计 10-30s，轮询直到题目区不再是加载态（最多 60s）
    for _ in range(60):
        pg.wait_for_timeout(1000)
        done_flag = pg.evaluate("""() => {
          const qda = document.getElementById('questionDisplayArea');
          const t = String(qda ? qda.textContent : '');
          return t.includes('正在生成') || t.includes('题目将在这里显示') ? 'PENDING' : 'READY';
        }""")
        if done_flag == "READY":
            break
    r9 = pg.evaluate("""() => {
      const qda = document.getElementById('questionDisplayArea');
      const idd = document.getElementById('practiceIdDisplay');
      const box = document.querySelector('.ll-alert-box');
      return JSON.stringify({ qda_final: String(qda ? qda.textContent : '').trim().slice(0, 250),
                              pid: idd ? idd.textContent.trim() : '',
                              alert_if_any: box ? String(box.innerText).trim().slice(0, 200) : '' });
    }""")
    lines.append("STEP9_FINAL -> " + str(r9))
    pg.screenshot(path=r"e:\\LLM\\LectureLearnLoop\\server\\logs\\u7_repro_maximized.png")

    lines.append("DIALOGS: " + (str(dialogs[:8]) if dialogs else "NONE"))
    lines.append("PAGE_ERRORS: " + (str(errs[:10]) if errs else "NONE"))
    lines.append("CONSOLE: " + (str(cons[:15]) if cons else "NONE"))
    b.close()

open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("done")
