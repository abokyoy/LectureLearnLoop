# u4 验证：导入功能移植后 全局挂载 / 按钮存在 / MD 导入端到端 / 新建文件夹内联改名
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:6001"
OUT = r"e:\LLM\LectureLearnLoop\server\logs\u4_verify.txt"
TOKEN = open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", encoding="utf-8").read().strip()

lines = []
errs = []

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.on("pageerror", lambda e: errs.append("pageerror: " + str(e)[:300]))
    pg.goto(BASE + "/login", wait_until="domcontentloaded")
    pg.evaluate("t => localStorage.setItem('ll_token', t)", TOKEN)
    pg.goto(BASE + "/", wait_until="networkidle")
    pg.wait_for_timeout(1000)
    pg.evaluate("handleMenuClick('online_course_notes')")
    pg.wait_for_timeout(4000)

    # 1) 挂载块 + 按钮存在
    probe = pg.evaluate("""() => {
      const names = ['addDebugLog','createNewNoteInRoot','createNewFolderInRoot','selectFile',
                     'retryQuestionGeneration','retryEvaluation','importFiles','closeImportBar'];
      const out = {};
      names.forEach(n => out[n] = typeof window[n]);
      out['import_button'] = !!document.querySelector('button[onclick="importFiles()"]');
      return out;
    }""")
    for k, v in probe.items():
        lines.append(f"MOUNT {k} = {v}")

    # 2) 导入下拉菜单弹出
    menu = pg.evaluate("""() => {
      importFiles();
      const m = document.getElementById('imp-menu');
      const r = m ? m.textContent : 'no-menu';
      if (m) m.remove();
      return r;
    }""")
    lines.append("IMPORT_MENU -> " + str(menu).strip())

    # 3) MD 导入端到端（页面内 fetch，走真实 multipart + 轮询）
    e2e = pg.evaluate("""async () => {
      const tk = localStorage.getItem('ll_token');
      const md = new Blob(['# u4 导入验证\\n\\n内容段落 probe'], {type: 'text/markdown'});
      const fd = new FormData();
      fd.append('file', md, 'u4_import_probe.md');
      fd.append('folder_path', 'vault');
      const r1 = await fetch('/api/vault/import', {method:'POST', headers:{'Authorization':'Bearer '+tk}, body: fd});
      if (!r1.ok) return 'HTTP ' + r1.status;
      const j1 = await r1.json();
      const d1 = j1.data || j1;
      if (!d1.success) return 'IMPORT-FAIL: ' + JSON.stringify(d1);
      const tid = d1.task_id;
      for (let i = 0; i < 20; i++) {
        await new Promise(res => setTimeout(res, 500));
        const r2 = await fetch('/api/vault/import/' + tid, {headers:{'Authorization':'Bearer '+tk}});
        const j2 = await r2.json();
        const d2 = j2.data || j2;
        if (d2.status === 'done') return 'DONE name=' + d2.result_name;
        if (d2.status === 'failed') return 'FAILED: ' + d2.error;
      }
      return 'TIMEOUT pending';
    }""")
    lines.append("IMPORT_MD_E2E -> " + str(e2e))

    # 4) 文件树刷新后出现导入产物（重新进入学页触发树加载）
    pg.evaluate("handleMenuClick('online_course_notes')")
    pg.wait_for_timeout(3000)
    tree_hit = pg.evaluate("""() => {
      const nodes = document.querySelectorAll('#file-tree .jstree-node');
      let hit = false;
      nodes.forEach(n => { if ((n.textContent||'').includes('u4_import_probe')) hit = true; });
      return hit;
    }""")
    lines.append("TREE_HAS_IMPORTED_FILE = " + str(tree_hit))

    # 5) 新建文件夹 → jsTree 内联改名输入框（u5 顺带验证）
    pg.evaluate("createNewFolderInRoot()")
    pg.wait_for_timeout(1200)
    inline = pg.evaluate("""() => {
      const inp = document.querySelector('#file-tree .jstree-rename-input, #file-tree input.jstree-rename-input');
      return inp ? 'RENAME-INPUT-FOUND value=' + inp.value : 'NO-INLINE-INPUT';
    }""")
    lines.append("CREATE_FOLDER_INLINE -> " + str(inline))
    # 按 ESC 取消内联改名，避免留下空文件夹
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(500)

    lines.append("PAGE_ERRORS: " + (str(errs[:10]) if errs else "NONE"))
    pg.screenshot(path=r"e:\LLM\LectureLearnLoop\server\logs\u4_verify.png")
    b.close()

open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("done")
