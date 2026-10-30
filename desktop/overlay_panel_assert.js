/**
 * 悬浮窗体验改造端到端断言（2026-10-12，8 项需求逐一对账）。
 * 前提：后端 9992 已启动；electron 以 --remote-debugging-port=9224 启动（LL_SERVER 默认 127.0.0.1:9992）。
 * 用法：node overlay_panel_assert.js
 *
 * 覆盖：
 *  A1 标题栏录制计时   A2 总结倒计时   A3 间隔默认300+随时改下次生效
 *  A4 总结 MD 渲染链（离线本地库）    A5 未聚焦电平 RAF（后台节流修复）
 *  A6 音频设备切换自愈（模拟耳机插拔的 devicechange 面）
 *  A7 右下角把手 resize              A8 原生拖拽 CSS（越拖越宽根除）
 *  A9 完整录制收尾（笔记落盘）
 */
const http = require('http');
const WebSocket = require('ws');

const BASE = process.env.LL_SERVER || 'http://127.0.0.1:9992';
const CDP = 'http://127.0.0.1:9224/json';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function getJSON(url) {
  return new Promise((res, rej) => http.get(url, (r) => {
    let d = ''; r.on('data', (c) => (d += c)); r.on('end', () => { try { res(JSON.parse(d)); } catch (e) { rej(e); } });
  }).on('error', rej));
}

let failures = [];
function check(cond, name, detail) {
  console.log(`[${cond ? 'PASS' : 'FAIL'}] ${name}${detail ? '  ' + detail : ''}`);
  if (!cond) failures.push(name);
}

async function attach(matcher) {
  let page = null;
  for (let i = 0; i < 40 && !page; i++) {
    try {
      const targets = await getJSON(CDP);
      page = targets.find((t) => t.type === 'page' && matcher(t.url));
    } catch (e) { /* 未就绪 */ }
    if (!page) await sleep(500);
  }
  if (!page) throw new Error('no target for ' + matcher);
  const ws = new WebSocket(page.webSocketDebuggerUrl, { perMessageDeflate: false });
  await new Promise((res, rej) => { ws.on('open', res); ws.on('error', rej); });
  let id = 0;
  const send = (method, params) => new Promise((res, rej) => {
    const mid = ++id;
    const to = setTimeout(() => rej(new Error(method + ' timeout')), 25000);
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
  return { url: page.url, targetId: page.id, evalJs, send, close: () => ws.close() };
}

(async () => {
  // 0) 注册独立测试用户（登录即送每日积分，可真实调 ASR/LLM），token 写主窗口 localStorage
  const user = 'ovl_user_' + Date.now().toString().slice(-6);
  const pwd = 'Ovl12345!';
  const jf = async (p, opts, token) => {
    const headers = { 'Content-Type': 'application/json' };
    if (token) headers.Authorization = 'Bearer ' + token;
    const r = await fetch(BASE + p, Object.assign({}, opts, { headers }));
    return r.json().catch(() => ({}));
  };
  let reg = await jf('/api/auth/register', { method: 'POST', body: JSON.stringify({ username: user, password: pwd }) });
  // 业务规则（探针实锤）：注册用户 balance=0，登录才触发每日赠送 100，/api/asr/config 拒发无分账号 → 必须显式 login
  const lg = await jf('/api/auth/login', { method: 'POST', body: JSON.stringify({ username: user, password: pwd }) });
  let TOKEN = (lg && lg.data && lg.data.token) || (reg && reg.data && reg.data.token);
  check(!!TOKEN, '测试用户登录获得 token');
  if (!TOKEN) return finish();

  const main = await attach((u) => u.startsWith(BASE) && !/note-picker|overlay|capture/.test(u));
  await main.evalJs(`localStorage.setItem('ll_token', ${JSON.stringify(TOKEN)}); 'seeded'`);

  // 1) 打开悬浮窗（全新实例：清掉上次保存的间隔，验证默认 300）
  await main.evalJs(`localStorage.removeItem('ll_sum_interval'); 'x'`);
  await main.evalJs(`window.llShell.openOverlay()`);
  const ov = await attach((u) => /\/overlay/.test(u));
  await sleep(1500);

  // A3a 间隔默认 300
  const ivVal = await ov.evalJs(`document.getElementById('interval').value`);
  check(ivVal === '300', 'A3 段落总结间隔默认 300 秒', 'input=' + ivVal);

  // A8 原生拖拽就位（越拖越宽的根除方案：JS 逐帧 setPosition 全删）
  const dragCss = await ov.evalJs(`JSON.stringify({ bar: getComputedStyle(document.getElementById('dragbar')).webkitAppDrag || getComputedStyle(document.getElementById('dragbar')).getPropertyValue('-webkit-app-region'), btns: getComputedStyle(document.querySelector('#dragbar .btns')).getPropertyValue('-webkit-app-region'), oldDragFn: typeof window.llOverlayDrag })`);
  const dc = JSON.parse(dragCss);
  check(dc.bar === 'drag' && dc.btns === 'no-drag' && dc.oldDragFn === 'undefined', 'A8 标题栏原生拖拽 / 按钮 no-drag / 旧拖拽桥已移除', dragCss);

  // A4 MD 渲染链：页面离线库真实组合一遍（总结展示所走的同一管线）
  const mdOut = await ov.evalJs(`(() => {
    if (!window.marked || !window.DOMPurify || !window.MdRender) return 'LIB_MISSING';
    const md = '小测\\n- 要点**重点**\\n- 公式 $x^2+y^2$';
    const ex = MdRender.extract(md);
    const host = document.createElement('div');
    document.body.appendChild(host);  // 与生产 appendSummaryView 同构：先挂进文档再渲染（applyMath 的 isConnected 守卫会跳过分离节点）
    host.innerHTML = DOMPurify.sanitize(marked.parse(ex.text));
    MdRender.applyMath(host, ex.slots);
    const r = JSON.stringify({ strong: !!host.querySelector('strong'), li: host.querySelectorAll('li').length, katex: !!host.querySelector('.katex'), noPh: host.textContent.indexOf('\\uE000') < 0 });
    host.remove();
    return r;
  })()`);
  const mdo = mdOut === 'LIB_MISSING' ? {} : JSON.parse(mdOut);
  check(mdOut !== 'LIB_MISSING' && mdo.strong && mdo.li === 2 && mdo.katex && mdo.noPh, 'A4 总结 MD 渲染链（列表/加粗/公式/占位符回收）', mdOut);

  // A7 resize 把手（不需要录制态）
  await ov.evalJs(`window.llOverlayResize(520, 700)`, false);
  await sleep(700);
  const sizeNow = await ov.evalJs(`document.documentElement.clientWidth + 'x' + document.documentElement.clientHeight`);
  const [cw, chh] = sizeNow.split('x').map(Number);
  check(Math.abs(cw - 520) <= 6 && Math.abs(chh - 700) <= 6, 'A7 把手改窗口尺寸生效（内容区随 setSize 变化）', sizeNow);

  // 2) 真实录音链路：开始 → 选择窗回传新笔记 → 引擎 recording
  await ov.evalJs(`document.getElementById('btnStart').click()`, false);
  const picker = await attach((u) => /\/note-picker/.test(u));
  await sleep(1200);
  const noteName = await picker.evalJs(`(async () => {
    const r = await fetch('/api/vault/note', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + window.llAuth.getToken() }, body: JSON.stringify({ folder_path: 'vault' }) });
    const j = await r.json();
    const nm = j && j.data; if (!nm) return '';
    window.llNotePickerSel.choose({ action: 'open', path: 'vault/' + nm, name: nm });
    return nm;
  })()`);
  check(!!noteName, '选择窗已回传新建笔记', noteName);

  // 等待进入 recording（getDisplayMedia 免弹框自动接回 + ASR 会话建立）
  let st = '';
  for (let i = 0; i < 30 && st !== 'recording'; i++) { await sleep(500); st = await ov.evalJs(`document.getElementById('status').textContent`); }
  const stateNow = await ov.evalJs(`document.getElementById('btnPause').disabled ? 'notrec' : 'rec'`);
  check(stateNow === 'rec', '录音已真实启动（暂停按钮已点亮）', 'status=' + st);

  // A1 录制计时：读两次，秒数应增长且格式正确
  const c1 = await ov.evalJs(`document.getElementById('recClock').textContent`);
  await sleep(2300);
  const c2 = await ov.evalJs(`document.getElementById('recClock').textContent`);
  const secOf = (s) => { const m = s.match(/(\d+):(\d\d)/); return m ? Number(m[1]) * 60 + Number(m[2]) : -1; };
  check(/\d+:\d\d/.test(c2) && secOf(c2) > secOf(c1), 'A1 标题栏录制计时在走', c1 + ' -> ' + c2);

  // A2 倒计时显示 + A3b 随时改间隔（下一次轮询按新值）
  const cd1 = await ov.evalJs(`document.getElementById('sumCd').textContent`);
  check(/下次\s+\d+:\d\d/.test(cd1), 'A2 距下次总结倒计时显示', cd1);
  await ov.evalJs(`(() => { const el = document.getElementById('interval'); el.value = '30'; el.dispatchEvent(new Event('change')); return 1; })()`);
  await sleep(1400);  // 等一个完整 UI 心跳拍（每秒刷新倒计时），避免读新值前的竞态
  const cd2 = await ov.evalJs(`document.getElementById('sumCd').textContent`);
  check(/下次\s+0:\d\d/.test(cd2), 'A3 改间隔 30 秒后立即按新值重排（倒计时变 0:xx）', cd1 + ' -> ' + cd2);

  // A5 电平 RAF：切焦点到主窗（悬浮窗失焦），1.2 秒内 RAF 帧数应 > 8（后台节流修复前 ≈0~1）
  await main.send('Target.activateTarget', { targetId: main.targetId });
  await sleep(400);
  const rafN = await ov.evalJs(`new Promise((res) => { let n = 0; const t0 = performance.now(); (function loop() { n++; if (performance.now() - t0 < 1200) requestAnimationFrame(loop); else res(n); })(); })`);
  check(rafN > 8, 'A5 悬浮窗失焦时电平动画仍持续（后台节流已关）', 'frames=' + rafN);

  // A6 模拟输出设备切换（耳机插拔的 devicechange 面）：自愈重取，且不打断录音
  await ov.evalJs(`navigator.mediaDevices.dispatchEvent(new Event('devicechange'))`, false);
  let recap = '';
  for (let i = 0; i < 24; i++) {
    await sleep(500);
    recap = await ov.evalJs(`document.getElementById('status').textContent`);
    if (/重新接回/.test(recap)) break;
    // 若落到“需用户手势”降级分支：模拟点一下悬浮窗
    if (/点一下悬浮窗/.test(await ov.evalJs(`document.getElementById('toast').textContent`))) {
      await ov.evalJs(`document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }))`, false);
    }
  }
  const stAfter = await ov.evalJs(`document.getElementById('btnPause').disabled ? 'notrec' : 'rec'`);
  check(/系统声音已重新接回/.test(recap) && stAfter === 'rec', 'A6 设备切换后系统声音自愈且录音不中断', recap);

  // 9) 收尾：完成 → 笔记落盘
  await ov.evalJs(`document.getElementById('btnDone').click()`, false);
  await sleep(4000);
  const idle = await ov.evalJs(`document.getElementById('btnStart').disabled === false`);
  check(idle === true, 'A9 完成后回到就绪态');
  const noteBody = await jf('/api/notes/content?path=' + encodeURIComponent('vault/' + noteName), {}, TOKEN);
  const content = (noteBody && noteBody.data && noteBody.data.content) || '';
  check(/# 听课笔记/.test(content), 'A9 笔记已实时落盘', 'len=' + content.length);

  ov.close(); picker.close(); main.close();
  finish();
})().catch((e) => { console.log('SCRIPT ERROR:', e.stack || e.message); failures.push('script'); finish(); });

function finish() {
  console.log(failures.length ? ('FAILED: ' + failures.join(' | ')) : 'ALL PASS');
  process.exit(failures.length ? 1 : 0);
}
