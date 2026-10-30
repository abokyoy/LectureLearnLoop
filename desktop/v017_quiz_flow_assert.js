/**
 * v0.1.7 断言：考卷全链路自证（免 LLM：出题/判卷/拍照/匹配用桥桩；练习历史走真实端点）
 * Q1 配置弹窗：右击开始练习先弹配置窗，默认全勾/5题/智能；全不勾有校验；自定义配置正确传入组卷请求
 * Q2 自动跳入考卷：渲染逐题卡片（选择/判断/填空/简答），旧答题区隐藏，提交判卷按钮出现
 * Q3 作答与拍照：文件选择→上传桩→缩略图；提交答案含截图 MD 引用
 * Q4 判卷结果页：得分/逐题正误/错题勾选→知识点候选→勾选入库 payload 正确
 * Q5 二次点击恢复：返回欢迎页清态后，聊天按钮带 pid 从历史拉回考卷重新渲染
 * Q6 真实历史链路：REST 落库结构化考卷 → 历史弹窗可见 → 加载选中 → 考卷复看渲染
 * 用法：node v017_quiz_flow_assert.js（需 9992 服务与 9224 CDP Electron 存活）
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
const USER = 'v017_asrt_' + TS;
const PWD = 'V017a!';
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

// 桥桩：出题/判卷/拍照/匹配/入库/按pid恢复（Q6 不动 getPracticeHistory/loadPracticeHistory 真实调用则另起会话）
const QS = [
  { type: 'single', question: '断言选择：1+1等于几？', options: ['1', '2', '3', '4'], correct_answer: 'B', difficulty: '容易', explanation: '基础加法' },
  { type: 'judge', question: '断言判断：太阳从西边升起。', correct_answer: '错误', difficulty: '容易', explanation: '常识' },
  { type: 'fill', question: '断言填空：水的化学式是 ______。', correct_answer: 'H2O', difficulty: '容易', explanation: '化学基础' },
  { type: 'short', question: '断言简答：简述监督学习。', correct_answer: '有标签学习', difficulty: '容易', explanation: '定义要点' },
];
const SETUP = `(function(QS){
  window.__alerts = []; window.alert = function(m){ window.__alerts.push(String(m)); };
  window.__errs = []; window.addEventListener('error', function(e){ window.__errs.push(String(e.message||'')); });
  window.__toasts = []; var oldToast = window.showToast;
  window.bridge.generatePracticeQuiz = function (j) { var p = JSON.parse(j); window.__genPayload = p;
    return Promise.resolve({ success: true, practice_id: 'quiz_t1', questions: QS, difficulty_used: '容易', matched_point: null }); };
  window.bridge.uploadQuizPhoto = function (durl) { window.__photoDurl = String(durl).slice(0, 20);
    return Promise.resolve({ success: true, path: 'C:/vault/截图/测试.png', rel: '截图/测试.png', markdown: '![截屏](截图/测试.png)' }); };
  window.bridge.submitPracticeQuiz = function (j) { var p = JSON.parse(j); window.__subPayload = p;
    var det = QS.map(function(q,i){ return { question_index:i, question:q.question, type:q.type, options:q.options||null,
      user_answer: String(p.answers[i]||''), correct_answer:q.correct_answer, is_correct:(i!==1&&i!==3), difficulty:q.difficulty,
      explanation:q.explanation, comment:(i===3?'答得不错但缺要点':'') }; });
    return Promise.resolve({ success: true, practice_id: p.practice_id, correct_count: 2, total_count: 4, accuracy: 0.5, score: 50, detailed_results: det }); };
  window.bridge.matchQuizErrorPoints = function (q) { return Promise.resolve({ success: true, candidates: [
    { id: 11, point_name: '测试知识点甲', score: 0.9, subject: '测试学科' }, { id: 12, point_name: '测试知识点乙', score: 0.5, subject: '测试学科' } ] }); };
  window.bridge.saveErrorsToKnowledgeBase = function (j) { window.__savePayload = JSON.parse(j);
    return Promise.resolve({ success: true, message: '已保存 2 条错题到知识库', saved_count: 2 }); };
  window.bridge.loadPracticeHistory = function (pid) { window.__loadPid = String(pid);
    return Promise.resolve({ success: true, practice: { practice_id: String(pid), selected_text: '断言选中文本ABC',
      questions: JSON.stringify(QS), user_answers: '', evaluation_result: '', status: 'generated' } }); };
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

  // 基础存在性 + 旧按钮已移除
  const q0 = await page.evalJs(`(function(){
    var m = document.getElementById('quizConfigModal');
    if (m) m.classList.remove('show');
    return JSON.stringify({ modal: !!m, welcomeNew: !!document.getElementById('welcomeNewPracticeBtn'),
      topNew: !!document.getElementById('newPracticeBtn'), topStart: !!document.getElementById('startPracticeBtn'),
      fnDlg: typeof window.openQuizConfigDialog, fnFlow: typeof window.startQuizFlow });
  })()`);
  const Q0 = JSON.parse(q0);
  chk('Q0.1 配置弹窗DOM存在', Q0.modal === true, Q0);
  chk('Q0.2 欢迎页开始新练习按钮已移除', Q0.welcomeNew === false, Q0.welcomeNew);
  chk('Q0.3 顶栏新练习/开始新练习已移除', Q0.topNew === false && Q0.topStart === false, Q0);
  chk('Q0.4 考卷入口函数已暴露', Q0.fnDlg === 'function' && Q0.fnFlow === 'function', Q0);

  await page.evalJs(`${SETUP}(${JSON.stringify(QS)})`);

  // ================= Q1 配置弹窗 =================
  await page.evalJs(`(function(){ window.handlePractice(null, '断言选中文本ABC'); return 1; })()`);
  await sleep(500);
  const q1a = await page.evalJs(`(function(){
    var m = document.getElementById('quizConfigModal');
    var cbs = Array.prototype.slice.call(m.querySelectorAll('.quiz-type-cb'));
    var diffSmart = m.querySelector('input[name="quizDiffRadio"][value="smart"]').checked;
    var count = document.getElementById('quizCountSelect').value;
    var diffSelDisabled = document.getElementById('quizDiffSelect').disabled;
    // 全不勾 → 校验
    cbs.forEach(function(cb){ cb.checked = false; });
    document.getElementById('quizConfigStartBtn').click();
    return JSON.stringify({ shown: m.classList.contains('show'), types: cbs.length, smart: diffSmart, count: count, diffSelDisabled: diffSelDisabled,
      stillShown: m.classList.contains('show') });
  })()`);
  const Q1A = JSON.parse(q1a);
  chk('Q1.1 右击开始练习弹出配置窗', Q1A.shown === true, Q1A);
  chk('Q1.2 默认题型4项全勾/5题/智能难度', Q1A.types === 4 && Q1A.smart === true && Q1A.count === '5', Q1A);
  chk('Q1.3 全不勾时校验拦截（弹窗不关）', Q1A.stillShown === true, Q1A);
  // 自定义配置：单选+简答、4题、难度自定义=容易 → 开始组卷
  const q1b = await page.evalJs(`(function(){
    var m = document.getElementById('quizConfigModal');
    m.querySelectorAll('.quiz-type-cb').forEach(function(cb){ cb.checked = (cb.value === 'single' || cb.value === 'short'); });
    document.getElementById('quizCountSelect').value = '3';
    var custom = m.querySelector('input[name="quizDiffRadio"][value="custom"]'); custom.click(); // 真实点击触发 change 事件
    var diffSel = document.getElementById('quizDiffSelect');
    var en1 = !diffSel.disabled; diffSel.value = '容易';
    document.getElementById('quizConfigStartBtn').click();
    return JSON.stringify({ closed: !m.classList.contains('show'), diffEnabled: en1 });
  })()`);
  const Q1B = JSON.parse(q1b);
  chk('Q1.4 选自定义后难度下拉解禁', Q1B.diffEnabled === true, Q1B);
  chk('Q1.5 开始组卷后弹窗关闭', Q1B.closed === true, Q1B);
  await sleep(1800);
  const q1c = await page.evalJs(`JSON.stringify(window.__genPayload || null)`);
  const GEN = JSON.parse(q1c);
  chk('Q1.6 组卷请求携带配置(types/count/difficulty)', GEN && GEN.types.join(',') === 'single,short' && GEN.count === 3 && GEN.difficulty === '容易' && GEN.selected_text === '断言选中文本ABC', GEN);

  // ================= Q2 自动跳入考卷 =================
  const q2 = await page.evalJs(`(function(){
    var win = document.getElementById('aiChatWindow');
    var pcont = document.getElementById('practiceContainer');
    var cards = document.querySelectorAll('#questionDisplayArea .quiz-q-card');
    var legacy = document.getElementById('practiceLegacyAnswerArea');
    var submitBtn = document.getElementById('quizSubmitBtn');
    var oldSubmit = document.getElementById('submitAnswerBtn');
    var radios = document.querySelectorAll('#questionDisplayArea input.quiz-answer[type="radio"]');
    var textIn = document.querySelectorAll('#questionDisplayArea input.quiz-answer[type="text"]');
    var areas = document.querySelectorAll('#questionDisplayArea textarea.quiz-answer');
    var photoBtns = document.querySelectorAll('.quiz-photo-btn');
    var welcome = document.getElementById('practiceWelcomePanel');
    var m = document.getElementById('aiPracticeMessages');
    var c = document.getElementById('aiChatMessages');
    var btns = ((m?Array.from(m.querySelectorAll('button')):[]).concat(c?Array.from(c.querySelectorAll('button')):[])).map(function(b){return b.textContent.trim();}).join('|');
    return JSON.stringify({ max: /maximized/.test(win.className), pcont: getComputedStyle(pcont).display,
      cards: cards.length, legacy: getComputedStyle(legacy).display, submit: getComputedStyle(submitBtn).display,
      oldSubmit: getComputedStyle(oldSubmit).display, radios: radios.length, textIn: textIn.length, areas: areas.length,
      photoBtns: photoBtns.length, welcomeHidden: !welcome || getComputedStyle(welcome).display === 'none',
      msgBtns: btns, errs: window.__errs });
  })()`);
  const Q2 = JSON.parse(q2);
  chk('Q2.1 自动最大化+面板显示', Q2.max === true && Q2.pcont === 'flex', Q2);
  chk('Q2.2 逐题卡片渲染4题', Q2.cards === 4, Q2);
  chk('Q2.3 题型控件正确(选择/判断radio=6 填空=1 简答=1)', Q2.radios === 6 && Q2.textIn === 1 && Q2.areas === 1, Q2);
  chk('Q2.4 填空/简答都带拍照上传按钮', Q2.photoBtns === 2, Q2.photoBtns);
  chk('Q2.5 旧答题区/旧提交按钮隐藏，提交判卷出现', Q2.legacy === 'none' && Q2.oldSubmit === 'none' && Q2.submit !== 'none', Q2);
  chk('Q2.6 欢迎页让位', Q2.welcomeHidden === true, Q2.welcomeHidden);
  chk('Q2.7 练习消息区带开始练习按钮', Q2.msgBtns.indexOf('开始练习') >= 0, Q2.msgBtns);
  chk('Q2.8 无JS错误', Q2.errs.length === 0, Q2.errs);

  // ================= Q3 作答 + 拍照上传 =================
  const q3 = await page.evalJs(`(function(){
    var r = document.querySelector('input.quiz-answer[type="radio"][value="B"]'); r.checked = true; r.dispatchEvent(new Event('change', { bubbles: true }));
    var tf = document.querySelector('#questionDisplayArea input[type="text"].quiz-answer'); tf.value = 'H2O'; tf.dispatchEvent(new Event('input', { bubbles: true }));
    var ta = document.querySelector('#questionDisplayArea textarea.quiz-answer'); ta.value = '监督学习是有标签的学习。'; ta.dispatchEvent(new Event('input', { bubbles: true }));
    var inp = document.querySelector('.quiz-photo-input[data-idx="3"]'); // 简答题位（v0.1.8 起填空也有拍照钮，须按 idx 定位）
    var dt = new DataTransfer(); dt.items.add(new File(['fakepng'], 'hand.png', { type: 'image/png' }));
    inp.files = dt.files; inp.dispatchEvent(new Event('change', { bubbles: true }));
    return 1;
  })()`);
  await sleep(1200);
  const q3b = await page.evalJs(`(function(){
    var thumbs = document.querySelectorAll('.quiz-photo-thumbs img');
    return JSON.stringify({ thumbs: thumbs.length, photoDurl: window.__photoDurl || null });
  })()`);
  const Q3B = JSON.parse(q3b);
  chk('Q3.1 拍照上传触发桥方法', String(Q3B.photoDurl).indexOf('data:') === 0, Q3B);
  chk('Q3.2 上传后缩略图出现', Q3B.thumbs === 1, Q3B.thumbs);
  // 判断题留空 → 直接提交（应 confirm 未答提示：覆盖 confirm 返回 true）
  await page.evalJs(`(function(){ window.confirm = function(){ return true; }; document.getElementById('quizSubmitBtn').click(); return 1; })()`);
  await sleep(1500);
  const q3c = await page.evalJs(`(function(){
    var p = window.__subPayload || {};
    return JSON.stringify({ n: (p.answers||[]).length, a0: (p.answers||[])[0]||'', a3: (p.answers||[])[3]||'', pid: p.practice_id,
      qn: (p.questions||[]).length, sel: p.selected_text });
  })()`);
  const Q3C = JSON.parse(q3c);
  chk('Q3.3 提交payload含题目/答案/考卷号/文本', Q3C.n === 4 && Q3C.qn === 4 && Q3C.pid === 'quiz_t1' && Q3C.sel === '断言选中文本ABC', Q3C);
  chk('Q3.4 选择题答案B已记录', Q3C.a0 === 'B', Q3C.a0);
  chk('Q3.5 简答答案含拍照MD引用', Q3C.a3.indexOf('监督学习') >= 0 && Q3C.a3.indexOf('![手写解答](截图/测试.png)') >= 0, Q3C.a3);

  // ================= Q4 判卷结果 + 勾选错题入库 =================
  const q4 = await page.evalJs(`(function(){
    var area = document.getElementById('questionDisplayArea');
    var score = area.querySelector('.text-3xl'); var cbs = area.querySelectorAll('.quiz-err-cb');
    var saveBtn = document.getElementById('quizSaveErrorsBtn');
    var submitBtn = document.getElementById('quizSubmitBtn');
    return JSON.stringify({ score: score ? score.textContent : null, wrongCbs: cbs.length,
      saveBtn: saveBtn ? saveBtn.textContent.trim() : null, saveDisabled: saveBtn ? saveBtn.disabled : null,
      submitHidden: getComputedStyle(submitBtn).display });
  })()`);
  const Q4A = JSON.parse(q4);
  chk('Q4.1 判卷结果页得分显示', Q4A.score === '50', Q4A.score);
  chk('Q4.2 错题勾选框=2道', Q4A.wrongCbs === 2, Q4A);
  chk('Q4.3 提交判卷按钮结果态隐藏', Q4A.submitHidden === 'none', Q4A.submitHidden);
  // 勾选两道错题 → 知识点候选懒加载 → 入库
  await page.evalJs(`(function(){
    var cbs = document.querySelectorAll('.quiz-err-cb');
    cbs[0].click(); cbs[1].click();
    return cbs.length;
  })()`);
  await sleep(1000);
  const q4b = await page.evalJs(`(function(){
    var sels = document.querySelectorAll('.quiz-err-kp-select');
    var opts = sels.length ? Array.from(sels[0].options).map(function(o){return o.textContent;}) : [];
    var saveBtn = document.getElementById('quizSaveErrorsBtn');
    var st = saveBtn.disabled ? 'still-disabled' : 'enabled';
    if (!saveBtn.disabled) saveBtn.click();
    return JSON.stringify({ sels: sels.length, opts: opts, st: st });
  })()`);
  const Q4B = JSON.parse(q4b);
  chk('Q4.4 勾选后知识点候选懒加载', Q4B.sels === 2 && Q4B.opts.length === 2 && Q4B.opts[0].indexOf('测试知识点甲') >= 0, Q4B);
  chk('Q4.5 两道错题勾选后入库按钮解禁', Q4B.st === 'enabled', Q4B.st);
  await sleep(800);
  const q4c = await page.evalJs(`(function(){
    var p = window.__savePayload || {};
    var es = p.selected_errors || [];
    return JSON.stringify({ n: es.length, kp0: es[0] ? es[0].selected_knowledge_point : null,
      hasQ: es[0] ? !!es[0].question_content : false, hasA: es[0] ? 'user_answer' in es[0] : false,
      unchecked: document.querySelectorAll('.quiz-err-cb:checked').length });
  })()`);
  const Q4C = JSON.parse(q4c);
  chk('Q4.6 入库payload结构正确(kp.id/题目/用户答案)', Q4C.n === 2 && Q4C.kp0 && Q4C.kp0.id === 11 && Q4C.hasQ && Q4C.hasA, Q4C);
  chk('Q4.7 入库成功后勾选框复位', Q4C.unchecked === 0, Q4C.unchecked);

  // ================= Q5 返回首页后二次点击消息按钮恢复 =================
  await page.evalJs(`(function(){ document.getElementById('backToWelcomeBtn').click(); return 1; })()`);
  await sleep(600);
  const q5a = await page.evalJs(`(function(){
    var pcont = document.getElementById('practiceContainer');
    var welcome = document.getElementById('practiceWelcomePanel');
    return JSON.stringify({ pcont: getComputedStyle(pcont).display, welcomeShown: welcome && getComputedStyle(welcome).display !== 'none' });
  })()`);
  const Q5A = JSON.parse(q5a);
  chk('Q5.1 返回首页后面板隐藏/欢迎页出现', Q5A.pcont === 'none' && Q5A.welcomeShown === true, Q5A);
  // 点击聊天区「点击这里开始练习」按钮（小窗模式消息落在 aiChatMessages，v0.1.7 带 quizPid 闭包）→ 走 loadPracticeHistory(pid) 恢复
  const q5b = await page.evalJs(`(function(){
    var found = null;
    ['aiPracticeMessages','aiChatMessages'].some(function(cid){
      var m = document.getElementById(cid);
      var btn = m ? Array.from(m.querySelectorAll('button')).find(function(b){ return b.textContent.indexOf('开始练习') >= 0; }) : null;
      if (btn) { btn.click(); found = btn.textContent.trim(); }
      return !!btn;
    });
    return found;
  })()`);
  chk('Q5.2 聊天区开始练习按钮可点击', !!q5b, q5b);
  await sleep(1800);
  const q5c = await page.evalJs(`(function(){
    var cards = document.querySelectorAll('#questionDisplayArea .quiz-q-card');
    var pcont = document.getElementById('practiceContainer');
    return JSON.stringify({ loadPid: window.__loadPid || null, cards: cards.length, pcont: getComputedStyle(pcont).display,
      submit: getComputedStyle(document.getElementById('quizSubmitBtn')).display, errs: window.__errs });
  })()`);
  const Q5C = JSON.parse(q5c);
  chk('Q5.3 二次点击按pid从历史恢复考卷', Q5C.loadPid === 'quiz_t1' && Q5C.cards === 4, Q5C);
  chk('Q5.4 恢复后是答题态(提交判卷出现)', Q5C.pcont === 'flex' && Q5C.submit !== 'none', Q5C);
  chk('Q5.5 全流程无JS错误', Q5C.errs.length === 0, Q5C.errs);

  // ================= Q6 真实历史链路（重载页清除桩） =================
  const quizPid = 'quiz_asrt_' + TS;
  const save = await jf('/api/practice/history', { method: 'POST', body: JSON.stringify({
    practice_id: quizPid, selected_text: '真实历史断言文本', questions: JSON.stringify(QS),
    user_answers: '', answer_history: '', evaluation_result: '',
  }) });
  chk('Q6.1 REST 落库结构化考卷成功', save.body && save.body.data && save.body.data.success === true, save.body);
  await page.evalJs(`location.reload(); 'r'`, false).catch(() => {});
  await sleep(3500);
  const page2 = await attach((u) => /\/online_course/.test(u));
  await page2.evalJs(`(function(){
    window.__alerts = []; window.alert = function(m){ window.__alerts.push(String(m)); };
    window.__errs = []; window.addEventListener('error', function(e){ window.__errs.push(String(e.message||'')); });
    return 1; })()`);
  // 打开练习历史弹窗（按钮虽在隐藏容器内，程序化点击仍有效）
  await page2.evalJs(`(function(){ document.getElementById('practiceHistoryBtn').click(); return 1; })()`);
  await sleep(2000);
  const q6a = await page2.evalJs(`(function(){
    var modal = document.getElementById('practiceHistoryModal');
    var items = Array.prototype.slice.call(document.querySelectorAll('#practiceHistoryList .history-item'));
    return JSON.stringify({ shown: modal.classList.contains('show'), n: items.length, ids: items.map(function(i){ return i.dataset.practiceId; }) });
  })()`);
  const Q6A = JSON.parse(q6a);
  chk('Q6.2 练习历史不再为空（含考卷记录）', Q6A.shown === true && Q6A.ids.indexOf(quizPid) >= 0, Q6A);
  // 选中并加载
  await page2.evalJs(`(function(){
    var items = Array.prototype.slice.call(document.querySelectorAll('#practiceHistoryList .history-item'));
    var it = items.find(function(i){ return i.dataset.practiceId === ${JSON.stringify(quizPid)}; });
    if (it) it.click();
    document.getElementById('loadPracticeBtn').click();
    return 1; })()`);
  await sleep(2500);
  const q6b = await page2.evalJs(`(function(){
    var cards = document.querySelectorAll('#questionDisplayArea .quiz-q-card');
    var pcont = document.getElementById('practiceContainer');
    var win = document.getElementById('aiChatWindow');
    return JSON.stringify({ cards: cards.length, pcont: getComputedStyle(pcont).display, max: /maximized/.test(win.className),
      alerts: window.__alerts, errs: window.__errs });
  })()`);
  const Q6B = JSON.parse(q6b);
  chk('Q6.3 历史加载走真实桥恢复考卷渲染', Q6B.cards === 4 && Q6B.pcont === 'flex', Q6B);
  chk('Q6.4 无JS错误', Q6B.errs.length === 0, Q6B.errs);
  chk('Q6.5 无alert异常弹窗', Q6B.alerts.filter(function(a){ return a.indexOf('失败') >= 0; }).length === 0, Q6B.alerts);

  // 还原 token
  await page2.evalJs(`localStorage.setItem('ll_token', ${JSON.stringify(origToken || '')}); location.reload(); 'restored'`, false).catch(() => {});
  await sleep(1200);
  page2.close(); page.close(); main.close();
  console.log('RESULT: ' + (FAIL === 0 ? 'ALL PASS' : FAIL + ' FAIL') + ' (PASS=' + PASS + ')');
  process.exit(FAIL === 0 ? 0 : 1);
})().catch((e) => { console.error('FATAL: ' + e.message); process.exit(1); });
