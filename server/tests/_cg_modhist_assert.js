// 模块考历史 E2E 断言：交卷后成绩必须即时进「成绩」Tab（用户报障：模块考似乎没记录历史）
// 链路：注册测试用户 → seed(题包复制真实模块考包，免 LLM) → 页面点模块考 → 全选A交卷
//       → 关抽屉 → 成绩Tab断言行/得分/错题明细展开 → API 交叉核对 → 清理
// 用法：LL_SERVER=http://127.0.0.1:9992 node _cg_modhist_assert.js
const fs = require('fs');
const http = require('http');
const path = require('path');
const { execFileSync } = require('child_process');
module.paths.push('e:/LLM/LectureLearnLoop/desktop/node_modules');
const WebSocket = require('ws');
const BASE = process.env.LL_SERVER || 'http://127.0.0.1:5010';
const CDP = 'http://127.0.0.1:9333/json';
const DIR = 'e:/LLM/LectureLearnLoop/server/tests';
const SEEDJSON = path.join(DIR, '_cg_modhist_seed.json');
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
    const U = 'cgmod_' + Date.now().toString().slice(-6);
    const reg = await httpReq(BASE + '/api/auth/register', 'POST', { username: U, password: 'Pass1234' });
    if (!reg || !reg.success) throw new Error('register failed: ' + JSON.stringify(reg));
    const TOKEN = reg.data.token;
    execFileSync('python', [path.join(DIR, '_cg_modhist_seed.py'), U, SEEDJSON], { encoding: 'utf8' });
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
    const waitFor = async (expr, sec, label) => {
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
    for (let i = 0; i < 30; i++) { if (await evalJs("typeof window.openModuleExam === 'function'")) break; await sleep(1000); }

    // M0 地图视图自动选中唯一目标，模块考按钮在
    const m0 = await waitFor(`!!document.querySelector('.cg-map-exam[data-mid="${S.mid}"]')`, 30);
    chk('M0 课程地图模块考按钮渲染(mid=' + S.mid + ')', m0);
    if (!m0) { fs.writeFileSync(SEEDJSON + '.keep', JSON.stringify(S)); ws.close(); process.exit(1); }

    // 开考：GET 复用 seed 题包（不经 LLM）
    await evalJs(`window.openModuleExam(${S.mid}); 'ok'`, false);
    const m1 = await waitFor(`document.querySelectorAll('#cgDrawerBody input[type=radio]').length === ${S.n * 4}`, 60);
    chk('M1 模块考题挂载(题目 ' + S.n + ' 道)', m1, await evalJs(`({r: document.querySelectorAll('#cgDrawerBody input[type=radio]').length, h: document.getElementById('cgDrawerBody').innerText.slice(0,80)})`));

    // 全选 A 交卷
    await evalJs(`(function(){ for (var i = 0; i < ${S.n}; i++) { var el = document.querySelector('#cgDrawerBody input[name=cgq' + i + '][value="0"]'); el.click(); } return 'ok'; })()`);
    await evalJs(`document.querySelector('#cgDrawerBody #cgQuizSubmitBtn').click(); 'ok'`, false);
    const m2 = await waitFor(`(function(){ var b = document.getElementById('cgExamCloseBtn'); if (!b) return false; var t = document.querySelector('#cgDrawerBody .text-\\\\[28px\\\\]'); return t ? t.textContent : false; })()`, 60);
    const gotPct = m2 ? await evalJs(`(function(){ var t = document.querySelector('#cgDrawerBody .text-\\\\[28px\\\\]'); return t ? parseInt(t.textContent, 10) : -1; })()`) : -1;
    chk('M2 交卷判分结果屏得分=' + S.expect_score_pct + '%', gotPct === S.expect_score_pct, { gotPct });

    // 关抽屉 → 成绩 Tab：行必须即时出现
    await evalJs(`(function(){ var b = document.getElementById('cgExamCloseBtn'); if (b) b.click(); return 'ok'; })()`);
    await evalJs(`window.switchCgView('history'); 'ok'`, false);
    const m3 = await waitFor(`(function(){ var rows = document.querySelectorAll('#cgHistoryBox .cg-hist-row'); return rows.length >= 1 && rows[0].innerText.indexOf('模块考') >= 0; })()`, 30);
    const histTxt = await evalJs(`(document.getElementById('cgHistoryBox').innerText || '').slice(0, 200)`);
    chk('M3 成绩Tab出现模块考历史行', m3, histTxt);
    chk('M4 历史行含模块名与得分', histTxt.indexOf('断言模块甲') >= 0 && histTxt.indexOf(S.expect_score_pct + '%') >= 0, histTxt);

    // 展开错题明细（过程）
    await evalJs(`document.querySelector('#cgHistoryBox .cg-hist-row').click(); 'ok'`, false);
    await sleep(500);
    const det = await evalJs(`(function(){ var d = document.querySelector('#cgHistoryBox .cg-hist-detail'); if (!d) return null; var t = d.innerText; return { wrong: (t.match(/✗/g) || []).length, allCorrect: t.indexOf('全部答对') >= 0 }; })()`);
    const expWrongOk = S.expect_wrong > 0 ? (det && det.wrong === S.expect_wrong) : (det && det.allCorrect);
    chk('M5 展开明细错题数=' + S.expect_wrong, expWrongOk === true, { det, expect_wrong: S.expect_wrong });

    // API 交叉核对（与界面同源 course_attempts）
    const api = await httpReq(BASE + '/api/course/goals/' + S.gid + '/attempts', 'GET', null, TOKEN);
    const a0 = api && api.success && api.data.attempts[0];
    chk('M6 API attempts 含 moduleexam 行且明细完整',
        !!a0 && a0.kind === 'moduleexam' && a0.detail && a0.detail.per_question.length === S.n,
        { head: a0 && { kind: a0.kind, score: a0.score, n: a0.detail && a0.detail.per_question.length } });

    await sleep(300);
    const shot = await send('Page.captureScreenshot', { format: 'jpeg', quality: 75 });
    fs.writeFileSync('e:/LLM/LectureLearnLoop/design/walkthrough/course_mod_history.jpg', Buffer.from(shot.data, 'base64'));
    console.log('SHOT: design/walkthrough/course_mod_history.jpg user=' + U);
    ws.close();

    execFileSync('python', [path.join(DIR, '_cg_modhist_clean.py'), S.uid, String(S.tid)], { encoding: 'utf8' });
    console.log('CLEANED');
    console.log(fails === 0 ? 'RESULT: PASS' : 'RESULT: FAIL ' + fails);
    process.exit(fails === 0 ? 0 : 1);
})().catch(e => { console.error('ERR', e.message); process.exit(2); });
