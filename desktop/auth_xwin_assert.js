/**
 * 登录态跨窗口同步断言（缺陷回归：未勾选“记住登录”时子窗口误报“未登录”）。
 * 场景还原：token 只写入主窗口 sessionStorage（= 登录页不勾选“记住登录”的四期行为），
 * 然后依次验证 悬浮窗(overlay) 与 笔记选择窗(note-picker) 能否经 llAuth/auth:getToken 桥拿到主窗口 token。
 * 运行前提：后端 9992 已启动；electron 以 --remote-debugging-port=9222 启动。
 * 用法：node auth_xwin_assert.js
 */
const http = require('http');
const WebSocket = require('ws');

const BASE = process.env.LL_SERVER || 'http://127.0.0.1:9992';
const CDP = 'http://127.0.0.1:9222/json';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function getJSON(url) {
  return new Promise((res, rej) => http.get(url, (r) => {
    let d = ''; r.on('data', (c) => (d += c)); r.on('end', () => { try { res(JSON.parse(d)); } catch (e) { rej(e); } });
  }).on('error', rej));
}

let failures = [];
function check(cond, name, detail) {
  console.log(`[${cond ? 'PASS' : 'FAIL'}] ${name}${detail ? '  ' + detail : ''}`);
  if (!cond) failures.push(name);
}

// 连接一个 CDP target，返回 { evalJs, close }
async function attach(matcher) {
  let page = null;
  for (let i = 0; i < 40 && !page; i++) {
    try {
      const targets = await getJSON(CDP);
      page = targets.find((t) => t.type === 'page' && matcher(t.url));
    } catch (e) { /* 9222 未就绪，稍候 */ }
    if (!page) await sleep(500);
  }
  if (!page) throw new Error('no target for ' + matcher);
  const ws = new WebSocket(page.webSocketDebuggerUrl, { perMessageDeflate: false });
  await new Promise((res, rej) => { ws.on('open', res); ws.on('error', rej); });
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
  await send('Page.enable');
  const evalJs = async (expression, awaitPromise = true) => {
    const r = await send('Runtime.evaluate', { expression, awaitPromise, returnByValue: true });
    if (r.exceptionDetails) throw new Error('page exception: ' + JSON.stringify(r.exceptionDetails.exception && r.exceptionDetails.exception.description || r.exceptionDetails.text));
    return r.result.value;
  };
  return { url: page.url, evalJs, close: () => ws.close() };
}

(async () => {
  // 0) 注册独立测试用户（隔离数据，不污染正式账号），获得 JWT
  const user = 'xwin_user_' + Date.now().toString().slice(-6);
  const pwd = 'Xwin12345!';
  const jf = async (p, opts, token) => {
    const headers = { 'Content-Type': 'application/json' };
    if (token) headers.Authorization = 'Bearer ' + token;
    const r = await fetch(BASE + p, Object.assign({}, opts, { headers }));
    return r.json().catch(() => ({}));
  };
  let reg = await jf('/api/auth/register', { method: 'POST', body: JSON.stringify({ username: user, password: pwd }) });
  let TOKEN = reg && reg.data && reg.data.token;
  if (!TOKEN) {
    const lg = await jf('/api/auth/login', { method: 'POST', body: JSON.stringify({ username: user, password: pwd }) });
    TOKEN = lg && lg.data && lg.data.token;
  }
  check(!!TOKEN, '测试用户登录获得 token');
  if (!TOKEN) { finish(); return; }

  // 1) 主窗口：模拟“不勾选记住登录”的登录终态 —— token 只在 sessionStorage，localStorage 必须为空
  const main = await attach((u) => new RegExp(BASE.replace('http://', 'http://')).test(u) && !/note-picker|overlay|capture/.test(u));
  await main.evalJs(`(async () => {
    try { (window.llClearToken || function(){ localStorage.removeItem('ll_token'); })(); } catch(e){}
    localStorage.removeItem('ll_token');
    sessionStorage.setItem('ll_token', ${JSON.stringify(TOKEN)});
    return 'seeded';
  })()`);
  const state = await main.evalJs(`JSON.stringify({ ls: localStorage.getItem('ll_token')||'', ss: sessionStorage.getItem('ll_token')||'' })`);
  const st = JSON.parse(state);
  check(st.ls === '' && st.ss === TOKEN, '主窗口已置为会话级登录态（仅 sessionStorage）', 'ls=' + (st.ls ? '有值' : '空'));

  // 2) 主窗口打开悬浮窗
  await main.evalJs(`window.llShell.openOverlay()`);
  const overlay = await attach((u) => /\/overlay/.test(u));
  check(/\/overlay/.test(overlay.url), '悬浮窗已打开', overlay.url);

  // 3) 悬浮窗经 llAuth.refresh 拉取主窗口 token（修复前此处必为空 → 报“未登录”）
  const tkOverlay = await overlay.evalJs(`(async () => { await window.llAuth.refresh(); return window.llAuth.getToken(); })()`);
  check(tkOverlay === TOKEN, '悬浮窗 llAuth 拉到主窗口会话级 token');

  // 4) 悬浮窗弹出笔记选择窗（invoke 不 resolve，不 await）
  await overlay.evalJs(`window.llNotePicker.open()`, false);
  const picker = await attach((u) => /\/note-picker/.test(u));
  await sleep(2500); // 等 picker 页内首屏 refresh + load() 完成

  // 5) 裁决断言：选择窗不得再出现“未登录”文案；列表接口应鉴权成功（空账号即“没有匹配”而非报错/未登录）
  const pickerList = await picker.evalJs(`document.getElementById('list').innerText`);
  const pickerTk = await picker.evalJs(`window.llAuth ? window.llAuth.getToken() : ''`);
  check(pickerTk === TOKEN, '选择窗 llAuth 缓存了主窗口 token');
  check(!/未登录/.test(pickerList), '选择窗不再误报“未登录”', 'list=' + JSON.stringify(pickerList.slice(0, 60)));
  const listApiOk = await picker.evalJs(`(async () => { const r = await fetch('/api/notes/list', { headers: { Authorization: 'Bearer ' + window.llAuth.getToken() } }); const j = await r.json(); return r.status + ':' + (j.success === true); })()`);
  check(listApiOk === '200:true', '选择窗以该 token 调 /api/notes/list 鉴权通过', listApiOk);

  // 6) 登出即时生效断言：主窗口清空登录态后，悬浮窗 refresh 应拿不到 token
  await main.evalJs(`(async () => { sessionStorage.removeItem('ll_token'); localStorage.removeItem('ll_token'); return 'cleared'; })()`);
  const tkAfterLogout = await overlay.evalJs(`(async () => { await window.llAuth.refresh(); return window.llAuth.getToken(); })()`);
  check(tkAfterLogout === '', '主窗口登出后悬浮窗 token 同步失效（无旧快照滞留）');

  // 7) 还原悬浮窗登录态并收起弹层（取消选择窗），关闭测试 electron 由外部处理
  await main.evalJs(`sessionStorage.setItem('ll_token', ${JSON.stringify(TOKEN)}); 'restored'`);
  await picker.evalJs(`window.llNotePickerSel && llNotePickerSel.cancel(); 'cancelled'`, false);
  await sleep(500);
  overlay.close(); picker.close(); main.close();
  finish();
})().catch((e) => { console.log('SCRIPT ERROR:', e.message); failures.push('script:' + e.message); finish(); });

function finish() {
  console.log(failures.length ? ('FAILED: ' + failures.join(' | ')) : 'ALL PASS');
  process.exit(failures.length ? 1 : 0);
}
