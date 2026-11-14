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
                 svg: s.querySelectorAll('.cg-note-a svg').length,
                 kx: s.querySelectorAll('.cg-note-a .katex').length, bare: s.innerText.indexOf('$2e_i$') >= 0 }; })()`);
    chk('N4 淡黄虚线章节+问答+思路图', n4 && n4.border === 'dashed' && n4.q === true && n4.a === true && n4.svg >= 1, { n4 });
    // N4a 数字开头公式渲染回归守卫（实弹轮 2026-11-13：$2e_i$ 被旧货币防误判规则整批丢弃裸显）
    chk('N4a 回答内 $2e_i$ 已 KaTeX 渲染且不裸显', !!n4 && n4.kx >= 1 && n4.bare === false, { n4 });

    // N4b 列表锚定回归守卫（完全展开轮 2026-11-13 实弹：锚句在列表第2项，笔记曾被推到整张 ul 末尾）：
    //     章节组必须紧跟在带锚 li 之后（同一 ul 内），而非列表尾部
    const n4b = await evalJs(`(function(){ var a = document.querySelector('#cgMdBody .cg-anchor');
        if (!a) return null; var li = a.closest('li'); if (!li) return 'no-li';
        var sib = li.nextElementSibling;
        return !!(sib && sib.classList.contains('cg-anchor-group') && sib.querySelector('.cg-read-note')); })()`);
    chk('N4b 笔记紧跟带锚列表项（非整表末尾）', n4b === true, { n4b });

    // N5 追问的追问落位（九追 2026-11-13）：n2 锚「步长」必须落在父回答该段之后（非节末堆叠）
    const n5 = await evalJs(`(function(){ var sec = document.querySelector('.cg-read-note[data-note-id="${S.n1}"]');
        if (!sec) return null; var aEl = sec.querySelector(':scope > .cg-note-a');
        var kidsSec = sec.querySelector(':scope > .cg-note-kids');
        var inKids = !!(kidsSec && kidsSec.querySelector('.cg-note[data-note-id="${S.n2}"]'));
        var e2 = aEl.querySelector('.cg-note[data-note-id="${S.n2}"]');
        if (!e2) return { mark: false, inKids: inKids };
        var grp = e2.closest('.cg-anchor-group') || e2.parentElement;
        var ln = grp.previousElementSibling;
        while (ln && !(ln.querySelector && ln.querySelector('.cg-anchor'))) { ln = ln.previousElementSibling; }
        var afterLine = !!(ln && ln.querySelector('.cg-anchor') && ln.textContent.indexOf('步长') >= 0);
        return { mark: true, inKids: inKids, afterLine: afterLine, lineHas: afterLine,
                 sent: !!(grp.innerText.indexOf('Q2SENTINEL') >= 0 && grp.innerText.indexOf('ANSWER2SENTINEL') >= 0) }; })()`);
    chk('N5 子追问落父回答锚段之后（非节末）', !!n5 && n5.mark === true && n5.inKids === false && n5.afterLine === true && n5.lineHas === true && n5.sent === true, { n5 });

    // N5b 子锚不中降级：n2b 落父节末尾 .cg-note-kids，内容不丢（九追）
    const n5b = await evalJs(`(function(){ var k = document.querySelector('.cg-read-note[data-note-id="${S.n1}"] .cg-note-kids .cg-note[data-note-id="${S.n2b}"]');
        return !!k && k.innerText.indexOf('Q2BSENTINEL') >= 0 && k.innerText.indexOf('ANSWER2BSENTINEL') >= 0; })()`);
    chk('N5b 子锚不中降级节末 kids 内容不丢', n5b === true, { n5b });

    // N5c 选区噪声锚归一（九追二 2026-11-13 镜像铁证：KaTeX 堆叠/表格选区入库带换行/零宽字符，
    // 原样拼接永不命中全沉节末）：同一段文本夹带噪声，去空白归一后仍须落父回答锚段之后
    const n5c = await evalJs(`(function(){ var sec = document.querySelector('.cg-read-note[data-note-id="${S.n1}"]');
        var aEl = sec.querySelector(':scope > .cg-note-a');
        var kidsSec = sec.querySelector(':scope > .cg-note-kids');
        var c = aEl.querySelector(':scope .cg-note[data-note-id="${S.n2c}"]');
        if (!c || kidsSec.contains(c)) return { ok: false };
        var grp = c.closest('.cg-anchor-group');
        var prev = grp ? grp.previousElementSibling : null; // 同段两组：建序 n2 在前（跨链追加不反序）
        return { ok: true, sent: c.innerText.indexOf('Q2CSENTINEL') >= 0 && c.innerText.indexOf('ANSWER2CSENTINEL') >= 0,
                 afterN2: !!(prev && prev.querySelector('.cg-note[data-note-id="${S.n2}"]')) }; })()`);
    chk('N5c 噪声锚去空白归一后仍落父回答内', !!n5c && n5c.ok === true && n5c.sent === true, { n5c });
    chk('N5d 同段两子组保持建序（n2 在前 n2c 紧随）', !!n5c && n5c.afterN2 === true, { n5c });

    // N5e/N5e2 表格内锚落位（用户裁定 2026-11-13：表格里的追问也必须贴在那一行下面，
    // 行内插块级节点会碎版，折中为紧跟整张表，绝不沉节末）；锚文本还夹带制表符+零宽，
    // 同时验证去空白归一在表格选区场景生效
    const n5e = await evalJs(`(function(){ var sec = document.querySelector('.cg-read-note[data-note-id="${S.n1}"]');
        var aEl = sec.querySelector(':scope > .cg-note-a');
        var kidsSec = sec.querySelector(':scope > .cg-note-kids');
        var d = aEl.querySelector(':scope .cg-note[data-note-id="${S.n2d}"]');
        if (!d || kidsSec.contains(d)) return { ok: false };
        var grp = d.closest('.cg-anchor-group');
        var prev = grp ? grp.previousElementSibling : null;
        return { ok: true, sent: d.innerText.indexOf('Q2DSENTINEL') >= 0 && d.innerText.indexOf('ANSWER2DSENTINEL') >= 0,
                 afterTable: !!(prev && prev.tagName === 'TABLE' && prev.innerText.indexOf('动量项') >= 0) }; })()`);
    chk('N5e 表格内锚落父回答内（不沉节末）', !!n5e && n5e.ok === true && n5e.sent === true, { n5e });
    chk('N5e2 表格追问紧跟整张表之后', !!n5e && n5e.afterTable === true, { n5e });
    
        // N5f 公式源码态锚（十追镜像铁证：真实笔记 3659 锚里 $2e_i$ 是框选时的 md 源码字面，
        // DOM 已渲染成符号；SKIP 把 $ ^ _ \ {} 与空白同视为透明后必须一次命中，落父回答内）
        const n5f = await evalJs(`(function(){ var sec = document.querySelector('.cg-read-note[data-note-id="${S.n1}"]');
            var aEl = sec.querySelector(':scope > .cg-note-a');
            var kidsSec = sec.querySelector(':scope > .cg-note-kids');
            var e = aEl.querySelector(':scope .cg-note[data-note-id="${S.n2e}"]');
            if (!e || kidsSec.contains(e)) return { ok: false };
            var grp = e.closest('.cg-anchor-group');
            var prev = grp ? grp.previousElementSibling : null;
            // 锚标记在宿主行内（源码态 $2e_i$ 归一后命中的是渲染态文本，标记文字无 $ _）
            return { ok: true, sent: e.innerText.indexOf('Q2ESENTINEL') >= 0 && e.innerText.indexOf('ANSWER2ESENTINEL') >= 0,
                     marked: !!(prev && prev.querySelector && prev.querySelector('.cg-anchor') && prev.textContent.indexOf('残差导数项') >= 0) }; })()`);
        chk('N5f 源码态公式锚归一命中落父回答内', !!n5f && n5f.ok === true && n5f.sent === true && n5f.marked === true, { n5f });

    // N5g 命令词锈锚最长前缀兜底（镜像铁证 3659：`\hat` 渲染态不产生字母，整段永远对不上；
    // 兜底前缀≥40 归一字且唯一命中 → 包裹前缀、落宿主段后，绝不沉节末）
    const n5g = await evalJs(`(function(){ var sec = document.querySelector('.cg-read-note[data-note-id="${S.n1}"]');
        var aEl = sec.querySelector(':scope > .cg-note-a');
        var kidsSec = sec.querySelector(':scope > .cg-note-kids');
        var f = aEl.querySelector(':scope .cg-note[data-note-id="${S.n2f}"]');
        if (!f || kidsSec.contains(f)) return { ok: false };
        var grp = f.closest('.cg-anchor-group');
        var prev = grp ? grp.previousElementSibling : null;
        return { ok: true, sent: f.innerText.indexOf('Q2FSENTINEL') >= 0 && f.innerText.indexOf('ANSWER2FSENTINEL') >= 0,
                 marked: !!(prev && prev.querySelector && prev.querySelector('.cg-anchor') && prev.textContent.indexOf('链式法则不可省略') >= 0) }; })()`);
        chk('N5g 命令词锈锚最长前缀兜底落父回答内', !!n5g && n5g.ok === true && n5g.sent === true && n5g.marked === true, { n5g });

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

    // N14 mermaid sanitizer（本轮实弹：用户真图 subgraph 裸标题带全角括号 → Lexical error 降级回显源码）：
    // 原始源码应渲染失败；cgMmSanitize 改写后能出图；存量笔记免重生成直接可看
    const mmFix = await evalJs(`(function(){
        if (typeof cgMmSanitize !== 'function' || typeof cgMmEnsure !== 'function') return { missing: true };
        var raw = 'graph LR\\n    subgraph 凸损失面（MSE 就是这种）\\n    B1["只有一个全局碗底"]\\n    end';
        var s = cgMmSanitize(raw);
        var changed = s !== raw && s.indexOf('subgraph sgU1["凸损失面（MSE 就是这种）"]') >= 0;
        cgMmEnsure();
        return Promise.all([
            mermaid.render('cdn14bad' + Date.now(), raw).then(function(){ return true; }).catch(function(){ return false; }),
            mermaid.render('cdn14ok' + Date.now(), s).then(function(o){ return !!(o && o.svg && o.svg.length > 100); }).catch(function(){ return false; })
        ]).then(function(rs){ return { changed: changed, rawOk: rs[0], sanOk: rs[1] }; });
    })()`);
    chk('N14 sanitizer：裸标题括号图纠偏后可出图', mmFix && mmFix.changed === true && mmFix.rawOk === false && mmFix.sanOk === true, mmFix);

    ws.close();

    execFileSync('python', [path.join(DIR, '_cg_notes_clean.py'), String(S.uid)], { encoding: 'utf8' });
    console.log('CLEANED');
    console.log(fails === 0 ? 'RESULT: PASS' : 'RESULT: FAIL ' + fails);
    process.exit(fails === 0 ? 0 : 1);
})().catch(e => { console.error('ERR', e.message); process.exit(2); });
