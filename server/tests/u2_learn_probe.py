# u2 学页摸底探针：全局函数挂载状态 / 右键菜单绑定 / 练习链路 / 控制台错误
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:6001"
OUT = r"e:\LLM\LectureLearnLoop\server\logs\u2_learn_probe.txt"
TOKEN = open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", encoding="utf-8").read().strip()

lines = []
errs = []
conso = []

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.on("pageerror", lambda e: errs.append("pageerror: " + str(e)[:300]))
    pg.on("console", lambda m: conso.append(m.type + ": " + m.text[:200]) if m.type in ("error", "warning") else None)
    pg.goto(BASE + "/login", wait_until="domcontentloaded")
    pg.evaluate("t => localStorage.setItem('ll_token', t)", TOKEN)
    pg.goto(BASE + "/", wait_until="networkidle")
    pg.wait_for_timeout(1000)

    # 进入「学」页
    pg.evaluate("handleMenuClick('online_course_notes')")
    pg.wait_for_timeout(4000)

    # 1) 全局挂载状态
    probe = pg.evaluate("""() => {
      const names = ['createNewNoteInRoot','createNewFolderInRoot','addDebugLog','debugLog','selectFile',
                     'importFiles','closeImportBar','llRunOnMenuText','llShowUnifiedMenu','llHideAllMenus',
                     'handlePractice','handleDeepLearning','generatePracticeQuestionsForAI',
                     'retryQuestionGeneration','retryEvaluation','switchToPreview','handleSaveButton',
                     'showAIPracticePanel','addAIPracticeMessage','openAIChatWindow'];
      const out = {};
      names.forEach(n => { out[n] = (typeof window[n]) + (n==='handlePractice' && window[n] ? ' | body:' + window[n].toString().slice(0,80) : ''); });
      out['#file-context-menu'] = !!document.getElementById('file-context-menu');
      out['#preview-content'] = !!document.getElementById('preview-content');
      out['#file-tree'] = !!document.getElementById('file-tree');
      return out;
    }""")
    for k, v in probe.items():
        lines.append(f"GLOBAL {k} = {v}")

    # 2) 预览区右键是否弹菜单
    r = pg.evaluate("""() => {
      const pc = document.getElementById('preview-content');
      if (!pc) return 'no-preview';
      const ev = new MouseEvent('contextmenu', {bubbles:true, cancelable:true, clientX:400, clientY:400, pageX:400, pageY:400});
      pc.dispatchEvent(ev);
      const m = document.getElementById('file-context-menu');
      return m ? ('menu-hidden=' + m.classList.contains('hidden') + ' pos=' + m.style.left + ',' + m.style.top) : 'no-menu';
    }""")
    lines.append("PREVIEW_CONTEXTMENU -> " + str(r))
    pg.wait_for_timeout(300)

    # 3) 新建文件夹/笔记按钮点击（无反应验证）
    click_err = pg.evaluate("""() => {
      try { if (typeof createNewFolderInRoot === 'function') { createNewFolderInRoot(); return 'invoked'; } return 'not-a-function'; }
      catch (e) { return 'ERR: ' + e.message; }
    }""")
    lines.append("createNewFolderInRoot -> " + str(click_err))
    pg.wait_for_timeout(800)
    dlg = pg.evaluate("""() => {
      const els = document.querySelectorAll('input');
      let hit = null;
      els.forEach(i => { if ((i.placeholder||'').includes('名称') || i.className.includes('rename')) hit = i.outerHTML.slice(0,120); });
      return hit;
    }""")
    lines.append("rename_input_after_click: " + str(dlg))

    # 4) 练习链路：直接调 llRunOnMenuText 看是否断（选区空→走全文回退）
    perr = pg.evaluate("""async () => {
      try {
        if (typeof window.llRunOnMenuText !== 'function') return 'llRunOnMenuText missing';
        window.llRunOnMenuText('practice', window.currentFilePath, 'file', 'probe');
        return 'invoked (watch subsequent pageerror)';
      } catch (e) { return 'SYNC-ERR: ' + e.message; }
    }""")
    lines.append("llRunOnMenuText('practice') -> " + str(perr))
    pg.wait_for_timeout(2500)

    # 5) 文件树是否存在节点 + 树节点右键
    tree_nodes = pg.evaluate("document.querySelectorAll('#file-tree .jstree-node').length")
    lines.append("tree_nodes: " + str(tree_nodes))

    lines.append("PAGE_ERRORS: " + (str(errs[:12]) if errs else "NONE"))
    lines.append("CONSOLE_ERR: " + (str(conso[:20]) if conso else "NONE"))
    pg.screenshot(path=r"e:\LLM\LectureLearnLoop\server\logs\u2_learn_probe.png")
    b.close()

open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("done")
