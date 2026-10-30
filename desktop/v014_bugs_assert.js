/**
 * v0.1.4 三 bug 修复断言（2026-10-12）：
 *  A1 悬浮窗关闭后 recording 残留 → done() 必须等清标识请求完成（node vm 行为测试）
 *  A2 toast 不再压在窗口控制按钮区（模板静态扫描：无 top-4 right-4 残留，全部 top-16）
 *  A3 笔记页公式渲染走本地 vendor + MdRender 保护管线（CDP 真页面全链路）
 * 前提：后端 9992 已启动；electron --remote-debugging-port=9224（A3 用）。
 * 用法：node v014_bugs_assert.js
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const http = require('http');
const WebSocket = require('ws');

const BASE = process.env.LL_SERVER || 'http://127.0.0.1:9992';
const CDP = 'http://127.0.0.1:' + (process.env.LL_CDP_PORT || '9224') + '/json';
const ROOT = path.resolve(__dirname, '..');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let failures = [];
function check(cond, name, detail) {
  console.log(`[${cond ? 'PASS' : 'FAIL'}] ${name}${detail ? '  ' + detail : ''}`);
  if (!cond) failures.push(name);
}
function getJSON(url) {
  return new Promise((res, rej) => http.get(url, (r) => {
    let d = ''; r.on('data', (c) => (d += c)); r.on('end', () => { try { res(JSON.parse(d)); } catch (e) { rej(e); } });
  }).on('error', rej));
}
async function attach(matcher) {
  let page = null;
  for (let i = 0; i < 40 && !page; i++) {
    try { page = (await getJSON(CDP)).find((t) => t.type === 'page' && matcher(t.url)); } catch (e) { /* 未就绪 */ }
    if (!page) await sleep(500);
  }
  if (!page) throw new Error('no target for ' + matcher);
  const ws = new WebSocket(page.webSocketDebuggerUrl, { perMessageDeflate: false });
  await new Promise((res, rej) => { ws.on('open', res); ws.on('error', rej); });
  let id = 0;
  const send = (method, params) => new Promise((res, rej) => {
    const mid = ++id;
    const to = setTimeout(() => rej(new Error(method + ' timeout')), 25000);
    const onMsg = (raw) => {
      const m = JSON.parse(raw);
      if (m.id === mid) { ws.off('message', onMsg); clearTimeout(to); m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result); }
    };
    ws.on('message', onMsg);
    ws.send(JSON.stringify({ id: mid, method, params: params || {} }));
  });
  await send('Page.enable');
  const evalJs = async (expression, awaitPromise = true) => {
    const r = await send('Runtime.evaluate', { expression, awaitPromise, returnByValue: true });
    if (r.exceptionDetails) throw new Error('page exception: ' + JSON.stringify((r.exceptionDetails.exception && r.exceptionDetails.exception.description) || r.exceptionDetails.text));
    return r.result.value;
  };
  return { url: page.url, evalJs, close: () => ws.close() };
}

/* ---------------- A1：done() 等待清标识（vm 行为测试） ---------------- */
async function testA1() {
  const src = fs.readFileSync(path.join(ROOT, 'server', 'static', 'js', 'recorder.js'), 'utf8');
  // 静态：done() 里 recording off 必须被 await（Promise.race 包裹亦算，行为由 A1b 实地验）
  check(/await Promise\.race\(\[\s*this\.api\('\/api\/notes\/recording'[\s\S]{0,200}?on: false/.test(src),
        'A1a 静态：done() 清标识调用带 await（Promise.race 3s 超时包裹）');

  const sandbox = { setInterval, clearInterval, setTimeout, clearTimeout, console, Promise, JSON, String, Number, Math, Date, Array, Object, Error };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(src, sandbox, { filename: 'recorder.js' });

  let offDoneAt = 0;
  sandbox.window.fetch = (p, opts) => new Promise((res) => {
    const delay = String(p).includes('/api/notes/recording') ? 120 : 5;
    setTimeout(() => {
      if (String(p).includes('/api/notes/recording') && opts && /"on":\s*false/.test(opts.body)) offDoneAt = Date.now();
      res({ json: () => Promise.resolve({ success: true, data: {} }) });
    }, delay);
  });
  const rec = new sandbox.window.LLRecorder({ getToken: () => 't' });
  rec.saveNow = async () => true;
  rec._teardown = async () => {};
  rec.state = 'recording';
  rec.note = { path: 'E:\\vault\\t.md', name: 't.md' };
  rec._recSec = 0;
  await rec.done();
  const doneAt = Date.now();
  check(offDoneAt > 0 && doneAt >= offDoneAt, 'A1b 行为：done() 返回时清标识请求已完成（窗口销毁前必达）',
        `off@${offDoneAt} done@${doneAt}`);
}

/* ---------------- A2：toast 位置静态扫描 ---------------- */
function testA2() {
  const active = ['server/templates/base.html', 'server/templates/pages/online_course_notes.html',
                  'server/templates/pages/learn_from_materials.html', 'server/templates/overlay.html'];
  for (const rel of active) {
    const t = fs.readFileSync(path.join(ROOT, rel), 'utf8');
    check(!t.includes('fixed top-4 right-4'), `A2 ${rel} 无 top-4 toast 残留（压窗口按钮）`);
  }
  const oc = fs.readFileSync(path.join(ROOT, 'server/templates/pages/online_course_notes.html'), 'utf8');
  check(oc.includes('fixed top-16 right-4'), 'A2 笔记页 toast 已落 Header 下方（top-16）');
}

/* ---------------- A3：笔记页公式管线（CDP 真页面·生产路径） ----------------
 * 页面巨型 script 块是 IIFE 包装（历史设计），renderMarkdownContent 不在 window 上，
 * 故不能直接函数级调用；改走用户真实链路：autosave 落盘含公式笔记 → 刷新页 →
 * 文件树点开 → 断言预览区出现 KaTeX 渲染且无公式源码泄漏。 */
async function testA3() {
  const jf = async (p, opts, token) => {
    const headers = { 'Content-Type': 'application/json' };
    if (token) headers.Authorization = 'Bearer ' + token;
    const r = await fetch(BASE + p, Object.assign({}, opts, { headers }));
    return r.json().catch(() => ({}));
  };
  const user = 'v014_user_' + Date.now().toString().slice(-6);
  const pwd = 'V014test!';
  await jf('/api/auth/register', { method: 'POST', body: JSON.stringify({ username: user, password: pwd }) });
  const lg = await jf('/api/auth/login', { method: 'POST', body: JSON.stringify({ username: user, password: pwd }) });
  const TOKEN = lg && lg.data && lg.data.token;
  check(!!TOKEN, 'A3 前置：测试用户登录获得 token');
  if (!TOKEN) return;

  // 生产接口落盘含公式笔记（相对路径→vault 根）
  const fname = 'v014_math_probe.md';
  const md = '# 公式探针\n\n总结：质能 $E=mc^2$ 行内，块级 $$\\frac{\\alpha}{\\beta} = c$$ 收尾。\n';
  const sv = await jf('/api/notes/autosave', { method: 'POST', body: JSON.stringify({ path: fname, content: md }) }, TOKEN);
  check(sv && sv.success && sv.data && sv.data.success, 'A3 前置：autosave 落盘探针笔记', JSON.stringify(sv).slice(0, 160));

  const main = await attach((u) => u.startsWith(BASE));
  await main.evalJs(`localStorage.setItem('ll_token', ${JSON.stringify(TOKEN)}); 'seeded'`);
  await main.evalJs(`location.href = ${JSON.stringify(BASE + '/online_course')}`, false).catch(() => {});
  await sleep(3500);

  const page = await attach((u) => /\/online_course/.test(u));
  // a) 静态：页内 script/link 标签无 CDN KaTeX，本地件已挂；库全局就绪（vendor 离线可验）
  const libs = await page.evalJs(`JSON.stringify({
    cdnKatex: document.querySelectorAll('script[src*="jsdelivr"][src*="katex"], link[href*="jsdelivr"][href*="katex"]').length,
    localKatex: document.querySelectorAll('script[src*="/static/vendor/vditor/dist/js/katex/"]').length,
    mdRender: document.querySelectorAll('script[src="/static/js/md_render.js"]').length,
    marked: typeof window.marked, katex: typeof window.katex, md: typeof window.MdRender
  })`);
  const lb = JSON.parse(libs);
  console.log('  A3 libs: ' + libs);
  check(lb.cdnKatex === 0 && lb.localKatex >= 1 && lb.mdRender === 1, 'A3a KaTeX/md_render 已本地化，无 CDN 依赖（客户机离线可用）', libs);
  check(lb.marked === 'object' && lb.katex === 'object' && lb.md === 'object', 'A3b marked/katex/MdRender 全局就绪（marked9 为命名空间 object）', libs);

  // A2f computed-style：Tailwind 预编译产物必须真的含 .top-16（CodeReview 教训：
  // 静态断言检测不出 purge 漏类导致的 top:auto 回归，必须量测渲染后的 top 值）
  const topVal = await page.evalJs(`(() => {
    var d = document.createElement('div');
    d.className = 'fixed top-16 right-4';
    d.style.pointerEvents = 'none';
    document.body.appendChild(d);
    var v = getComputedStyle(d).top;
    d.remove();
    return v;
  })()`);
  check(topVal === '64px', 'A2f .top-16 在预编译 cl.css 中确实生效（toast 落 Header 下方 64px）', 'computed top=' + topVal);

  // b) 生产链路：等 jsTree 节点出现并点击 → loadFileContent → preview 渲染
  const clickOut = await page.evalJs(`(async () => {
    var sleep = (ms) => new Promise(r => setTimeout(r, ms));
    var anchor = null;
    for (var i = 0; i < 20 && !anchor; i++) {
      anchor = Array.from(document.querySelectorAll('.jstree-anchor')).find(a => (a.textContent || '').indexOf('v014_math_probe') >= 0);
      if (!anchor) await sleep(500);
    }
    if (!anchor) return JSON.stringify({ err: 'tree node not found', anchors: document.querySelectorAll('.jstree-anchor').length });
    anchor.click();
    for (var k = 0; k < 16; k++) {
      await sleep(500);
      var pc = document.getElementById('preview-content');
      if (pc && pc.querySelector('.katex')) break;
    }
    var pc = document.getElementById('preview-content');
    if (!pc) return JSON.stringify({ err: 'no preview-content' });
    return JSON.stringify({
      katex: pc.querySelectorAll('.katex').length,
      hasFracSrc: (pc.textContent || '').indexOf('frac') >= 0,
      hasPh: (pc.textContent || '').indexOf('\\uE000') >= 0,
      hasEm: pc.querySelector('em') ? 1 : 0,
      title: (document.getElementById('preview-title') || {}).textContent || ''
    });
  })()`);
  console.log('  A3 preview: ' + clickOut);
  const co = JSON.parse(clickOut);
  check(!co.err && co.katex >= 2, 'A3c 真实打开笔记后预览区公式渲染为 KaTeX（行内+块级）', clickOut);
  check(co.hasFracSrc === false && co.hasPh === false, 'A3d 公式源码/占位符均不泄漏到文本');
  check(co.hasEm === 0, 'A3e 公式内下划线未被 marked 咬成斜体');
  await page.close();
  main.close();
}

(async () => {
  try { await testA1(); } catch (e) { check(false, 'A1 执行异常', String(e)); }
  try { testA2(); } catch (e) { check(false, 'A2 执行异常', String(e)); }
  try { await testA3(); } catch (e) { check(false, 'A3 执行异常（electron/9224 未就绪？）', String(e)); }
  console.log(failures.length ? `\nRESULT: FAIL ${failures.length} -> ${failures.join(' | ')}` : '\nRESULT: ALL PASS');
  process.exit(failures.length ? 1 : 0);
})();
