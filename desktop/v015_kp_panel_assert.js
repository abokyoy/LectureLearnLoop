/**
 * v0.1.5 知识点管理面板断言（2026-10-12）：
 *  E1 后端：PUT /api/knowledge/points/<pid>/name 校验链 + description 端点 + DB 生效
 *  E2 UI（CDP）：按钮互斥状态机 + 相似知识点行内编辑自动保存 + 合并/新增落库
 * 免 LLM：pybridge.extractKnowledgePoints 注入假提取结果，其余全部走真实后端。
 * 前提：后端 9992 已启动（新代码）；electron --remote-debugging-port=9224。
 * 用法：node v015_kp_panel_assert.js
 */
const path = require('path');
const http = require('http');
const WebSocket = require('ws');

const BASE = process.env.LL_SERVER || 'http://127.0.0.1:9992';
const CDP = 'http://127.0.0.1:' + (process.env.LL_CDP_PORT || '9224') + '/json';
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
  return { url: page.url, evalJs, close: () => ws.close() };
}

const TS = Date.now().toString().slice(-6);
const USER = 'v015_user_' + TS;
const PWD = 'V015test!';
const SUBJ = 'V015TestSubject';
const NAME_A = 'V015ExtractedAlpha';        // 与库内预置点同名 → 启发式 0.99
// 编辑目标名含实体/尖括号/引号：一并验证 escHtml 转义链不产生 DOM 注入且原值往返一致（CodeReview Major-2）
const NAME_A_EDITED = 'V015Edited<&>"\'点_' + TS;
const DESC_A_DB = '库内描述A_初始';
const DESC_A_EDITED = '库内描述A_已编辑' + TS;
const NAME_G = 'V015ExtractedGamma';        // 只走「新增」
const NOTE = 'v015_kp_probe_' + TS + '.md';

let TOKEN = '';
async function jf(p, opts, token) {
  const headers = { 'Content-Type': 'application/json' };
  if (token !== undefined ? token : TOKEN) headers.Authorization = 'Bearer ' + (token !== undefined ? token : TOKEN);
  const r = await fetch(BASE + p, Object.assign({}, opts, { headers }));
  return { status: r.status, body: await r.json().catch(() => ({})) };
}
async function dbPoints() {
  const j = await jf('/api/knowledge/points?subject=' + encodeURIComponent(SUBJ));
  return (j.body && j.body.data) || [];
}

/* ---------------- E1：后端 name/description 端点 ---------------- */
async function testE1() {
  await jf('/api/auth/register', { method: 'POST', body: JSON.stringify({ username: USER, password: PWD }) }, null);
  const lg = await jf('/api/auth/login', { method: 'POST', body: JSON.stringify({ username: USER, password: PWD }) }, null);
  TOKEN = lg.body && lg.body.data && lg.body.data.token;
  check(!!TOKEN, 'E1a 测试用户注册+登录');
  if (!TOKEN) return;

  // 预置科目+三个库内知识点（point-new 会 auto-add-subject）；
  // E1 的改名/改描述测试用独立靶点 E1Target，保持 Alpha 原状给 E2 的同名相似匹配+UI 编辑用
  const c1 = await jf('/api/knowledge/point-new', { method: 'POST', body: JSON.stringify({ subject: SUBJ, point: { name: NAME_A, description: DESC_A_DB } }) });
  const c2 = await jf('/api/knowledge/point-new', { method: 'POST', body: JSON.stringify({ subject: SUBJ, point: { name: 'V015库内Beta', description: '库内描述B' } }) });
  const c3 = await jf('/api/knowledge/point-new', { method: 'POST', body: JSON.stringify({ subject: SUBJ, point: { name: 'V015E1Target', description: 'E1初始描述' } }) });
  check(c1.body.data.success && c2.body.data.success && c3.body.data.success, 'E1b 预置科目与库内知识点', JSON.stringify(c1.body.data).slice(0, 120));
  const pidA = c3.body.data.knowledge_id;

  const noAuth = await fetch(BASE + '/api/knowledge/points/' + pidA + '/name', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: 'x' }) });
  check(noAuth.status === 401, 'E1c PUT /name 无 token → 401', 'status=' + noAuth.status);

  const empty = await jf('/api/knowledge/points/' + pidA + '/name', { method: 'PUT', body: JSON.stringify({ name: '   ' }) });
  check(empty.body.data.success === false, 'E1d 空白名称拒绝', JSON.stringify(empty.body.data).slice(0, 100));
  const longN = await jf('/api/knowledge/points/' + pidA + '/name', { method: 'PUT', body: JSON.stringify({ name: 'x'.repeat(201) }) });
  check(longN.body.data.success === false, 'E1e 超 200 字拒绝');
  const miss = await jf('/api/knowledge/points/99999999/name', { method: 'PUT', body: JSON.stringify({ name: 'ok' }) });
  check(miss.body.data.success === false, 'E1f 不存在/他人 pid 拒绝', JSON.stringify(miss.body.data).slice(0, 100));

  const okN = await jf('/api/knowledge/points/' + pidA + '/name', { method: 'PUT', body: JSON.stringify({ name: 'V015E1TargetRenamed_' + TS }) });
  check(okN.body.data.success === true, 'E1g 改名成功');
  const okD = await jf('/api/knowledge/points/' + pidA + '/description', { method: 'PUT', body: JSON.stringify({ description: DESC_A_EDITED }) });
  check(okD.body.data.success === true, 'E1h 改描述成功');
  const longD = await jf('/api/knowledge/points/' + pidA + '/description', { method: 'PUT', body: JSON.stringify({ description: 'y'.repeat(5001) }) });
  check(longD.body.data.success === false, 'E1i 描述超 5000 字拒绝');

  const pts = await dbPoints();
  const rowA = pts.find((p) => p.id === pidA);
  check(!!rowA && (rowA.point_name || rowA.name) === 'V015E1TargetRenamed_' + TS && (rowA.core_description || rowA.description) === DESC_A_EDITED,
        'E1j GET points 确认 name/description 均已落库', rowA ? JSON.stringify({ n: rowA.point_name || rowA.name }) : 'row missing');
  return pidA;
}

/* ---------------- E2：UI 状态机 + 行内编辑自动保存（CDP 真页面） ---------------- */
async function testE2(pidA) {
  // 探针笔记落盘（供文件树打开）
  await jf('/api/notes/autosave', { method: 'POST', body: JSON.stringify({ path: NOTE, content: '# v015 面板断言探针\n\n正文。\n' }) });

  const main = await attach((u) => u.startsWith(BASE));
  const origToken = await main.evalJs(`localStorage.getItem('ll_token') || ''`);
  await main.evalJs(`localStorage.setItem('ll_token', ${JSON.stringify(TOKEN)}); 'seeded'`);
  await main.evalJs(`location.href = ${JSON.stringify(BASE + '/online_course')}`, false).catch(() => {});
  await sleep(3500);

  const page = await attach((u) => /\/online_course/.test(u));
  // 免 LLM 注入：pybridge 为渲染侧普通对象，可安全覆盖（测完刷新即还原）
  const fake = JSON.stringify({ success: true, knowledge_points: [
    { name: NAME_A, description: '提取描述A' },
    { name: NAME_G, description: '提取描述G' },
  ] });
  const setup = await page.evalJs(`(() => {
    window.confirm = function () { return true; };
    window.__alerts = [];
    window.alert = function (m) { window.__alerts.push(String(m)); };
    window.pybridge.extractKnowledgePoints = function (p, cb) { setTimeout(function () { cb(${JSON.stringify(fake)}); }, 30); return 'stub'; };
    return typeof window.pybridge.findSimilarKnowledgePoints;
  })()`);
  check(setup === 'function', 'E2a 桥就绪 + 提取结果注入（免 LLM，其余全真实后端）');

  // 诊断：页面基础就绪状态
  const diag = await page.evalJs(`JSON.stringify({
    ready: document.readyState,
    anchors: document.querySelectorAll('.jstree-anchor').length,
    hasSelectFile: typeof window.selectFile,
    hasExtract: typeof window.extractKnowledgePoints,
    kbArea: !!document.getElementById('knowledge-content')
  })`);
  console.log('  E2 diag: ' + diag);

  // 第一步：打开探针笔记（独立预算，失败可定位）
  const openOut = await page.evalJs(`(async () => {
    var sleep = (ms) => new Promise(r => setTimeout(r, ms));
    var anchor = null;
    for (var i = 0; i < 24 && !anchor; i++) {
      anchor = Array.from(document.querySelectorAll('.jstree-anchor')).find(a => (a.textContent || '').indexOf(${JSON.stringify(NOTE)}) >= 0);
      if (!anchor) await sleep(500);
    }
    if (!anchor) return JSON.stringify({ err: 'tree node missing', total: document.querySelectorAll('.jstree-anchor').length });
    anchor.click();
    for (var k = 0; k < 20; k++) {
      await sleep(300);
      if (((document.getElementById('preview-title') || {}).textContent || '').indexOf('v015_kp_probe') >= 0) break;
    }
    return JSON.stringify({ title: (document.getElementById('preview-title') || {}).textContent || '', alerts: window.__alerts });
  })()`);
  console.log('  E2 open: ' + openOut);
  check(JSON.parse(openOut).title.indexOf('v015_kp_probe') >= 0, 'E2b1 探针笔记已打开（preview-title 更新）', openOut);

  // 第二步：触发提取链 → 知识点区渲染
  const extractOut = await page.evalJs(`(async () => {
    var sleep = (ms) => new Promise(r => setTimeout(r, ms));
    if (typeof window.extractKnowledgePoints !== 'function') return JSON.stringify({ err: 'window.extractKnowledgePoints missing' });
    window.extractKnowledgePoints();
    for (var j = 0; j < 20 && !document.getElementById('save-knowledge-btn'); j++) await sleep(300);
    return JSON.stringify({
      saveBtn: !!document.getElementById('save-knowledge-btn'),
      items: document.querySelectorAll('#knowledge-content .knowledge-point-item').length,
      alerts: window.__alerts
    });
  })()`);
  const ex = JSON.parse(extractOut);
  check(!ex.err && ex.saveBtn && ex.items === 2, 'E2b 提取渲染出 2 个知识点 + 保存按钮', extractOut);

  // 打开管理面板 + 选科目
  const panelOut = await page.evalJs(`(async () => {
    var sleep = (ms) => new Promise(r => setTimeout(r, ms));
    document.getElementById('save-knowledge-btn').click();
    for (var j = 0; j < 20 && !document.getElementById('subject-select'); j++) await sleep(300);
    var sel = document.getElementById('subject-select');
    if (!sel) return JSON.stringify({ err: 'no panel' });
    var has = false;
    for (var k = 0; k < 20 && !has; k++) {
      has = Array.from(sel.options).some(o => o.value === ${JSON.stringify(SUBJ)});
      if (!has) await sleep(300);
    }
    if (!has) return JSON.stringify({ err: 'subject option missing' });
    sel.value = ${JSON.stringify(SUBJ)};
    sel.dispatchEvent(new Event('change'));
    for (var m = 0; m < 20; m++) {
      await sleep(300);
      var bot = document.getElementById('subject-knowledge-list');
      if (bot && (bot.textContent || '').indexOf('V015') >= 0) break;
    }
    var cur = document.querySelectorAll('.current-knowledge-item');
    return JSON.stringify({ curCount: cur.length, bottomHasData: !!(bot && (bot.textContent || '').indexOf('V015') >= 0) });
  })()`);
  const pn = JSON.parse(panelOut);
  check(!pn.err && pn.curCount === 2 && pn.bottomHasData, 'E2c 面板打开：左 2 项 + 科目可选 + 底部库已加载', panelOut);

  // 只选左项 → 合并禁用 / 新增可用
  const u1 = await page.evalJs(`(() => {
    var items = document.querySelectorAll('.current-knowledge-item');
    items[0].click();
    return JSON.stringify({
      mergeDis: document.getElementById('merge-knowledge-btn').disabled,
      createDis: document.getElementById('create-new-knowledge-btn').disabled,
      ring: items[0].classList.contains('ring-primary')
    });
  })()`);
  const r1 = JSON.parse(u1);
  check(r1.ring && r1.mergeDis === true && r1.createDis === false, 'E2d 状态机：仅左选中 → 合并禁用、新增可用', u1);

  // 等相似列表渲染 → 点右项 → 合并可用 / 新增禁用 + 编辑提示
  const u2 = await page.evalJs(`(async () => {
    var sleep = (ms) => new Promise(r => setTimeout(r, ms));
    var sim = null;
    for (var j = 0; j < 30 && !sim; j++) {
      await sleep(300);
      sim = document.querySelector('.similar-knowledge-item');
    }
    if (!sim) return JSON.stringify({ err: 'no similar item' });
    sim.click();
    return JSON.stringify({
      simName: sim.querySelector('[data-edit-field=name]').textContent,
      simScore: sim.dataset.similarity,
      mergeDis: document.getElementById('merge-knowledge-btn').disabled,
      createDis: document.getElementById('create-new-knowledge-btn').disabled,
      hint: !!sim.querySelector('.kp-edit-hint')
    });
  })()`);
  const r2 = JSON.parse(u2);
  check(!r2.err && r2.simName === NAME_A && Number(r2.simScore) > 0.9, 'E2e 相似匹配命中库内同名点（启发式，不依赖 Ollama）', u2);
  check(r2.mergeDis === false && r2.createDis === true, 'E2f 状态机：左右都选中 → 合并可用、新增禁用（防误操作）', u2);
  check(r2.hint === true, 'E2g 选中后出现"点击标题/描述可编辑"提示');

  // 行内编辑标题 → 失焦自动保存 → DOM/dataset/DB 三处生效
  // 注：后台 Electron 窗口里 input 可能从未获得焦点，inp.blur() 是 no-op；
  // 必须 dispatchEvent(new FocusEvent('blur')) 确定性地触发失焦提交
  const u3 = await page.evalJs(`(async () => {
    var sleep = (ms) => new Promise(r => setTimeout(r, ms));
    var sim = document.querySelector('.similar-knowledge-item');
    var h4 = sim.querySelector('[data-edit-field=name]');
    h4.click();
    var inp = sim.querySelector('input');
    if (!inp) return JSON.stringify({ err: 'name click no input' });
    inp.value = ${JSON.stringify(NAME_A_EDITED)};
    inp.dispatchEvent(new FocusEvent('blur'));
    var editedText = '';
    for (var j = 0; j < 25; j++) {
      await sleep(300);
      var live = sim.querySelector('[data-edit-field=name]');
      editedText = live ? live.textContent : '';
      var valIn = inp.isConnected ? inp.value : '';
      if (editedText === ${JSON.stringify(NAME_A_EDITED)} || valIn === ${JSON.stringify(NAME_A_EDITED)}) break;
    }
    return JSON.stringify({
      domName: sim.querySelector('[data-edit-field=name]') ? sim.querySelector('[data-edit-field=name]').textContent : '',
      dataName: sim.dataset.name,
      stillSelected: sim.classList.contains('ring-blue-500'),
      injected: sim.querySelectorAll('img,script,svg,iframe').length,
      alerts: window.__alerts
    });
  })()`);
  const r3 = JSON.parse(u3);
  check(!r3.err && r3.domName === NAME_A_EDITED && r3.dataName === NAME_A_EDITED && r3.stillSelected,
        'E2h 标题行内编辑：失焦即落库回显，选中态保持（含实体/引号往返）', u3);
  check(r3.injected === 0, 'E2h2 恶意名称未产生 DOM 注入（img/script/svg/iframe=0）', u3);
  const pts3 = await dbPoints();
  check(pts3.some((p) => (p.point_name || p.name) === NAME_A_EDITED), 'E2i 标题编辑已真实写入数据库（node 侧独立复核）');

  // 行内编辑描述 → blur 自动保存
  const NEW_DESC = '合并前用户补充的完整描述_' + TS;
  const u4 = await page.evalJs(`(async () => {
    var sleep = (ms) => new Promise(r => setTimeout(r, ms));
    var want = ${JSON.stringify(NEW_DESC)};
    var sim = document.querySelector('.similar-knowledge-item');
    var pEl = sim.querySelector('[data-edit-field=desc]');
    pEl.click();
    var ta = sim.querySelector('textarea');
    if (!ta) return JSON.stringify({ err: 'desc click no textarea' });
    ta.value = want;
    ta.dispatchEvent(new FocusEvent('blur'));
    for (var j = 0; j < 20 && sim.querySelector('[data-edit-field=desc]').textContent.trim() !== want; j++) await sleep(300);
    return JSON.stringify({ domDesc: sim.querySelector('[data-edit-field=desc]').textContent.trim(), want: want });
  })()`);
  const r4 = JSON.parse(u4);
  check(!r4.err && r4.domDesc === NEW_DESC, 'E2j 描述行内编辑：失焦自动保存并回显', u4);

  // 描述清空 → 占位文案保底可点 → 再点占位可重新编辑（CodeReview Major-1 回归）
  const u4b = await page.evalJs(`(async () => {
    var sleep = (ms) => new Promise(r => setTimeout(r, ms));
    var sim = document.querySelector('.similar-knowledge-item');
    var pEl = sim.querySelector('[data-edit-field=desc]');
    pEl.click();
    var ta = sim.querySelector('textarea');
    if (!ta) return JSON.stringify({ err: 'no textarea on clear' });
    ta.value = '';
    ta.dispatchEvent(new FocusEvent('blur'));
    for (var j = 0; j < 20 && sim.querySelector('[data-edit-field=desc]').textContent.indexOf('点击添加描述') < 0; j++) await sleep(300);
    var ph = sim.querySelector('[data-edit-field=desc]').textContent;
    // 再点占位：应重新进编辑且原值为空串（占位文案不会被当原值写库）
    sim.querySelector('[data-edit-field=desc]').click();
    var ta2 = sim.querySelector('textarea');
    var v2 = ta2 ? ta2.value : null;
    if (ta2) { ta2.dispatchEvent(new FocusEvent('blur')); }
    for (var k = 0; k < 15 && sim.querySelector('[data-edit-field=desc]').textContent.indexOf('点击添加描述') < 0; k++) await sleep(200);
    return JSON.stringify({ placeholder: ph, reopened: !!ta2, openVal: v2, dataDesc: sim.dataset.desc });
  })()`);
  const r4b = JSON.parse(u4b);
  check(!r4b.err && r4b.placeholder === '（点击添加描述）' && r4b.reopened && r4b.openVal === '' && r4b.dataDesc === '',
        'E2q 空描述保存为占位文案且可再次编辑（占位不入库）', u4b);

  // 合并 → processed 标记 + 双按钮禁用 + 库内 sources 关联笔记
  const u5 = await page.evalJs(`(async () => {
    var sleep = (ms) => new Promise(r => setTimeout(r, ms));
    var cur = document.querySelectorAll('.current-knowledge-item')[0];
    document.getElementById('merge-knowledge-btn').click();
    for (var j = 0; j < 25 && cur.dataset.processed !== 'true'; j++) await sleep(300);
    return JSON.stringify({
      processed: cur.dataset.processed,
      mergeDis: document.getElementById('merge-knowledge-btn').disabled,
      createDis: document.getElementById('create-new-knowledge-btn').disabled,
      similarCleared: !document.querySelector('.similar-knowledge-item')
    });
  })()`);
  const r5 = JSON.parse(u5);
  check(r5.processed === 'true' && r5.similarCleared, 'E2k 合并成功：左项标记已处理、相似区清空', u5);
  check(r5.mergeDis === true && r5.createDis === true, 'E2l 合并后状态机复位：双按钮禁用');

  // 第二项只左选 → 新增可用 → 创建落库
  const u6 = await page.evalJs(`(async () => {
    var sleep = (ms) => new Promise(r => setTimeout(r, ms));
    var items = document.querySelectorAll('.current-knowledge-item');
    items[1].click();
    var midState = {
      mergeDis: document.getElementById('merge-knowledge-btn').disabled,
      createDis: document.getElementById('create-new-knowledge-btn').disabled
    };
    document.getElementById('create-new-knowledge-btn').click();
    for (var j = 0; j < 25 && items[1].dataset.processed !== 'true'; j++) await sleep(300);
    return JSON.stringify({ midState: midState, processed: items[1].dataset.processed,
      mergeDis2: document.getElementById('merge-knowledge-btn').disabled,
      createDis2: document.getElementById('create-new-knowledge-btn').disabled });
  })()`);
  const r6 = JSON.parse(u6);
  check(r6.midState.mergeDis === true && r6.midState.createDis === false, 'E2m 仅左选第二项：合并禁用、新增可用', JSON.stringify(r6.midState));
  check(r6.processed === 'true' && r6.mergeDis2 === true && r6.createDis2 === true, 'E2n 新增成功：已处理标记 + 双按钮禁用', u6);
  const pts6 = await dbPoints();
  check(pts6.some((p) => (p.point_name || p.name) === NAME_G), 'E2o 新知识点已真实入库（node 侧复核）');
  const srcA = pts6.find((p) => (p.point_name || p.name) === NAME_A_EDITED);
  const srcR = srcA ? await jf('/api/knowledge/points/' + srcA.id + '/sources') : { body: {} };
  const srcArr = (srcR.body && srcR.body.data) || [];
  check(!!srcA && Array.isArray(srcArr) && srcArr.length >= 1, 'E2p 合并后库内点关联了当前笔记（sources>=1）', JSON.stringify(srcArr).slice(0, 150));

  // 还原现场：原 token + 重新加载
  await page.evalJs(`localStorage.setItem('ll_token', ${JSON.stringify(origToken || '')}); location.reload(); 'restored'`, false).catch(() => {});
  await sleep(2500);
  await page.close();
  main.close();
}

(async () => {
  let pidA = 0;
  try { pidA = await testE1(); } catch (e) { check(false, 'E1 执行异常', String(e)); }
  try { await testE2(pidA); } catch (e) { check(false, 'E2 执行异常（electron/9224 未就绪？）', String(e)); }
  console.log(failures.length ? `\nRESULT: FAIL ${failures.length} -> ${failures.join(' | ')}` : '\nRESULT: ALL PASS');
  process.exit(failures.length ? 1 : 0);
})();
