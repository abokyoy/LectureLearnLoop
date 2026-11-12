// 题包提示与我不会 E2E 断言（2026-11-12）：查看提示隐藏区 + value=-1 我不会 + 提交透传
// 链路：注册测试用户 → seed(灌含 hint 的 pretest 题包，2 有 1 无) → openLesson 进前测 →
//       DOM 断言按钮数/展开文本/无 hint 降级/我不会 radio → mock cgPost 捕获 answers 含 -1 → 清理
// 零真实 LLM：题包 seed 直灌复用；交卷走 mock 不真提交。用法：LL_SERVER=http://127.0.0.1:9992 node _cg_hint_assert.js
const fs = require('fs');
const http = require('http');
const path = require('path');
const { execFileSync } = require('child_process');
module.paths.push('e:/LLM/LectureLearnLoop/desktop/node_modules');
const WebSocket = require('ws');
const BASE = process.env.LL_SERVER || 'http://127.0.0.1:5010';
const CDP = 'http://127.0.0.1:9333/json';
const DIR = 'e:/LLM/LectureLearnLoop/server/tests';
const SEEDJSON = path.join(DIR, '_cg_hint_seed.json');
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
    const U = 'cghint_' + Date.now().toString().slice(-6);
    const reg = await httpReq(BASE + '/api/auth/register', 'POST', { username: U, password: 'Pass1234' });
    if (!reg || !reg.success) throw new Error('register failed: ' + JSON.stringify(reg));
    const TOKEN = reg.data.token;
    execFileSync('python', [path.join(DIR, '_cg_hint_seed.py'), U, SEEDJSON], { encoding: 'utf8' });
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

    // 进前测步（seed 题包复用，零 LLM）
    await evalJs(`window.openLesson(${S.lid}); 'ok'`, false);
    const v0 = await waitFor(`document.querySelectorAll('#cgDrawerBody .cg-quiz-q').length === 3`, 30);
    chk('H0 前测题包挂载（3 题）', v0);
    if (!v0) { fs.writeFileSync(SEEDJSON + '.keep', JSON.stringify(S)); ws.close(); process.exit(1); }

    // H1 「查看提示」按钮数=2（q0/q1 有 hint；q2 旧契约无 hint 静默不渲染）
    const h1 = await evalJs(`document.querySelectorAll('#cgDrawerBody .cg-hint-toggle').length`);
    chk('H1 查看提示按钮数=2（无 hint 题不渲染）', h1 === 2, { h1 });
    const h1b = await evalJs(`!!document.querySelectorAll('#cgDrawerBody .cg-quiz-q')[2].querySelector('.cg-hint-toggle') === false`);
    chk('H1b 第 3 题（无 hint）不含按钮', h1b === true);

    // H2 初始收起 + 点击展开可见哨兵文本（走 cgMdSpan/cgHydrateMath 管线）+ 按钮文案切换
    const h2a = await evalJs(`document.querySelector('#cgDrawerBody .cg-hint-body').offsetParent === null`);
    chk('H2a 提示区初始收起', h2a === true);
    await evalJs(`document.querySelector('#cgDrawerBody .cg-hint-toggle').click(); 'ok'`, false);
    await sleep(400);
    const h2b = await evalJs(`(function(){ var b = document.querySelector('#cgDrawerBody .cg-hint-body'); return b.offsetParent !== null && b.innerText.indexOf('HINTSENTINEL0') >= 0 && b.innerText.indexOf('梯度') >= 0; })()`);
    chk('H2b 展开后哨兵文本可见', h2b === true);
    const h2c = await evalJs(`document.querySelector('#cgDrawerBody .cg-hint-toggle span').textContent`);
    chk('H2c 按钮文案切为「收起提示」', h2c === '收起提示', { h2c });
    await evalJs(`document.querySelector('#cgDrawerBody .cg-hint-toggle').click(); 'ok'`, false);
    await sleep(300);
    const h2d = await evalJs(`document.querySelector('#cgDrawerBody .cg-hint-body').offsetParent === null`);
    chk('H2d 再点收起', h2d === true);

    // H3 题干公式管线不受影响（q0 题干 $x^2$ 应出 KaTeX）
    const h3 = await evalJs(`document.querySelectorAll('#cgDrawerBody .cg-quiz-q .katex').length`);
    chk('H3 题干 KaTeX 渲染≥1', h3 >= 1, { h3 });

    // H4 「我不会」radio：三题全在、value=-1、同组 name 与选项互斥
    const h4 = await evalJs(`(function(){ var rs = document.querySelectorAll('#cgDrawerBody .cg-dontknow input[type=radio]'); if (rs.length !== 3) return { n: rs.length }; var okv = true, names = {}; for (var i = 0; i < rs.length; i++) { if (rs[i].value !== '-1') okv = false; names[rs[i].name] = 1; } return { okv: okv, groups: Object.keys(names).length }; })()`);
    chk('H4 我不会 radio ×3 且 value=-1 按题分组', h4 && h4.okv === true && h4.groups === 3, { h4 });

    // H5 mock cgPost 捕获交卷 answers（不真提交，零判分/积分消耗）
    await evalJs(`window.__cap = null; window.__cgPostReal = window.cgPost;
        window.cgPost = function (u, b) { if (u.indexOf('/pretest') >= 0) { window.__cap = { u: u, b: b }; return new Promise(function () {}); } return window.__cgPostReal(u, b); }; 'ok'`, false);
    await evalJs(`(function(){
        document.querySelector('.cg-quiz-q input[value="-1"]').click();
        var qs = document.querySelectorAll('#cgDrawerBody .cg-quiz-q');
        qs[1].querySelector('input[value="0"]').click();
        qs[2].querySelector('input[value="-1"]').click();
        document.getElementById('cgQuizSubmitBtn').click(); return 'ok';
    })()`, false);
    await sleep(600);
    const cap = await evalJs(`window.__cap && window.__cap.b.answers`);
    chk('H5 交卷透传 answers=[-1,0,-1]（我不会计入已答）', cap && cap.join(',') === '-1,0,-1', { cap });
    // 未答拦截仍生效：submitPretest 已重写 drawer（按钮销毁），重进前测拿全新未选实例再交，不发请求
    await evalJs(`window.__cap = null; window.openLesson(${S.lid}); 'ok'`, false);
    const re = await waitFor(`!!document.getElementById('cgQuizSubmitBtn')`, 20);
    chk('H6a 重新进前测渲染就绪', re === true);
    await evalJs(`document.getElementById('cgQuizSubmitBtn').click(); 'ok'`, false);
    await sleep(400);
    const h6 = await evalJs(`window.__cap === null && document.querySelector('#cgDrawerBody .cg-quiz-hint').textContent.indexOf('还未作答') >= 0`);
    chk('H6 全清空提交仍被「还未作答」拦截', h6 === true);

    await sleep(300);
    const shot = await send('Page.captureScreenshot', { format: 'jpeg', quality: 75 });
    fs.writeFileSync('e:/LLM/LectureLearnLoop/design/walkthrough/course_hint_dontknow.jpg', Buffer.from(shot.data, 'base64'));
    console.log('SHOT: design/walkthrough/course_hint_dontknow.jpg user=' + U);
    ws.close();

    execFileSync('python', [path.join(DIR, '_cg_hint_clean.py'), String(S.uid)], { encoding: 'utf8' });
    console.log('CLEANED');
    console.log(fails === 0 ? 'RESULT: PASS' : 'RESULT: FAIL ' + fails);
    process.exit(fails === 0 ? 0 : 1);
})().catch(e => { console.error('ERR', e.message); process.exit(2); });
