// 课文图文结合 E2E 断言（2026-11-12 A 方案）：正文 mermaid 出图 + 坏图降级 + 公式共存 + 两展示位
// 链路：注册测试用户 → seed(课文含 2 合法图块+1 坏图块+公式；预置 principle 产物) →
//       openLesson 进阅读步 → DOM 断言 SVG/降级/KaTeX/iframe 直显/生成按钮 → 清理
// 零真实 LLM：不调用任何生成按钮。用法：LL_SERVER=http://127.0.0.1:9992 node _cg_visual_assert.js
const fs = require('fs');
const http = require('http');
const path = require('path');
const { execFileSync } = require('child_process');
module.paths.push('e:/LLM/LectureLearnLoop/desktop/node_modules');
const WebSocket = require('ws');
const BASE = process.env.LL_SERVER || 'http://127.0.0.1:5010';
const CDP = 'http://127.0.0.1:9333/json';
const DIR = 'e:/LLM/LectureLearnLoop/server/tests';
const SEEDJSON = path.join(DIR, '_cg_visual_seed.json');
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
    const U = 'cgvis_' + Date.now().toString().slice(-6);
    const reg = await httpReq(BASE + '/api/auth/register', 'POST', { username: U, password: 'Pass1234' });
    if (!reg || !reg.success) throw new Error('register failed: ' + JSON.stringify(reg));
    const TOKEN = reg.data.token;
    execFileSync('python', [path.join(DIR, '_cg_visual_seed.py'), U, SEEDJSON], { encoding: 'utf8' });
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

    // 进课文阅读步（content_ready 直读，不经前测/生成）
    await evalJs(`window.openLesson(${S.lid}); 'ok'`, false);
    const v0 = await waitFor(`!!document.getElementById('cgMdBody') && document.getElementById('cgMdBody').innerText.indexOf('梯度下降') >= 0`, 30);
    chk('V0 课文正文挂载', v0);
    if (!v0) { fs.writeFileSync(SEEDJSON + '.keep', JSON.stringify(S)); ws.close(); process.exit(1); }

    // V1 合法 mermaid 块 → SVG（异步渲染，留 20s）
    const v1 = await waitFor(`document.querySelectorAll('#cgMdBody .cg-mm svg').length >= 2`, 40);
    chk('V1 正文 mermaid 出 SVG ≥2', v1, await evalJs(`({mm: document.querySelectorAll('#cgMdBody .cg-mm').length, svg: document.querySelectorAll('#cgMdBody .cg-mm svg').length})`));

    // V2 坏语法块降级：保留原代码块，不炸整篇
    const v2 = await evalJs(`(function(){ var p = document.querySelector('#cgMdBody pre[data-mm-fail="1"]'); return p && p.textContent.indexOf('BADGRAPH') >= 0; })()`);
    chk('V2 坏图块降级保留原文', v2 === true);

    // V3 公式管线正常（KaTeX 回填不受图块影响）
    const v3 = await evalJs(`document.querySelectorAll('#cgMdBody .katex').length`);
    chk('V3 KaTeX 公式渲染数≥2', v3 >= 2, { v3 });

    // V4 图块不被公式管线咬坏：SVG 节点文字保留课文术语
    const v4 = await evalJs(`(function(){ var s = document.querySelector('#cgMdBody .cg-mm svg'); if (!s) return false; var t = (s.textContent || '') + (s.innerHTML || ''); return t.indexOf('损失') >= 0 || t.indexOf('输入') >= 0 || t.indexOf('Loss') >= 0; })()`);
    chk('V4 SVG 节点文字完好（未被公式管线咬坏）', v4 === true);

    // V5 两个展示位常驻
    const v5 = await waitFor(`document.querySelectorAll('#cgVisualBar .cg-vis-card').length === 2`, 20);
    chk('V5 原理图/实验两个展示位渲染', v5);

    // V6 principle 已有产物 → 进页直显 iframe（srcdoc 哨兵）
    const v6 = await waitFor(`(function(){ var f = document.querySelector('#cgVisualBar iframe'); return !!f && (f.getAttribute('srcdoc')||'').indexOf('SENTINEL_VIS_PRINCIPLE') >= 0; })()`, 20);
    chk('V6 原理图产物进页直显（sandbox iframe srcdoc）', v6);
    const v6b = await evalJs(`(function(){ var f = document.querySelector('#cgVisualBar iframe'); return f ? f.getAttribute('sandbox') : null; })()`);
    chk('V6b iframe sandbox=allow-scripts（黑板同口径）', v6b === 'allow-scripts', { v6b });

    // V7 lab 无产物 → 展示生成按钮（不点击，零 LLM）
    const v7 = await evalJs(`!!document.querySelector('#cgVisualBar .cg-vis-go[data-kind="lab"]')`);
    chk('V7 实验展示位显示生成按钮', v7 === true);
    const v7b = await evalJs(`document.getElementById('cgVisualBar').innerText.indexOf('课文正文生成后') < 0`);
    chk('V7b has_content=true 不误显示缺正文提示', v7b === true);

    await sleep(300);
    const shot = await send('Page.captureScreenshot', { format: 'jpeg', quality: 75 });
    fs.writeFileSync('e:/LLM/LectureLearnLoop/design/walkthrough/course_visual_inline.jpg', Buffer.from(shot.data, 'base64'));
    console.log('SHOT: design/walkthrough/course_visual_inline.jpg user=' + U);
    ws.close();

    execFileSync('python', [path.join(DIR, '_cg_visual_clean.py'), String(S.uid)], { encoding: 'utf8' });
    console.log('CLEANED');
    console.log(fails === 0 ? 'RESULT: PASS' : 'RESULT: FAIL ' + fails);
    process.exit(fails === 0 ? 0 : 1);
})().catch(e => { console.error('ERR', e.message); process.exit(2); });
