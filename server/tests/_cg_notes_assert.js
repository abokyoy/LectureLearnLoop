// 课文追问笔记树 E2E 断言（追问笔记树轮 2026-11-12）：全屏沉浸 + 框选菜单 + 锚定树 + 编辑 + 提取右栏
// 链路：注册测试用户 → seed（content_ready 课文 + 3 笔记：可锚/嵌套/降级） → openLesson 直进阅读步 →
//       DOM 断言锚下划线/淡黄虚线章节/折叠展开/框选菜单/追问与指派 POST 体捕获/未定位索引/
//       Vditor 编辑弹层 + PUT 捕获/提取右栏 confirm 捕获/旧问答输入框已消失 → 截图 → 清理
// 零真实 LLM：笔记与课文 seed 直灌；写路径全 mock（cgPost/cgPut 覆盖即全前端拦截）。
// 用法：LL_SERVER=http://127.0.0.1:9992 node _cg_notes_assert.js
const fs = require('fs');
const http = require('http');
const path = require('path');
const { execFileSync } = require('child_process');
module.paths.push('e:/LLM/LectureLearnLoop/desktop/node_modules');
const WebSocket = require('ws');
const BASE = process.env.LL_SERVER || 'http://127.0.0.1:5010';
const CDP = 'http://127.0.0.1:9333/json';
const DIR = 'e:/LLM/LectureLearnLoop/server/tests';
const SEEDJSON = path.join(DIR, '_cg_notes_seed.json');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function getJSON(url) {
    return new Promise((res, rej) => http.get(url, (r) => { let d = ''; r.on('data', c => d += c); r.on('end', () => { try { res(JSON.parse(d)); } catch (e) { rej(e); } }); }).on('error', rej));
}
function httpReq(url, method, body, token) {
    return new Promise((res, rej) => {
        const data = body ? JSON.stringify(body) : null;
        const headers = {};
        if (data) { headers['Content-Type'] = 'application/json'; headers['Content-Length'] = Buffer.byteLength(data); }
        if (token) headers['Authorization'] = 'Bearer ' + token;
        const req = http.request(url, { method, headers }, (r) => {
            let d = ''; r.on('data', c => d += c); r.on('end', () => { try { res(JSON.parse(d)); } catch (e) { res(null); } });
        });
        req.on('error', rej); if (data) req.write(data); req.end();
    });
}
let fails = 0;
function chk(name, ok, info) {
    console.log((ok ? '[PASS] ' : '[FAIL] ') + name + (ok ? '' : '  info=' + String(JSON.stringify(info)).slice(0, 400)));
    if (!ok) fails++;
}
(async () => {
    const U = 'cgnote_' + Date.now().toString().slice(-6);
    const reg = await httpReq(BASE + '/api/auth/register', 'POST', { username: U, password: 'Pass1234' });
    if (!reg || !reg.success) throw new Error('register failed: ' + JSON.stringify(reg));
    const TOKEN = reg.data.token;
    execFileSync('python', [path.join(DIR, '_cg_notes_seed.py'), U, SEEDJSON], { encoding: 'utf8' });
    const S = JSON.parse(fs.readFileSync(SEEDJSON, 'utf8'));
    console.log('SEEDED', JSON.stringify(S));

    let page = null;
    for (let i = 0; i < 40 && !page; i++) {
        try { page = (await getJSON(CDP)).find(t => t.type === 'page' && /9992|5010|about:blank|learn_goals/.test(t.url)); } catch (e) {}
        if (!page) await sleep(500);
    }
    if (!page) throw new Error('no cdp page');
    const ws = new WebSocket(page.webSocketDebuggerUrl, { perMessageDeflate: false });
    await new Promise((res, rej) => { ws.on('open', res); ws.on('error', rej); });
    let id = 0;
    const send = (method, params) => new Promise((res, rej) => {
        const mid = ++id;
        const to = setTimeout(() => rej(new Error(method + ' timeout')), 90000);
        const onMsg = (raw) => { const m = JSON.parse(raw.toString()); if (m.id === mid) { ws.off('message', onMsg); clearTimeout(to); m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result); } };
        ws.on('message', onMsg);
        ws.send(JSON.stringify({ id: mid, method, params: params || {} }));
    });
    const evalJs = async (expression, awaitPromise = true) => {
        const r = await send('Runtime.evaluate', { expression, awaitPromise, returnByValue: true });
        if (r.exceptionDetails) throw new Error('page exception: ' + ((r.exceptionDetails.exception && r.exceptionDetails.exception.description) || r.exceptionDetails.text));
        return r.result.value;
    };
    const waitFor = async (expr, sec) => {
        for (let i = 0; i < sec * 2; i++) { if (await evalJs(expr)) return true; await sleep(500); }
        return false;
    };
    await send('Page.enable');
    await send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 800, deviceScaleFactor: 1, mobile: false });
    await evalJs("window.stop(); null", false).catch(() => {});
    await evalJs(`location.href=${JSON.stringify(BASE + '/')}; 'ok'`, false);
    for (let i = 0; i < 30; i++) { if (await evalJs("typeof window.handleMenuClick === 'function'")) break; await sleep(1000); }
    await evalJs(`localStorage.setItem('ll_token', ${JSON.stringify(TOKEN)}); 'ok'`, false);
    await evalJs(`location.href=${JSON.stringify(BASE + '/learn_goals')}; 'ok'`, false);
    for (let i = 0; i < 30; i++) { if (await evalJs("typeof window.openLesson === 'function'")) break; await sleep(1000); }

    // N0 进阅读步并等锚定完成（loadNotes 真请求 → 锚下划线出现）
    await evalJs(`window.openLesson(${S.lid}); 'ok'`, false);
    const n0 = await waitFor(`!!document.querySelector('#cgMdBody .cg-anchor')`, 30);
    chk('N0 阅读步挂载且笔记锚定完成', n0 === true);
    if (!n0) { ws.close(); process.exit(1); }

    // N1 全屏沉浸：cg-read-mode 面板铺满视口、遮罩隐藏
    const n1a = await evalJs(`(function(){ var d = document.getElementById('cgLessonDrawer'), p = document.getElementById('cgDrawerPanel');
        return d.classList.contains('cg-read-mode') && p.offsetWidth >= window.innerWidth - 2
            && getComputedStyle(document.getElementById('cgDrawerMask')).display === 'none'; })()`);
    chk('N1 全屏沉浸阅读（面板铺满+遮罩隐）', n1a === true, { n1a });

    // N2 旧右上角问答输入框已消失
    const n2 = await evalJs(`!document.getElementById('cgChatPanel') && !document.getElementById('cgChatInput') && !document.getElementById('cgChatSend')`);
    chk('N2 旧问答输入框已移除', n2 === true, { n2 });

    // N3 锚定：顶层可定位笔记出下划线锚，文本=anchor_text
    const n3 = await evalJs(`(function(){ var a = document.querySelector('#cgMdBody .cg-anchor');
        return a ? { t: a.textContent, deco: getComputedStyle(a).textDecorationLine } : null; })()`);
    chk('N3 锚文本下划线出现', n3 && n3.t === '梯度下降通过沿负梯度方向迭代更新参数' && /underline/.test(n3.deco), { n3 });

    // N4 虚线淡黄子章节：问题+回答（图文并貌产物 mermaid 出图）渲染在锚点段后（留 mermaid 异步渲染窗口）
    await sleep(800);
    const n4 = await evalJs(`(function(){ var s = document.querySelector('.cg-read-note[data-note-id="${S.n1}"]');
        if (!s) return null; var cs = getComputedStyle(s);
        return { border: cs.borderStyle, q: s.innerText.indexOf('Q1SENTINEL') >= 0, a: s.innerText.indexOf('ANSWER1SENTINEL') >= 0,
                 svg: s.querySelectorAll('.cg-note-a svg').length }; })()`);
    chk('N4 淡黄虚线章节+问答+思路图', n4 && n4.border === 'dashed' && n4.q === true && n4.a === true && n4.svg >= 1, { n4 });

    // N5 无限嵌套：追问的追问渲染在父章节 .cg-note-kids 内
    const n5 = await evalJs(`(function(){ var k = document.querySelector('.cg-read-note[data-note-id="${S.n1}"] .cg-note-kids .cg-note[data-note-id="${S.n2}"]');
        return !!k && k.innerText.indexOf('Q2SENTINEL') >= 0 && k.innerText.indexOf('ANSWER2SENTINEL') >= 0; })()`);
    chk('N5 嵌套子章节（追问的追问）渲染', n5 === true, { n5 });

    // N6 点锚文本收起 → 回答区消失只剩摘要；再点恢复展开
    await evalJs(`document.querySelector('#cgMdBody .cg-anchor').click(); 'ok'`, false);
    await sleep(400);
    const n6a = await evalJs(`(function(){ var s = document.querySelector('.cg-read-note[data-note-id="${S.n1}"]');
        return s.getAttribute('data-collapsed') === '1' && !s.querySelector('.cg-note-a'); })()`);
    await evalJs(`document.querySelector('#cgMdBody .cg-anchor').click(); 'ok'`, false);
    await sleep(400);
    const n6b = await evalJs(`(function(){ var s = document.querySelector('.cg-read-note[data-note-id="${S.n1}"]');
        return s.getAttribute('data-collapsed') !== '1' && s.innerText.indexOf('ANSWER1SENTINEL') >= 0; })()`);
    chk('N6 点锚文本收起/再点展开', n6a === true && n6b === true, { n6a, n6b });

    // N7 框选菜单：正文拖选（模拟 selection + mouseup）出「追问/请老师讲课」
    await evalJs(`window.__selectIn = function (needle) {
        var md = document.getElementById('cgMdBody');
        var tw = document.createTreeWalker(md, NodeFilter.SHOW_TEXT); var w;
        while ((w = tw.nextNode())) {
            var idx = w.nodeValue.indexOf(needle);
            if (idx >= 0 && !(w.parentElement && w.parentElement.closest('.cg-anchor,.cg-note,.cg-anchor-group'))) {
                var r = document.createRange(); r.setStart(w, idx); r.setEnd(w, idx + needle.length);
                var sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(r);
                w.parentElement.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                return true;
            }
        }
        return false;
    }; 'ok'`, false);
    const selOk = await evalJs(`window.__selectIn('学习率决定每步步长')`);
    await sleep(300);
    const n7 = await evalJs(`(function(){ var m = document.getElementById('cgSelMenu');
        return m ? { ask: !!m.querySelector('#cgMenuAsk'), teach: m.innerText.indexOf('请老师讲课') >= 0 } : null; })()`);
    chk('N7 框选浮动菜单（追问+请老师讲课）', selOk === true && n7 && n7.ask === true && n7.teach === true, { selOk, n7 });

    // N8 追问提交捕获 POST body（question/anchor_text/无 parent_id=顶层）——mock 挂起不真写库
    await evalJs(`window.__cap = []; window.__postReal = window.cgPost;
        window.cgPost = function (u, b) {
            if (u.indexOf('/notes') >= 0 || u.indexOf('/board/assign') >= 0) { window.__cap.push({ u: u, b: b }); return new Promise(function () {}); }
            return window.__postReal(u, b);
        }; 'ok'`, false);
    await evalJs(`document.getElementById('cgMenuAsk').click(); 'ok'`, false);
    await sleep(200);
    const popOk = await evalJs(`(function(){ var p = document.getElementById('cgAskPop');
        if (!p) return null; document.getElementById('cgAskInput').value = 'CDP断言追问：为什么？';
        document.getElementById('cgAskSend').click(); return p.innerText.indexOf('学习率决定每步步长') >= 0; })()`);
    await sleep(400);
    const capN = await evalJs(`window.__cap.filter(function (c) { return c.u.indexOf('/notes') >= 0; })[0]`);
    chk('N8 追问弹层引用原文+提交体捕获', popOk === true && capN && capN.b.question === 'CDP断言追问：为什么？'
        && capN.b.anchor_text === '学习率决定每步步长' && capN.u === '/api/course/lessons/' + S.lid + '/notes', { popOk, capN });

    // N9 请老师讲课捕获 assign {kind:'text', text:选中文}
    await evalJs(`var p = document.getElementById('cgAskPop'); if (p) p.remove(); 'ok'`, false);
    await evalJs(`window.__selectIn('实践中常配合动量项使用')`, false);
    await sleep(300);
    await evalJs(`document.getElementById('cgMenuTeach').click(); 'ok'`, false);
    await sleep(400);
    const capA = await evalJs(`window.__cap.filter(function (c) { return c.u.indexOf('/board/assign') >= 0; })[0]`);
    chk('N9 请老师讲课指派体 kind=text+原文', capA && capA.b.kind === 'text' && capA.b.text === '实践中常配合动量项使用', { capA });
    await evalJs(`window.cgPost = window.__postReal; 'ok'`, false);

    // N10 未定位笔记降级右栏索引：徽章文案 + 点开弹层内容不丢
    const n10a = await waitFor(`(function(){ var b = document.getElementById('cgNotesIndex');
        return b && b.innerText.indexOf('未定位') >= 0 && !!b.querySelector('[data-open-nid="${S.n3}"]'); })()`, 10);
    chk('N10a 未定位节点进右栏索引', n10a === true);
    await evalJs(`document.querySelector('#cgNotesIndex [data-open-nid="${S.n3}"]').click(); 'ok'`, false);
    await sleep(400);
    const n10b = await evalJs(`(function(){ var m = document.getElementById('cgNoteViewModal');
        return m && m.innerText.indexOf('Q3SENTINEL') >= 0 && m.innerText.indexOf('ANSWER3SENTINEL') >= 0; })()`);
    chk('N10b 未定位查看弹层内容可见可编辑', n10b === true, { n10b });

    // N11 编辑弹层 Vditor 就绪 + PUT 捕获（保存调 /api/course/notes/<nid>）
    await evalJs(`document.getElementById('cgNvEdit').click(); 'ok'`, false);
    // Vditor 把 .vditor 类挂在挂载体本身（_ocn 现例口径），不能用后代选择器查
    const vdOk = await waitFor(`(function(){ var el = document.querySelector('#cgNoteEditModal #cgEdQ');
        return !!el && el.classList.contains('vditor') && !!el.querySelector('.vditor-ir'); })()`, 20);
    chk('N11a Vditor 编辑弹层就绪', vdOk === true);
    await sleep(800); // Vditor setValue 的 150ms 补偿窗口落定后再保存
    await evalJs(`window.__put = null; window.__putReal = window.cgPut;
        window.cgPut = function (u, b) { window.__put = { u: u, b: b }; return new Promise(function () {}); }; 'ok'`, false);
    await evalJs(`document.getElementById('cgEdSave').click(); 'ok'`, false);
    await sleep(500);
    const put = await evalJs(`window.__put`);
    chk('N11b 保存 PUT 端点与体捕获', put && put.u === '/api/course/notes/' + S.n3
        && typeof put.b.question === 'string' && put.b.question.indexOf('Q3SENTINEL') >= 0 && typeof put.b.answer_md === 'string', { put });
    await evalJs(`window.cgPut = window.__putReal; var m = document.getElementById('cgNoteEditModal'); if (m) m.remove(); 'ok'`, false);

    // N12 提取右栏：按钮 → 候选（相似提示）→ confirm 捕获；全程 mock 零积分零 LLM
    await evalJs(`window.cgPost = function (u, b) {
        if (u.indexOf('/extract') >= 0) return Promise.resolve({ points: [{ name: 'CDP提取点', description: '描述', category: '方法', importance: '高', match_status: '已存在相似知识点', similar_count: 2 }] });
        if (u.indexOf('/knowledge/confirm') >= 0) { window.__conf = { u: u, b: b }; return Promise.resolve({}); }
        return window.__postReal(u, b);
    }; window.__conf = null; 'ok'`, false);
    const hasBtn = await evalJs(`!!document.getElementById('cgExtractGoBtn') && document.getElementById('cgExtractPanel').innerText.indexOf('提取') >= 0`);
    chk('N12a 阅读右栏提取按钮存在', hasBtn === true, { hasBtn });
    await evalJs(`document.getElementById('cgExtractGoBtn').click(); 'ok'`, false);
    const candOk = await waitFor(`document.querySelectorAll('#cgExtractOut .cg-ext-item').length === 1 && document.getElementById('cgExtractOut').innerText.indexOf('已存在相似') >= 0`, 15);
    chk('N12b 候选列表+相似提示渲染', candOk === true);
    await evalJs(`document.getElementById('cgExtractSaveBtn').click(); 'ok'`, false);
    await sleep(500);
    const conf = await evalJs(`window.__conf`);
    const saved = await evalJs(`window.__cgExtractSaved === true && document.getElementById('cgExtractMsg').innerText.indexOf('已加入') >= 0`);
    chk('N12c 加入知识点库 confirm 体+成功提示', conf && conf.b.confirmations.length === 1
        && conf.b.confirmations[0].action === 'new' && conf.b.confirmations[0].point_data.point_name === 'CDP提取点' && saved === true, { conf, saved });
    await evalJs(`window.cgPost = window.__postReal; 'ok'`, false);

    // 截图：展开全树的全屏阅读视图
    await evalJs(`window.scrollTo(0, 0); var b = document.querySelector('#cgDrawerBody'); if (b) b.scrollTop = 0; 'ok'`, false);
    await sleep(400);
    const shot = await send('Page.captureScreenshot', { format: 'jpeg', quality: 75 });
    fs.writeFileSync('e:/LLM/LectureLearnLoop/design/walkthrough/course_notes_tree.jpg', Buffer.from(shot.data, 'base64'));
    console.log('SHOT: design/walkthrough/course_notes_tree.jpg user=' + U);

    // N13 全屏阅读退出入口（用户反馈「没有退出的地方」轮 2026-11-12）：
    // 阅读步显式「← 退出阅读」按钮可见；Esc 退出；弹层（z-50）开着时 Esc 不抢抽屉退出
    const exitVisible = await evalJs(`(function(){ var b = document.getElementById('cgReadExit'), d = document.getElementById('cgLessonDrawer');
        return !!(b && !b.classList.contains('hidden') && d.classList.contains('cg-read-mode') && b.offsetWidth > 0); })()`);
    chk('N13a 阅读步退出按钮可见', exitVisible === true, { exitVisible });
    await evalJs(`document.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape', bubbles:true})); 'ok'`, false);
    const escClosed = await waitFor(`document.getElementById('cgLessonDrawer').classList.contains('hidden')`, 5);
    chk('N13b Esc 退出全屏阅读', escClosed === true, { escClosed });
    await evalJs(`window.openLesson(${S.lid}); 'ok'`, false);
    const reOk = await waitFor(`!!document.querySelector('#cgMdBody .cg-anchor')`, 30);
    await evalJs(`var d = document.createElement('div'); d.id = 'cgEscFakeModal'; d.className = 'fixed inset-0 z-50 flex';
        document.body.appendChild(d); document.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape', bubbles:true})); 'ok'`, false);
    await sleep(400);
    const modalBlocks = await evalJs(`(function(){ var dr = document.getElementById('cgLessonDrawer');
        var kept = !dr.classList.contains('hidden') && dr.classList.contains('cg-read-mode');
        var fm = document.getElementById('cgEscFakeModal'); if (fm) fm.remove(); return kept; })()`);
    chk('N13c 弹层开着时 Esc 不退出抽屉（重进后验）', reOk === true && modalBlocks === true, { reOk, modalBlocks });
    await evalJs(`document.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape', bubbles:true})); 'ok'`, false);
    const escClosed2 = await waitFor(`document.getElementById('cgLessonDrawer').classList.contains('hidden')`, 5);
    chk('N13d 弹层关掉后 Esc 恢复退出', escClosed2 === true, { escClosed2 });

    ws.close();

    execFileSync('python', [path.join(DIR, '_cg_notes_clean.py'), String(S.uid)], { encoding: 'utf8' });
    console.log('CLEANED');
    console.log(fails === 0 ? 'RESULT: PASS' : 'RESULT: FAIL ' + fails);
    process.exit(fails === 0 ? 0 : 1);
})().catch(e => { console.error('ERR', e.message); process.exit(2); });
