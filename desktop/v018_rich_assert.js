/**
 * v0.1.8 断言：考卷内容呈现三修复（免 LLM：出题/判卷/拍照/图水合全部桥桩）
 * R1 题干公式：KaTeX 渲染（.katex 出现、无 $ 原样泄漏）、选项富渲染
 * R2 题干图片：![说明](路径) → 占位 img[data-quiz-img-path] → getImageAsBase64 桩水合为 data:image
 * R3 填空题拍照：拍照按钮/文件框/缩略容器存在；上传后作答含 ![手写解答](rel)；提交 payload 正确
 * R4 判卷结果页：得分卡富渲染（正确答案/点评公式、题干图再次水合）
 * R5 学页选段 MD 化：llSelectionMarkdown 图片转标准 MD 引用、无图回退纯文本；llNormalizeNoteImgWiki 归一化
 * R6 v0.1.9 题干表格：MD 表→真表（thead/tbody 结构、无竖线源码泄漏），答题/结果两页都渲染
 * 用法：node v018_rich_assert.js（需 9992 服务与 9224 CDP Electron 存活）
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
const USER = 'v018_asrt_' + TS;
const PWD = 'V018a!';
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

// 考卷桩：题干含公式/图片/表格；填空×2 简答×1 选择×2
const PNG1PX = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';
const QS = [
  { type: 'single', question: '当 $x_1=1$ 且 $x_2=2$ 时，求 $x_1+x_2$ 的值。', options: ['1', '2', '$x^2$', '3'], correct_answer: 'B', difficulty: '容易', explanation: '基础加法' },
  { type: 'fill', question: '完全平方公式 $(a+b)^2$ 展开为 ______。', correct_answer: 'a^2+2ab+b^2', difficulty: '容易', explanation: '公式' },
  { type: 'fill', question: '如图所示，笔记中蓝色曲线表示什么？![题图](截图/测试.png) 答：______。', correct_answer: '梯度', difficulty: '中等', explanation: '看图' },
  { type: 'short', question: '简述 $E=mc^2$ 的含义。', correct_answer: '质能方程', difficulty: '容易', explanation: '定义' },
  { type: 'single', question: '在表1-1中，ReLU 的输出范围是？\n| 激活函数 | 输出范围 |\n| --- | --- |\n| ReLU* | [0,+∞) |\n| Sigmoid* | (0,1) |\n| 范数 a\\|b | 任意实数 |', options: ['[0,+∞)', '(0,1)', '(-1,1)', '0或1'], correct_answer: 'A', difficulty: '容易', explanation: '看表作答' },
];
const SETUP = `(function(QS, PNG1PX){
  window.__alerts = []; window.alert = function(m){ window.__alerts.push(String(m)); };
  window.__errs = []; window.addEventListener('error', function(e){ window.__errs.push(String(e.message||'')); });
  window.__imgReqs = [];
  window.bridge.generatePracticeQuiz = function (j) { window.__genPayload = JSON.parse(j);
    return Promise.resolve({ success: true, practice_id: 'quiz_t1', questions: QS, difficulty_used: '容易', matched_point: null }); };
  window.bridge.uploadQuizPhoto = function (durl) { window.__photoDurl = String(durl).slice(0, 20);
    return Promise.resolve({ success: true, path: 'C:/vault/截图/测试.png', rel: '截图/测试.png', markdown: '![截屏](截图/测试.png)' }); };
  window.bridge.getImageAsBase64 = function (p) { window.__imgReqs.push(String(p));
    return Promise.resolve({ success: true, dataUrl: PNG1PX }); };
  window.bridge.submitPracticeQuiz = function (j) { var p = JSON.parse(j); window.__subPayload = p;
    var det = QS.map(function(q,i){ return { question_index:i, question:q.question, type:q.type, options:q.options||null,
      user_answer: String(p.answers[i]||''), correct_answer:q.correct_answer, is_correct:(i===0), difficulty:q.difficulty,
      explanation:q.explanation, comment:(i===1?'展开式缺了交叉项 $ab$':'') }; });
    return Promise.resolve({ success: true, practice_id: p.practice_id, correct_count: 1, total_count: 5, accuracy: 0.2, score: 20, detailed_results: det }); };
  window.bridge.matchQuizErrorPoints = function (q) { return Promise.resolve({ success: true, candidates: [] }); };
  window.bridge.saveErrorsToKnowledgeBase = function (j) { return Promise.resolve({ success: true, saved_count: 0 }); };
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

  // 依赖存在性（页面应已加载 katex + md_render；学页选段函数已暴露）
  const q0 = await page.evalJs(`JSON.stringify({ katex: typeof window.katex, md: typeof window.MdRender,
    selMd: typeof window.llSelectionMarkdown, wiki: typeof window.llNormalizeNoteImgWiki })`);
  const Q0 = JSON.parse(q0);
  chk('R0.1 KaTeX/MdRender 已加载', Q0.katex !== 'undefined' && Q0.md === 'object', Q0);
  chk('R0.2 选段 MD 化函数已暴露', Q0.selMd === 'function' && Q0.wiki === 'function', Q0);

  await page.evalJs(`${SETUP}(${JSON.stringify(QS)}, ${JSON.stringify(PNG1PX)})`);

  // 走配置弹窗默认全勾开始组卷 → 自动渲染考卷
  await page.evalJs(`(function(){ window.handlePractice(null, '断言选段含图 $(x)$ 文本'); var m=document.getElementById('quizConfigModal');
    m.querySelectorAll('.quiz-type-cb').forEach(function(cb){cb.checked=true;}); document.getElementById('quizConfigStartBtn').click(); return 1; })()`);
  await sleep(2000);

  // ================= R1 题干/选项公式渲染 =================
  const q1 = await page.evalJs(`(function(){
    var area = document.getElementById('questionDisplayArea');
    var rich = area.querySelectorAll('.quiz-rich');
    var katex = area.querySelectorAll('.katex');
    var stemTxt = area.querySelector('.quiz-q-card .quiz-rich') ? area.querySelector('.quiz-q-card .quiz-rich').textContent : '';
    var optKatex = 0;
    area.querySelectorAll('label').forEach(function(l){ if (l.querySelector('.katex')) optKatex++; });
    return JSON.stringify({ cards: area.querySelectorAll('.quiz-q-card').length, rich: rich.length,
      katex: katex.length, dollarLeak: /\\$x_1=1\\$|\\$\\(a\\+b\\)\\^2\\$/.test(stemTxt), optKatex: optKatex,
      errs: window.__errs });
  })()`);
  const Q1 = JSON.parse(q1);
  chk('R1.1 考卷5题卡片渲染', Q1.cards === 5, Q1);
  chk('R1.2 题干公式 KaTeX 生效且无 $ 源码泄漏', Q1.katex >= 4 && Q1.dollarLeak === false, Q1);
  chk('R1.3 选项富渲染（$x^2$ 选项出 katex）', Q1.optKatex >= 1, Q1);
  chk('R1.4 渲染无JS错误', Q1.errs.length === 0, Q1.errs);

  // ================= R2 题干图片占位 + 水合 =================
  const q2 = await page.evalJs(`(function(){
    var img = document.querySelector('#questionDisplayArea img[data-quiz-img-path="截图/测试.png"]');
    return JSON.stringify({ exists: !!img, hydrated: img ? String(img.src).slice(0, 15) : null,
      reqs: window.__imgReqs });
  })()`);
  const Q2 = JSON.parse(q2);
  chk('R2.1 题干图引用渲染为占位 img', Q2.exists === true, Q2);
  chk('R2.2 走桥请求并水合为 dataUrl', Q2.reqs.indexOf('截图/测试.png') >= 0 && /^data:image\/png/.test(Q2.hydrated || ''), Q2);

  // ================= R6 v0.1.9 题干表格渲染（答题页） =================
  const q6 = await page.evalJs(`(function(){
    var area = document.getElementById('questionDisplayArea');
    var tbl = area.querySelector('table.quiz-q-table');
    var tds = tbl ? tbl.querySelectorAll('tbody td') : [];
    return JSON.stringify({ hasTable: !!tbl,
      th: tbl ? tbl.querySelectorAll('thead th').length : 0,
      tr: tbl ? tbl.querySelectorAll('tbody tr').length : 0,
      firstCell: tbl ? tds[0].textContent : '',
      normCell: tds.length >= 6 ? tds[4].textContent : '',
      emInside: tbl ? tbl.querySelectorAll('em, code').length : -1,
      pipeLeak: area.textContent.indexOf('| --- |') >= 0 });
  })()`);
  const Q6 = JSON.parse(q6);
  chk('R6.1 题干 MD 表渲成真表（2表头+3数据行）', Q6.hasTable && Q6.th === 2 && Q6.tr === 3, Q6);
  chk('R6.2 单元格内容正确', Q6.firstCell === 'ReLU*', Q6.firstCell);
  chk('R6.3 无竖线源码泄漏', Q6.pipeLeak === false, Q6);
  // 评审 Suggestion-1 回归锁：两单元格各含裸 * 不得被行内正则跨格配对成 <em>
  chk('R6.4 单元格星号不串格（表内无 em/code）', Q6.emInside === 0, Q6);
  // 评审 Suggestion-2 回归锁：\| 字面竖线不当列分隔，单元内原样显示
  chk('R6.5 转义竖线 \u007c 正确归并为单元格文本', Q6.normCell === '范数 a|b', Q6.normCell);

  // ================= R3 填空题拍照上传 =================
  const q3 = await page.evalJs(`(function(){
    var fills = Array.prototype.slice.call(document.querySelectorAll('#questionDisplayArea .quiz-q-card'))
      .filter(function(c){ return c.querySelector('input.quiz-answer[type="text"]'); });
    var withBtn = fills.filter(function(c){ return c.querySelector('.quiz-photo-btn') && c.querySelector('.quiz-photo-input') && c.querySelector('.quiz-photo-thumbs'); });
    return JSON.stringify({ fills: fills.length, withBtn: withBtn.length,
      shortBtn: !!document.querySelector('#questionDisplayArea textarea.quiz-answer') });
  })()`);
  const Q3 = JSON.parse(q3);
  chk('R3.1 填空题带拍照三件套(2/2)', Q3.fills === 2 && Q3.withBtn === 2, Q3);
  // 第 3 题（idx=2，图题）拍照上传
  await page.evalJs(`(function(){
    var inp = document.querySelector('.quiz-photo-input[data-idx="2"]');
    var dt = new DataTransfer(); dt.items.add(new File(['fakepng'], 'hand.png', { type: 'image/png' }));
    inp.files = dt.files; inp.dispatchEvent(new Event('change', { bubbles: true })); return 1; })()`);
  await sleep(1200);
  const q3b = await page.evalJs(`(function(){
    var thumbs = document.querySelectorAll('.quiz-photo-thumbs[data-idx="2"] img');
    var inpVal = document.querySelector('#questionDisplayArea input.quiz-answer[type="text"][data-idx="2"]').value;
    return JSON.stringify({ thumbs: thumbs.length, photoDurl: window.__photoDurl || '', inputVal: inpVal });
  })()`);
  const Q3B = JSON.parse(q3b);
  chk('R3.2 填空拍照上传出缩略图', Q3B.thumbs === 1 && String(Q3B.photoDurl).indexOf('data:') === 0, Q3B);
  chk('R3.3 拍照不污染输入框（仍为纯文字）', String(Q3B.inputVal).indexOf('![') < 0, Q3B);
  // 提交：填空2 只拍照不写字，其它题留空 → confirm 放行
  await page.evalJs(`(function(){ window.confirm = function(){ return true; }; document.getElementById('quizSubmitBtn').click(); return 1; })()`);
  await sleep(1800);
  const q3c = await page.evalJs(`(function(){ var p = window.__subPayload || {};
    return JSON.stringify({ a2: String((p.answers||[])[2]||''), a1: String((p.answers||[])[1]||''), n: (p.answers||[]).length }); })()`);
  const Q3C = JSON.parse(q3c);
  chk('R3.4 提交作答含照片 MD 引用', Q3C.n === 5 && Q3C.a2.indexOf('![手写解答](截图/测试.png)') >= 0, Q3C);
  chk('R3.5 未拍照填空不带图引用', Q3C.a1.indexOf('![') < 0, Q3C);

  // ================= R4 判卷结果页富渲染 =================
  await sleep(1200); // 等结果页图片再水合
  const q4 = await page.evalJs(`(function(){
    var area = document.getElementById('questionDisplayArea');
    var katex = area.querySelectorAll('.katex').length;
    var img = area.querySelector('img[data-quiz-img-path="截图/测试.png"]');
    var leak = /\\$ab\\$/.test(area.textContent);
    return JSON.stringify({ score: (area.querySelector('.text-3xl')||{}).textContent, katex: katex,
      imgHydrated: img ? String(img.src).indexOf('data:image/png') === 0 : false, leak: leak, errs: window.__errs,
      resTable: !!area.querySelector('table.quiz-q-table'), resPipeLeak: area.textContent.indexOf('| --- |') >= 0 });
  })()`);
  const Q4 = JSON.parse(q4);
  chk('R4.1 结果页得分显示', Q4.score === '20', Q4.score);
  chk('R4.2 结果页公式渲染（答案/点评/题干）无泄漏', Q4.katex >= 6 && Q4.leak === false, Q4);
  chk('R4.3 结果页题干图再次水合', Q4.imgHydrated === true, Q4.imgHydrated);
  chk('R4.4 判卷全流程无JS错误', Q4.errs.length === 0, Q4.errs);
  chk('R4.5 结果页题干表仍渲为真表且无源码泄漏', Q4.resTable === true && Q4.resPipeLeak === false, Q4);

  // ================= R5 学页选段提取 MD 化 =================
  const q5 = await page.evalJs(`(function(){
    // wiki 归一化
    var w = window.llNormalizeNoteImgWiki('见图 ![[sub/图表.png]] 说明');
    // 含图选段 MD 化：临时 box 注入 text + 水合前占位 img（data-ll-src 为编码原路径）
    var box = document.createElement('div');
    box.innerHTML = '<p>红线一侧可以通过平移得到</p><img data-ll-src="' + encodeURIComponent('attachments/图表.png') + '" src="data:image/svg+xml;base64,AA"><p>蓝色与哪些要素有关</p>';
    document.body.appendChild(box);
    var range = document.createRange(); range.selectNodeContents(box);
    var sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(range);
    var md = window.llSelectionMarkdown();
    sel.removeAllRanges(); box.remove();
    // 无图选段回退纯文本
    var box2 = document.createElement('div'); box2.textContent = '纯文字选段ABC';
    document.body.appendChild(box2);
    var r2 = document.createRange(); r2.selectNodeContents(box2);
    sel.removeAllRanges(); sel.addRange(r2);
    var plain = window.llSelectionMarkdown();
    sel.removeAllRanges(); box2.remove();
    return JSON.stringify({ w: w, md: md, plain: plain });
  })()`);
  const Q5 = JSON.parse(q5);
  chk('R5.1 wiki 图链接归一化为标准 MD', Q5.w === '见图 ![图表.png](attachments/图表.png) 说明', Q5.w);
  // 已打开过笔记时 resolveNoteImgSrc 会把 attachments/ 拼到当前目录前缀，只断言标准 MD 引用结构
  chk('R5.2 含图选段 MD 化（图片转标准引用+文字保留）', /!\[图表\.png\]\([^)]*图表\.png\)/.test(Q5.md)
    && Q5.md.indexOf('红线一侧') >= 0 && Q5.md.indexOf('蓝色') >= 0, Q5.md);
  chk('R5.3 无图选段回退纯文本', Q5.plain === '纯文字选段ABC', Q5.plain);

  const qe = await page.evalJs(`JSON.stringify(window.__errs)`);
  chk('R9.1 全程无页面JS错误', JSON.parse(qe).length === 0, qe);

  // 还原 token
  await page.evalJs(`localStorage.setItem('ll_token', ${JSON.stringify(origToken || '')}); location.reload(); 'restored'`, false).catch(() => {});
  await sleep(1200);
  page.close(); main.close();
  console.log('RESULT: ' + (FAIL === 0 ? 'ALL PASS' : FAIL + ' FAIL') + ' (PASS=' + PASS + ')');
  process.exit(FAIL === 0 ? 0 : 1);
})().catch((e) => { console.error('FATAL: ' + e.message); process.exit(1); });
