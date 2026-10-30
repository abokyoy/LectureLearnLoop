/**
 * v0.1.7 布局断言：用户反馈四项修复自证（免 LLM，出题走桥桩）
 * L1 考卷题目展示区占满版面（quiz-mode 解除 300px 帽，高度占比 ≥45%）
 * L2 考卷模式隐藏旧模式「用户答案记录」；返回欢迎页后复位
 * L3 相关学习内容收起仅一条栏、展开 overlay 向上浮出不改变题目区高度
 * L4 toast z-index 高于助手面板且上沿低于窗口功能区（≥56px）
 * L5 Electron 环境最大化面板 top ≥ 原生 titleBarOverlay(56px) 下沿
 * 用法：node v017_layout_assert.js（需 9992 服务与 9224 CDP Electron 存活）
 */
const http = require('http');
const WebSocket = require('ws');

const BASE = process.env.LL_SERVER || 'http://127.0.0.1:9992';
const CDP = 'http://127.0.0.1:' + (process.env.LL_CDP_PORT || '9224') + '/json';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

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
const USER = 'v017l_asrt_' + TS;
const PWD = 'V017l!';
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
  const d = (detail && typeof detail === 'object') ? JSON.stringify(detail) : String(detail);
  if (cond) { PASS++; console.log('[PASS] ' + name); }
  else { FAIL++; console.log('[FAIL] ' + name + ' :: ' + d.slice(0, 400)); }
}

const QS = [
  { type: 'single', question: '布局断言选择：1+1？', options: ['1', '2', '3', '4'], correct_answer: 'B', difficulty: '容易', explanation: 'x' },
  { type: 'judge', question: '布局断言判断：太阳西升。', correct_answer: '错误', difficulty: '容易', explanation: 'x' },
  { type: 'fill', question: '布局断言填空：水 ______。', correct_answer: 'H2O', difficulty: '容易', explanation: 'x' },
  { type: 'short', question: '布局断言简答：监督学习。', correct_answer: '有标签', difficulty: '容易', explanation: 'x' },
  { type: 'single', question: '布局断言选择2：2+2？', options: ['3', '4', '5', '6'], correct_answer: 'B', difficulty: '中等', explanation: 'x' },
];
const SETUP = `(function(QS){
  window.bridge.generatePracticeQuiz = function (j) {
    return Promise.resolve({ success: true, practice_id: 'quiz_l1', questions: QS, difficulty_used: '中等', matched_point: null }); };
  window.bridge.submitPracticeQuiz = function (j) {
    return Promise.resolve({ success: true, score: 40, correct_count: 2, total_count: QS.length,
      detailed_results: QS.map(function(q,i){ return { question_index:i, question:q.question, type:q.type, options:q.options||null,
        user_answer:'x', correct_answer:q.correct_answer, is_correct:(i<2), difficulty:q.difficulty, explanation:'x', comment:'' }; }) }); };
  return 1;
})`;

(async () => {
  await jf('/api/auth/register', { method: 'POST', body: JSON.stringify({ username: USER, password: PWD }) }, null);
  const lg = await jf('/api/auth/login', { method: 'POST', body: JSON.stringify({ username: USER, password: PWD }) }, null);
  TOKEN = lg.body && lg.body.data && lg.body.data.token;
  console.log('login ok=' + !!TOKEN);
  if (!TOKEN) { console.log('RESULT: ENV FAIL (no token)'); process.exit(1); }

  const main = await attach((u) => u.startsWith(BASE));
  await main.evalJs(`localStorage.setItem('ll_token', ${JSON.stringify(TOKEN)}); 'seeded'`);
  // cache-buster：Flask 页面响应无 cache-control/ETag，Electron 启发式缓存会回旧 HTML（真机验收同样适用）
  await main.evalJs(`location.href = ${JSON.stringify(BASE + '/online_course?_=' + Date.now())}`, false).catch(() => {});
  await sleep(3500);
  const page = await attach((u) => /\/online_course/.test(u));

  await page.evalJs(`${SETUP}(${JSON.stringify(QS)})`);
  // 走真实考卷入口：右击处理 → 配置窗 → 直接确认（默认配置）→ 自动跳入
  await page.evalJs(`(function(){ window.handlePractice(null, '布局断言选中文本'); return 1; })()`);
  await sleep(400);
  await page.evalJs(`(function(){ document.getElementById('quizConfigStartBtn').click(); return 1; })()`);
  await sleep(1800);

  // ================= L1 考卷布局占满版面 =================
  const l1 = await page.evalJs(`(function(){
    var win = document.getElementById('aiChatWindow');
    if (!win.classList.contains('maximized')) { return JSON.stringify({ fatal: 'not maximized', cls: String(win.className) }); }
    var qda = document.getElementById('questionDisplayArea');
    var scrollBox = qda.closest('.flex-grow.mb-4.overflow-y-auto') || qda.parentElement;
    var winH = win.clientHeight;
    var qRect = qda.getBoundingClientRect(), sRect = scrollBox.getBoundingClientRect();
    return JSON.stringify({
      quizMode: win.classList.contains('quiz-mode'),
      winH: winH, qdaH: Math.round(qRect.height), scrollH: Math.round(sRect.height),
      scrollMaxH: getComputedStyle(scrollBox).maxHeight,
      cards: document.querySelectorAll('#questionDisplayArea .quiz-q-card').length
    });
  })()`);
  const L1 = JSON.parse(l1);
  chk('L1.0 已进入考卷答题页', L1.fatal === undefined && L1.cards === 5, L1);
  chk('L1.1 quiz-mode 类已挂到面板', L1.quizMode === true, L1);
  chk('L1.2 题目区滚动容器高度帽已解除(max-height none)', L1.scrollMaxH === 'none', L1.scrollMaxH);
  chk('L1.3 题目展示区占版面 ≥45%', L1.winH > 0 && L1.scrollH / L1.winH >= 0.45, { winH: L1.winH, scrollH: L1.scrollH, ratio: (L1.scrollH / L1.winH).toFixed(2) });

  // ================= L2 用户答案记录隐藏 =================
  const l2 = await page.evalJs(`(function(){
    var t = document.getElementById('answerHistoryTitle');
    return JSON.stringify({ titleDisp: t ? getComputedStyle(t).display : 'missing',
      areaDisp: getComputedStyle(document.getElementById('answerHistoryArea')).display });
  })()`);
  const L2 = JSON.parse(l2);
  chk('L2.1 考卷模式隐藏用户答案记录', L2.titleDisp === 'none' && L2.areaDisp === 'none', L2);

  // ================= L3 相关学习内容 overlay（真实点击切换） =================
  const l3 = await page.evalJs(`(function(){
    var wrap = document.getElementById('relatedContentWrap');
    var btn = document.getElementById('relatedContentToggleBtn');
    var disp = document.getElementById('relatedContentDisplay');
    var scrollBox = (document.getElementById('questionDisplayArea').closest('.flex-grow.mb-4.overflow-y-auto') || document.getElementById('questionDisplayArea').parentElement);
    var hCollapsed = Math.round(wrap.getBoundingClientRect().height);
    var qhBefore = Math.round(scrollBox.getBoundingClientRect().height);
    // 现场取证：副本数与父子链（排查页面片段死副本干扰）
    var copies = document.querySelectorAll('#relatedContentDisplay').length;
    var chain = []; var p = disp; while (p && chain.length < 6) { chain.push(p.tagName + (p.id ? '#' + p.id : '.' + String(p.className).split(' ')[0])); p = p.parentElement; }
    // 注入模拟学习内容（真实场景浮层有多行知识条目；占位文本太矮无法验证遮挡）
    var origHtml = disp.innerHTML;
    disp.innerHTML = '<div>' + Array.from({ length: 8 }, (_, i) => '<p>模拟学习内容条目 ' + (i + 1) + '：知识点解析与对应练习提示，展开时向上浮出遮盖题目区，收起后不占版面。</p>').join('') + '</div>';
    btn.click(); // 展开
    // 注意：getComputedStyle 返回 live 对象，必须在收起前把基本类型值快照下来，
    // 否则 JSON.stringify 时才惰性求值，读到的是收起后的状态（此前 L3.2/3.3 假失败根因）
    var dispPos = getComputedStyle(disp).position;
    var matches = disp.matches('#relatedContentWrap #relatedContentDisplay.rc-expanded');
    var offsetParent = disp.offsetParent ? disp.offsetParent.tagName + '#' + disp.offsetParent.id : null;
    var dRect = disp.getBoundingClientRect(), wRect = wrap.getBoundingClientRect(), qRect = scrollBox.getBoundingClientRect();
    var hExpandedWrap = Math.round(wrap.getBoundingClientRect().height);
    var qhAfter = Math.round(scrollBox.getBoundingClientRect().height);
    var expandedOk = !disp.classList.contains('hidden') && disp.classList.contains('rc-expanded');
    var floatsUp = dRect.bottom <= wRect.top + 2, overlapsQuestions = dRect.top < qRect.bottom;
    var rawRect = [Math.round(dRect.top), Math.round(dRect.left), Math.round(dRect.width), Math.round(dRect.height)];
    var wrapPos = getComputedStyle(wrap).position;
    var panelDisplay = getComputedStyle(document.getElementById('aiChatWindow')).display;
    var contDisplay = getComputedStyle(document.getElementById('practiceContainer')).display;
    btn.click(); // 收起
    var collapsedBack = disp.classList.contains('hidden');
    disp.innerHTML = origHtml; // 还原占位文本，不污染页面
    return JSON.stringify({ expandedOk: expandedOk, collapsedBack: collapsedBack,
      floatsUp: floatsUp, overlapsQuestions: overlapsQuestions,
      wrapTop: Math.round(wRect.top), qBottom: Math.round(qRect.bottom), dTop: Math.round(dRect.top), dBottom: Math.round(dRect.bottom),
      wrapPos: wrapPos, dispPos: dispPos, matches: matches, offsetParent: offsetParent,
      panelDisplay: panelDisplay, contDisplay: contDisplay,
      rawRect: rawRect, copies: copies, chain: chain, dispInWrap: wrap.contains(disp),
      hCollapsed: hCollapsed, hExpandedWrap: hExpandedWrap,
      floatsUp: floatsUp, overlapsQuestions: overlapsQuestions,
      qhBefore: qhBefore, qhAfter: qhAfter });
  })()`);
  const L3 = JSON.parse(l3);
  chk('L3.1 收起时仅占一条入口栏(≤70px)', L3.hCollapsed <= 70, L3.hCollapsed);
  chk('L3.2 点击展开为绝对定位浮层', L3.expandedOk === true && L3.dispPos === 'absolute', L3);
  chk('L3.3 展开向上浮出遮住题目区', L3.floatsUp === true && L3.overlapsQuestions === true, L3);
  chk('L3.4 展开不改变题目区高度(不占版面)', L3.qhBefore === L3.qhAfter && L3.hExpandedWrap <= 70, { qhBefore: L3.qhBefore, qhAfter: L3.qhAfter, hExpandedWrap: L3.hExpandedWrap });
  chk('L3.5 再次点击可收起', L3.collapsedBack === true, L3.collapsedBack);

  // ================= L4/L5 toast 与 Electron 顶部避让 =================
  const l4 = await page.evalJs(`(function(){
    if (typeof showToast === 'function') showToast('布局断言通知', 'success');
    var toasts = Array.prototype.slice.call(document.body.children).filter(function(el){
      return el.style && el.style.zIndex === '10050'; });
    var t = toasts[toasts.length - 1];
    var win = document.getElementById('aiChatWindow');
    var winZ = getComputedStyle(win).zIndex;
    var res = { toastFound: !!t };
    if (t) { var r = t.getBoundingClientRect();
      res.toastTop = Math.round(r.top); res.toastZ = t.style.zIndex; res.pointerEvents = t.style.pointerEvents; }
    res.winZ = winZ;
    res.isElectron = document.documentElement.classList.contains('ll-electron');
    res.winRectTop = Math.round(win.getBoundingClientRect().top);
    res.winComputedTop = getComputedStyle(win).top;
    return JSON.stringify(res);
  })()`);
  const L4 = JSON.parse(l4);
  chk('L4.1 toast 存在且 z-index 高于助手面板', L4.toastFound === true && Number(L4.toastZ) > Number(L4.winZ), { toastZ: L4.toastZ, winZ: L4.winZ });
  chk('L4.2 toast 上沿低于窗口功能区下沿(≥56px)', L4.toastFound === true && L4.toastTop >= 56, L4.toastTop);
  chk('L4.3 toast 不拦截点击(pointer-events none)', L4.pointerEvents === 'none', L4.pointerEvents);
  chk('L5.1 Electron 环境已打标', L4.isElectron === true, L4);
  chk('L5.2 最大化面板 top 避开原生按钮区(≥56px)', parseFloat(L4.winComputedTop) >= 56, { top: L4.winComputedTop });

  // ================= L6 复位与旧模式回归 =================
  const l6 = await page.evalJs(`(function(){
    var b = document.getElementById('backToWelcomeBtn'); if (b) b.click();
    return 1;
  })()`);
  await sleep(600);
  const l6b = await page.evalJs(`(function(){
    var win = document.getElementById('aiChatWindow');
    var t = document.getElementById('answerHistoryTitle');
    var scrollBox = document.createElement('div'); // 读默认样式：脱离 quiz-mode 后原 300px 帽选择器应重新可命中（以类未挂上为准）
    return JSON.stringify({ quizMode: win.classList.contains('quiz-mode'),
      titleDisp: t ? getComputedStyle(t).display : 'missing',
      containerMaxH: getComputedStyle(document.querySelector('.practice-main-container')).maxHeight });
  })()`);
  const L6 = JSON.parse(l6b);
  chk('L6.1 返回欢迎页后 quiz-mode 类已摘除', L6.quizMode === false, L6);
  chk('L6.2 用户答案记录恢复可见（旧模式回归）', L6.titleDisp !== 'none', L6.titleDisp);

  const errs = await page.evalJs(`JSON.stringify(window.__errs || [])`);
  console.log('summary: ' + PASS + '/' + (PASS + FAIL));
  if (FAIL > 0) { console.log('RESULT: FAILED (' + FAIL + ')'); process.exit(2); }
  console.log('RESULT: ALL PASS (' + PASS + ')'); process.exit(0);
})().catch((e) => { console.log('FATAL: ' + e.message); process.exit(1); });
