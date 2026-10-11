// MD 预览空白 bug 断言脚本（CDP 9222）
// 复现路径：点 MD 文件(基线OK) → 点编辑 → 再点 MD 文件 → 断言预览区可见且有内容
// 用法：node md_preview_assert.js [baseUrl]
const http = require('http');
const WebSocket = require('ws');

const BASE = process.argv[2] || 'http://127.0.0.1:6001';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function getJSON(url) {
  return new Promise((res, rej) => http.get(url, (r) => {
    let d = ''; r.on('data', (c) => (d += c)); r.on('end', () => { try { res(JSON.parse(d)); } catch (e) { rej(e); } });
  }).on('error', rej));
}

(async () => {
  const targets = await getJSON('http://127.0.0.1:9222/json');
  const page = targets.find((t) => t.type === 'page' && /6001/.test(t.url) && !/note-picker|overlay|capture/.test(t.url));
  if (!page) throw new Error('no page target (先启动 dev electron)');
  const ws = new WebSocket(page.webSocketDebuggerUrl, { perMessageDeflate: false });
  let id = 0;
  const send = (method, params) => new Promise((res, rej) => {
    const mid = ++id;
    const to = setTimeout(() => rej(new Error(method + ' timeout')), 20000);
    const onMsg = (raw) => {
      const m = JSON.parse(raw);
      if (m.id === mid) { ws.off('message', onMsg); clearTimeout(to); m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result); }
    };
    ws.on('message', onMsg);
    ws.send(JSON.stringify({ id: mid, method, params: params || {} }));
  });
  await new Promise((res, rej) => { ws.on('open', res); ws.on('error', rej); });
  // 自动处理挂起的原生弹框（alert/confirm 在 Electron 里不显示但冻结 JS）
  ws.on('message', (raw) => {
    const m = JSON.parse(raw);
    if (m.method === 'Page.javascriptDialogOpening') {
      console.log('DIALOG:', m.params.type, '-', String(m.params.message).slice(0, 150));
      ws.send(JSON.stringify({ id: 99999, method: 'Page.handleJavaScriptDialog', params: { accept: true } }));
    }
  });
  await send('Page.enable');
  const evalJs = async (expression) => {
    const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error('page exception: ' + JSON.stringify(r.exceptionDetails.exception && r.exceptionDetails.exception.description || r.exceptionDetails.text));
    return r.result.value;
  };

  // 1) 从首页走 SPA 路由进入网课笔记页（直连 URL 会被壳层重写，已知坑）
  await evalJs(`location.href = '${BASE}/'; 'nav'`);
  await sleep(5000);
  // 弹框打桩：Electron 里 alert/confirm 不显示但冻结 JS，会假死整个断言流程
  await evalJs(`window.alert = () => true; window.confirm = () => true; 'stubbed'`);
  await evalJs(`(async () => { const sleep = ms => new Promise(r => setTimeout(r, ms));
    for (let i = 0; i < 20 && !window.handleMenuClick; i++) await sleep(500);
    if (window.handleMenuClick) handleMenuClick('online_course_notes');
    return 'routed:' + !!window.handleMenuClick + ' at:' + location.pathname; })()`);
  await sleep(5000);

  // 2) 文件树是 jsTree 渲染（不是自绘 .file-item），用 jstree API 展开并找 MD 节点
  const helper = `window.__findMdNode = function () {
    const inst = $('#file-tree').jstree(true);
    if (!inst) return null;
    let found = null;
    (function walk(nodes) { (nodes || []).forEach(n => { if (!found && n.data && /\.md$/i.test(n.data.path || '')) found = n; if (!found && Array.isArray(n.children) && n.children.length) walk(n.children.map(c => typeof c === 'string' ? inst.get_node(c) : c)); }); })(inst.get_json('#', { deep: true }));
    return found;
  };
`;
  await evalJs(`(async () => {
    const sleep = ms => new Promise(r => setTimeout(r, ms));
    ${helper}
    for (let i = 0; i < 20; i++) {
      const inst = $('#file-tree') && $('#file-tree').jstree(true);
      if (inst && __findMdNode()) break;
      if (inst) inst.open_all();
      await sleep(700);
    }
    const inst = $('#file-tree').jstree(true);
    if (inst) inst.open_all();
    await sleep(800);
    const n = __findMdNode();
    return { hasInst: !!inst, md: n ? { id: n.id, path: n.data.path.slice(-60) } : null };
  })()`);
  const expanded = await evalJs(`(() => { const n = __findMdNode(); return { mdCount: n ? 1 : 0, first: n ? n.text.slice(0, 40) : null }; })()`);
  console.log('STEP0 展开文件树:', JSON.stringify(expanded));

  // 3) 基线：直接点击第一个 MD 文件（select_node 模拟真实点击）→ 预览区应可见且有内容
  const baseline = await evalJs(`(async () => {
    const sleep = ms => new Promise(r => setTimeout(r, ms));
    const n = __findMdNode();
    if (!n) return { err: 'no md file in tree' };
    $('#file-tree').jstree('select_node', n);
    await sleep(2500);
    const pc = document.getElementById('preview-content');
    return { file: n.text.slice(0, 40), display: getComputedStyle(pc).display, len: pc.innerHTML.length };
  })()`);
  console.log('STEP1 基线(直接点MD):', JSON.stringify(baseline));

  // 4) 点"编辑" → 再点 MD 文件 → 再点"预览" → 断言预览区可见有内容，且无行内 display 污染
  const after = await evalJs(`(async () => {
    const sleep = ms => new Promise(r => setTimeout(r, ms));
    document.getElementById('edit-btn').click();
    await sleep(1500);
    const n = __findMdNode();
    $('#file-tree').jstree('unselect_node', n);
    $('#file-tree').jstree('select_node', n);
    await sleep(2500);
    const pc = document.getElementById('preview-content');
    const mid = { inlineDisplay: pc.style.display || '', hasHiddenClass: pc.classList.contains('hidden') };
    document.getElementById('preview-btn').click();
    await sleep(2500);
    const cs = getComputedStyle(pc);
    return { mid, display: cs.display, inlineDisplay: pc.style.display || '', hasHiddenClass: pc.classList.contains('hidden'), contentLen: pc.innerHTML.length, windowFlag: typeof window.isEditMode };
  })()`);
  console.log('STEP2 编辑→点MD→点预览:', JSON.stringify(after));

  // 判定：行内污染必须不存在；预览按钮后必须可见且内容非空
  const pass = after.inlineDisplay === '' && after.display !== 'none' && !after.hasHiddenClass && after.contentLen > 100 && after.windowFlag === 'undefined';
  console.log(pass ? 'RESULT: PASS（预览可见、无行内污染，bug 已修复）' : 'RESULT: FAIL（预览区空白或状态分裂，bug 存在）');
  ws.close();
  process.exit(pass ? 0 : 1);
})().catch((e) => { console.error('ERR', e.message); process.exit(2); });
