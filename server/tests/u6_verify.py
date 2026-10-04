# u6 验证：预览区右键菜单 / 开始练习链路（无 alert、走 handlePractice 新版）/ 重命名 modal 全链路
import json
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:6001"
OUT = r"e:\LLM\LectureLearnLoop\server\logs\u6_verify.txt"
TOKEN = open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", encoding="utf-8").read().strip()

lines = []
errs = []
dialogs = []

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.on("pageerror", lambda e: errs.append("pageerror: " + str(e)[:300]))
    pg.on("dialog", lambda d: (dialogs.append(d.type + ":" + d.message[:80]), d.dismiss()))
    pg.goto(BASE + "/login", wait_until="domcontentloaded")
    pg.evaluate("t => localStorage.setItem('ll_token', t)", TOKEN)
    pg.goto(BASE + "/", wait_until="networkidle")
    pg.wait_for_timeout(800)

    # 0) 模板特征（确认新代码已加载）
    tpl = pg.evaluate("""async () => {
      const r = await fetch('/fragments/online_course_notes', {headers:{'Authorization':'Bearer '+localStorage.getItem('ll_token')}});
      const j = await r.json();
      const h = j.data || '';
      return { modal: h.includes('llPromptModal'), noAlertStub: !h.includes("练习功能已触发") };
    }""")
    lines.append("TPL_FEATURES -> " + json.dumps(tpl))

    # 1) 导入探针笔记并进入学页
    imp = pg.evaluate("""async () => {
      const tk = localStorage.getItem('ll_token');
      const md = new Blob(['# u6 探针笔记\\n\\n排序算法的核心是比较和交换。快速排序使用分治策略。\\n\\n第二段：时间复杂度平均 O(n log n)，最坏 O(n^2)。'], {type: 'text/markdown'});
      const fd = new FormData();
      fd.append('file', md, 'u6_probe.md');
      fd.append('folder_path', 'vault');
      const r1 = await fetch('/api/vault/import', {method:'POST', headers:{'Authorization':'Bearer '+tk}, body: fd});
      const j1 = await r1.json();
      const d1 = j1.data || j1;
      return d1.success ? 'OK' : 'FAIL ' + JSON.stringify(d1);
    }""")
    lines.append("PROBE_IMPORT -> " + str(imp))
    pg.evaluate("handleMenuClick('online_course_notes')")
    # P030：外部脚本链串行下载，冷启动尾块就绪可超固定 sleep；轮询主块+尾块特征函数（最多 90s）
    for _ in range(90):
        ready = pg.evaluate("() => (typeof selectFile === 'function') && (typeof window.llRunOnMenuText === 'function')")
        if ready:
            break
        pg.wait_for_timeout(1000)
    lines.append("SCRIPTS_READY -> " + str(ready) + " (after poll)")
    pg.wait_for_timeout(1000)

    # 2) 打开探针笔记（selectFile 挂桥）
    opened = pg.evaluate("""() => {
      try { selectFile('u6_probe.md'); return 'CALLED'; } catch (e) { return 'ERR ' + e; }
    }""")
    # 预览区渲染含高亮/mermaid 异步链，轮询正文非空（最多 30s）
    pv_len = 0
    for _ in range(30):
        pg.wait_for_timeout(1000)
        pv_len = pg.evaluate("() => { const el = document.getElementById('preview-content'); return el ? (el.textContent||'').trim().length : -1; }")
        if pv_len > 50:
            break
    lines.append("SELECT_FILE -> " + str(opened))
    pv = pg.evaluate("""() => {
      const el = document.getElementById('preview-content');
      return el ? ('exists text_len=' + (el.textContent||'').trim().length) : 'NO preview-content';
    }""")
    lines.append("PREVIEW -> " + str(pv))
    # 3) 预览区选中文本 + 右键 → 统一菜单应弹出（handleTextContextMenu 绑定生效）
    menu_shown = pg.evaluate("""() => {
      const el = document.getElementById('preview-content');
      if (!el) return 'NO-PREVIEW';
      // 在预览区找一个含文字的文本节点并建立选区
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      let tn = null;
      while (walker.nextNode()) { const n = walker.currentNode; if ((n.textContent||'').includes('排序')) { tn = n; break; } }
      if (!tn) return 'NO-TEXTNODE';
      const sel = window.getSelection();
      const range = document.createRange();
      range.setStart(tn, 0); range.setEnd(tn, Math.min(6, tn.length));
      sel.removeAllRanges(); sel.addRange(range);
      const ev = new MouseEvent('contextmenu', {bubbles:true, cancelable:true, clientX:400, clientY:300, pageX:400, pageY:300, button:2});
      tn.parentElement.dispatchEvent(ev);
      const m = document.getElementById('file-context-menu');
      return JSON.stringify({ menu_visible: m ? !m.classList.contains('hidden') : false,
                              snapshot: (window.llMenuText||'').slice(0,12) });
    }""")
    lines.append("PREVIEW_CTXMENU -> " + str(menu_shown))

    # 4) 点击"开始练习"：先桩住 LLM 出题函数避免真实调用，验证到面板/消息链路为止
    pre = pg.evaluate("""() => {
      window.__hp_probe = [];
      const origOpen = window.openAIChatWindow;
      window.openAIChatWindow = function(){ window.__hp_probe.push('open'); if (origOpen) try{origOpen()}catch(e){} };
      const origMsg = window.addAIPracticeMessage;
      window.addAIPracticeMessage = function(c,t){ window.__hp_probe.push('msg:' + String(c).slice(0,20)); if (origMsg) try{origMsg(c,t)}catch(e){} };
      const origPanel = window.showAIPracticePanel;
      window.showAIPracticePanel = function(d){ window.__hp_probe.push('panel:' + (d && d.id ? 'has-id' : '?')); if (origPanel) try{origPanel(d)}catch(e){} };
      window.generatePracticeQuestionsForAI = function(){ window.__hp_probe.push('gen-stub'); };
      return typeof window.handlePractice;
    }""")
    lines.append("HANDLE_PRACTICE_TYPE -> " + str(pre))
    click_res = pg.evaluate("""() => {
      const item = document.querySelector('#file-context-menu .context-menu-item[data-action=practice]');
      if (!item) return 'NO-ITEM';
      item.click();
      return 'CLICKED';
    }""")
    pg.wait_for_timeout(1500)
    probe_out = pg.evaluate("() => JSON.stringify(window.__hp_probe || [])")
    lines.append("PRACTICE_CLICK -> " + str(click_res) + " PROBE=" + str(probe_out))

    # 5) 文件树右键 → 重命名 modal → 改名 → 断言树中出现新名 → 改回
    rename_res = pg.evaluate("""async () => {
      const nodes = document.querySelectorAll('#file-tree .jstree-anchor');
      let target = null;
      nodes.forEach(n => { if ((n.textContent||'').includes('u6_probe')) target = n; });
      if (!target) return 'NO-TREE-NODE';
      const ev = new MouseEvent('contextmenu', {bubbles:true, cancelable:true, clientX:200, clientY:400, pageX:200, pageY:400, button:2});
      target.dispatchEvent(ev);
      const item = document.querySelector('#file-context-menu .context-menu-item[data-action=rename]');
      if (!item) return 'NO-RENAME-ITEM';
      item.click();
      const modal = document.getElementById('ll-prompt-modal');
      if (!modal) return 'NO-MODAL';
      const inp = document.getElementById('ll-prompt-input');
      inp.value = 'u6_probe_renamed';
      document.getElementById('ll-prompt-ok').click();
      await new Promise(r => setTimeout(r, 2500));
      const nodes2 = document.querySelectorAll('#file-tree .jstree-anchor');
      let found = false; nodes2.forEach(n => { if ((n.textContent||'').includes('u6_probe_renamed')) found = true; });
      return found ? 'RENAMED-OK' : 'RENAME-NOT-REFLECTED';
    }""")
    lines.append("RENAME_FLOW -> " + str(rename_res))

    # 6) 改回原名 + 删除探针笔记（走真实 rename/delete 桥），清理残留
    cleanup = pg.evaluate("""async () => {
      const tk = localStorage.getItem('ll_token');
      const r = await fetch('/api/vault/rename', {method:'POST', headers:{'Authorization':'Bearer '+tk, 'Content-Type':'application/json'},
        body: JSON.stringify({old_path: 'u6_probe_renamed', new_name: 'u6_probe'})});
      const j = await r.json();
      const r2 = await fetch('/api/vault/delete', {method:'POST', headers:{'Authorization':'Bearer '+tk, 'Content-Type':'application/json'},
        body: JSON.stringify({path: 'u6_probe'})});
      const j2 = await r2.json();
      return 'rename_back=' + JSON.stringify(j.data !== undefined ? j.data : j) + ' delete=' + JSON.stringify(j2.data !== undefined ? j2.data : j2);
    }""")
    lines.append("CLEANUP -> " + str(cleanup))

    lines.append("DIALOGS: " + (str(dialogs[:6]) if dialogs else "NONE"))
    lines.append("PAGE_ERRORS: " + (str(errs[:10]) if errs else "NONE"))
    pg.screenshot(path=r"e:\LLM\LectureLearnLoop\server\logs\u6_verify.png")
    b.close()

open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("done")
