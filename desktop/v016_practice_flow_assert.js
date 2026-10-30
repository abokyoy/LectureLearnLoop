/**
 * v0.1.6 断言（回归资产）：开始练习流程修复自证（免 LLM，覆盖桥方法返回假题面）
 * R1 消息按钮链路：消息无题面全文+有完成关键词+有按钮 → 点击 → 最大化+练习Tab+面板题面非空
 * R2 手动切Tab防白页：生成完成后不点按钮，手动最大化+点练习Tab → 面板自动渲染题面
 * R3 连续二次练习：新一轮题就绪后切Tab自动刷新；最大化模式练习消息区带按钮；无重复渲染/递归
 * 用法：node v016_practice_flow_assert.js（需 9992 服务与 9224 CDP Electron 存活；输出 [PASS]/[FAIL]，退出码 0=全过）
 */
const http = require('http');
const WebSocket = require('ws');

const BASE = process.env.LL_SERVER || 'http://127.0.0.1:9992';
const CDP = 'http://127.0.0.1:' + (process.env.LL_CDP_PORT || '9224') + '/json';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const QMARK = '断言题甲XYZ'; // 题面唯一标记，用于判断全文是否泄漏进消息

function getJSON(url) {
  return new Promise((res, rej) => http.get(url, (r) => {
    let d = ''; r.on('data', (c) => (d += c)); r.on('end', () => { try { res(JSON.parse(d)); } catch (e) { rej(e); } });
  }).on('error', rej));
}
async function attach(matcher) {
  let page = null;
  for (let i = 0; i < 40 && !page; i++) {
    try { page = (await getJSON(CDP)).find((t) => t.type === 'page' && matcher(t.url)); } catch (e) {}
    if (!page) await sleep(500);
  }
  if (!page) throw new Error('no target for ' + matcher);
  const ws = new WebSocket(page.webSocketDebuggerUrl, { perMessageDeflate: false });
  await new Promise((res, rej) => { ws.on('open', res); ws.on('error', rej); });
  let id = 0;
  const send = (method, params) => new Promise((res, rej) => {
    const mid = ++id;
    const to = setTimeout(() => rej(new Error(method + ' timeout')), 90000);
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
  return { evalJs, close: () => ws.close() };
}

const TS = Date.now().toString().slice(-6);
const USER = 'v016_asrt_' + TS;
const PWD = 'V016a!';
let TOKEN = '';
async function jf(p, opts, token) {
  const headers = { 'Content-Type': 'application/json' };
  const tk = token === undefined ? TOKEN : token;
  if (tk) headers.Authorization = 'Bearer ' + tk;
  const r = await fetch(BASE + p, Object.assign({}, opts, { headers }));
  return { status: r.status, body: await r.json().catch(() => ({})) };
}

let PASS = 0, FAIL = 0;
function chk(name, cond, detail) {
  if (cond) { PASS++; console.log('[PASS] ' + name); }
  else { FAIL++; console.log('[FAIL] ' + name + ' :: ' + String(detail).slice(0, 300)); }
}

// 注入桥覆盖 + 错误捕获（reload 后需重注入）
const SETUP = `(function(QMARK){
  window.__alerts = []; window.alert = function(m){ window.__alerts.push(String(m)); };
  window.__errs = []; window.addEventListener('error', function(e){ window.__errs.push(String(e.message)); });
  // v0.1.7 适配：本脚本回归的是旧自由题面通道；临时禁用考卷配置弹窗入口，强制走降级兜底路径
  window.openQuizConfigDialog = null; window.startQuizFlow = null;
  var FAKE = '1. ' + QMARK + '？\\nA) x B) y\\n\\n2. 断言题乙：概括 supervised learning。\\n';
  window.bridge.generatePracticeQuestions = function (t) { return Promise.resolve(FAKE); };
  window.globalDebugLogs.length = 0;
  return 'ok';
})`;

(async () => {
  await jf('/api/auth/register', { method: 'POST', body: JSON.stringify({ username: USER, password: PWD }) }, null);
  const lg = await jf('/api/auth/login', { method: 'POST', body: JSON.stringify({ username: USER, password: PWD }) }, null);
  TOKEN = lg.body && lg.body.data && lg.body.data.token;
  console.log('login ok=' + !!TOKEN);
  if (!TOKEN) { console.log('RESULT: ENV FAIL'); process.exit(1); }

  const main = await attach((u) => u.startsWith(BASE));
  const origToken = await main.evalJs(`localStorage.getItem('ll_token') || ''`);
  await main.evalJs(`localStorage.setItem('ll_token', ${JSON.stringify(TOKEN)}); 'seeded'`);
  await main.evalJs(`location.href = ${JSON.stringify(BASE + '/online_course')}`, false).catch(() => {});
  await sleep(3500);
  const page = await attach((u) => /\/online_course/.test(u));

  // ================= R1：消息按钮链路 =================
  await page.evalJs(`${SETUP}(${JSON.stringify(QMARK)})`);
  await page.evalJs(`(function(){ window.handlePractice(null, '断言选中文本内容ABC'); return 1; })()`);
  await sleep(2500);

  const r1 = await page.evalJs(`(function(){
    var m = document.getElementById('aiChatMessages');
    var texts = m ? Array.from(m.querySelectorAll('.message-content')).map(function(e){ return e.textContent; }) : [];
    var btn = m ? Array.from(m.querySelectorAll('button')).find(function(b){ return b.textContent.indexOf('开始练习') >= 0; }) : null;
    if (btn) btn.click();
    return JSON.stringify({ texts: texts.map(function(t){return t.slice(0,200);}), btn: btn ? btn.textContent.trim() : null });
  })()`);
  const R1 = JSON.parse(r1);
  const allTxt = R1.texts.join('\n');
  chk('R1.1 生成中提示消息存在', allTxt.indexOf('正在生成练习题目') >= 0, R1.texts);
  chk('R1.2 完成消息存在', allTxt.indexOf('练习题目生成完成') >= 0, R1.texts);
  chk('R1.3 题面全文未泄漏进消息', allTxt.indexOf(QMARK) < 0, R1.texts);
  chk('R1.4 开始练习按钮存在', !!R1.btn && R1.btn.indexOf('开始练习') >= 0, R1.btn);
  await sleep(1500);

  const r1b = await page.evalJs(`(function(){
    var win = document.getElementById('aiChatWindow');
    var prac = document.getElementById('practiceTabContent');
    var pcont = document.getElementById('practiceContainer');
    var qarea = document.getElementById('questionDisplayArea');
    var rel = document.getElementById('relatedContentDisplay');
    return JSON.stringify({ cls: win.className, pracActive: prac.classList.contains('active'),
      pcontDisp: getComputedStyle(pcont).display, qtxt: qarea.textContent, rtxt: rel ? rel.textContent.slice(0,80) : null,
      errs: window.__errs, alerts: window.__alerts });
  })()`);
  const R1B = JSON.parse(r1b);
  chk('R1.5 窗口自动最大化', R1B.cls.indexOf('maximized') >= 0, R1B.cls);
  chk('R1.6 自动切到练习Tab', R1B.pracActive === true, R1B);
  chk('R1.7 练习面板显示', R1B.pcontDisp === 'flex', R1B.pcontDisp);
  chk('R1.8 题面已渲染进面板', R1B.qtxt.indexOf(QMARK) >= 0, R1B.qtxt.slice(0, 150));
  chk('R1.9 相关学习内容=选中文本', R1B.rtxt && R1B.rtxt.indexOf('断言选中文本内容ABC') >= 0, R1B.rtxt);
  chk('R1.10 无JS错误/无alert', R1B.errs.length === 0 && R1B.alerts.length === 0, R1B);

  // ================= R2：手动切 Tab 防白页（不点按钮） =================
  await page.evalJs(`location.reload(); 'r'`, false).catch(() => {});
  await sleep(3500);
  await page.evalJs(`${SETUP}(${JSON.stringify(QMARK)})`);
  await page.evalJs(`(function(){ window.handlePractice(null, '断言选中文本内容ABC'); return 1; })()`);
  await sleep(2500); // 等 ready，但不点消息按钮
  // 手动最大化 + 手动点练习 Tab（模拟用户行为）
  await page.evalJs(`(function(){ var b = document.getElementById('maximizeChatBtn'); if (b) b.click(); return 1; })()`);
  await sleep(600);
  await page.evalJs(`(function(){ var b = document.getElementById('practiceTabBtn'); if (b) b.click(); return 1; })()`);
  await sleep(1200);

  const r2 = await page.evalJs(`(function(){
    var win = document.getElementById('aiChatWindow');
    var prac = document.getElementById('practiceTabContent');
    var pcont = document.getElementById('practiceContainer');
    var qarea = document.getElementById('questionDisplayArea');
    var welcome = document.getElementById('practiceWelcomePanel');
    return JSON.stringify({ cls: win.className, pracActive: prac.classList.contains('active'),
      pcontDisp: getComputedStyle(pcont).display,
      welcomeDisp: welcome ? getComputedStyle(welcome).display : 'GONE',
      qtxt: qarea.textContent, errs: window.__errs, alerts: window.__alerts,
      autoLog: (window.globalDebugLogs||[]).some(function(l){ return l.indexOf('自动渲染练习面板') >= 0; }) });
  })()`);
  const R2 = JSON.parse(r2);
  chk('R2.1 手动切Tab后面板显示（不白页）', R2.pcontDisp === 'flex', R2);
  chk('R2.2 手动切Tab后题面已渲染', R2.qtxt.indexOf(QMARK) >= 0, R2.qtxt.slice(0, 150));
  chk('R2.3 欢迎页被让位', R2.welcomeDisp === 'none' || R2.welcomeDisp === 'GONE', R2.welcomeDisp);
  chk('R2.4 自动渲染日志出现', R2.autoLog === true, R2);
  chk('R2.5 无JS错误/无alert', R2.errs.length === 0 && R2.alerts.length === 0, R2);

  // ================= R3：连续二次练习（评审 W-1/W-2 时序）+ S-1 最大化模式按钮 =================
  // 不 reload，窗口当前已最大化；换一份新题面再发起第二轮练习
  await page.evalJs(`(function(){
    var FAKE2 = '1. 二次新题CCC？\\nA) p B) q\\n';
    window.bridge.generatePracticeQuestions = function (t) { return Promise.resolve(FAKE2); };
    window.handlePractice(null, '二次选中文本DEF');
    return 1;
  })()`);
  await sleep(2500);
  // 此时面板仍显示第一轮题（showAIPracticePanel 只存不渲染）→ 手动切走再切回练习Tab 应自动刷新为第二轮题
  const r3a = await page.evalJs(`(function(){
    var m = document.getElementById('aiPracticeMessages');
    var btns = m ? Array.from(m.querySelectorAll('button')).map(function(b){return b.textContent.trim();}).join('|') : '';
    var l = document.getElementById('learningTabBtn'); if (l) l.click();
    return JSON.stringify({ btns: btns });
  })()`);
  const R3A = JSON.parse(r3a);
  chk('R3.1 最大化模式练习消息区附加开始练习按钮(S-1)', R3A.btns.indexOf('开始练习') >= 0, R3A);
  await sleep(400);
  await page.evalJs(`(function(){ var b = document.getElementById('practiceTabBtn'); if (b) b.click(); return 1; })()`);
  await sleep(1200);
  const r3b = await page.evalJs(`(function(){
    var qarea = document.getElementById('questionDisplayArea');
    var pcont = document.getElementById('practiceContainer');
    return JSON.stringify({ qtxt: qarea.textContent, pcontDisp: getComputedStyle(pcont).display,
      errs: window.__errs, auto: (window.globalDebugLogs||[]).filter(function(l){return l.indexOf('自动渲染练习面板')>=0;}).length });
  })()`);
  const R3B = JSON.parse(r3b);
  chk('R3.2 二次练习切Tab后面板仍显示', R3B.pcontDisp === 'flex', R3B);
  chk('R3.3 题面刷新为第二轮新题（面板非旧题）', R3B.qtxt.indexOf('二次新题CCC') >= 0 && R3B.qtxt.indexOf(QMARK) < 0, R3B.qtxt.slice(0, 160));
  chk('R3.4 自动渲染仅触发一次（无重复渲染/递归）', R3B.auto <= 2, R3B.auto);
  chk('R3.5 无JS错误', R3B.errs.length === 0, R3B.errs);

  // 还原 token
  await page.evalJs(`localStorage.setItem('ll_token', ${JSON.stringify(origToken || '')}); location.reload(); 'restored'`, false).catch(() => {});
  await sleep(1200);
  page.close(); main.close();
  console.log('RESULT: ' + (FAIL === 0 ? 'ALL PASS' : FAIL + ' FAIL') + ' (PASS=' + PASS + ')');
  process.exit(FAIL === 0 ? 0 : 1);
})().catch((e) => { console.error('FATAL: ' + e.message); process.exit(1); });
