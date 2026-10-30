/**
 * 安全上下文断言（客户机报错回归：'Cannot read properties of undefined (reading getDisplayMedia)'）。
 * 机制：Chromium 只在安全上下文暴露 navigator.mediaDevices；http://域名:端口 是非安全地址 → undefined。
 * 验证手法：用本机局域网 IP（http 非回环）加载页面复现客户机条件；修复后应恢复。
 * 用法：node media_origin_assert.js <baseUrl> <repro|fixed>
 *   repro  = 断言未修复版 mediaDevices 为 undefined（证明根因机制成立，跑旧包）
 *   fixed  = 断言修复版 mediaDevices 可用（跑新代码）
 * 前提：electron 已以 --remote-debugging-port=9222 启动并连 <baseUrl>。
 */
const http = require('http');
const WebSocket = require('ws');

const BASE = process.argv[2] || 'http://192.168.0.113:9992';
const MODE = process.argv[3] || 'fixed';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function getJSON(url) {
  return new Promise((res, rej) => http.get(url, (r) => {
    let d = ''; r.on('data', (c) => (d += c)); r.on('end', () => { try { res(JSON.parse(d)); } catch (e) { rej(e); } });
  }).on('error', rej));
}

async function attach(matcher) {
  let page = null;
  for (let i = 0; i < 40 && !page; i++) {
    try {
      const targets = await getJSON('http://127.0.0.1:9222/json');
      page = targets.find((t) => t.type === 'page' && matcher(t.url));
    } catch (e) { /* 未就绪 */ }
    if (!page) await sleep(500);
  }
  if (!page) throw new Error('no target');
  const ws = new WebSocket(page.webSocketDebuggerUrl, { perMessageDeflate: false });
  await new Promise((res, rej) => { ws.on('open', res); ws.on('error', rej); });
  let id = 0;
  const send = (method, params) => new Promise((res, rej) => {
    const mid = ++id;
    const to = setTimeout(() => rej(new Error(method + ' timeout')), 20000);
    const onMsg = (raw) => {
      const m = JSON.parse(raw);
      if (m.id === mid) { ws.off('message', onMsg); clearTimeout(to); m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result); }
    };
    ws.on('message', onMsg);
    ws.send(JSON.stringify({ id: mid, method, params: params || {} }));
  });
  await send('Page.enable');
  const evalJs = async (expression) => {
    const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error('page exception: ' + JSON.stringify(r.exceptionDetails.exception && r.exceptionDetails.exception.description || r.exceptionDetails.text));
    return r.result.value;
  };
  return { url: page.url, evalJs, close: () => ws.close() };
}

(async () => {
  console.log('MODE=' + MODE + ' BASE=' + BASE);
  const main = await attach((u) => u.indexOf(BASE) === 0 && !/note-picker|overlay|capture/.test(u));
  // 页内探测：mediaDevices 存在性 + getDisplayMedia 实际取流（主进程 handler 自动喂屏幕+loopback，无需手势）
  const probeExpr = `(async () => {
    const md = typeof navigator.mediaDevices;
    let gdm = 'n/a', rec = 'n/a';
    if (md !== 'undefined') {
      gdm = typeof navigator.mediaDevices.getDisplayMedia;
      if (gdm === 'function') {
        try {
          const st = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
          rec = 'tracks=' + st.getTracks().length;
          st.getTracks().forEach((t) => t.stop());
        } catch (e) { rec = 'ERR:' + e.name; }
      }
    }
    return JSON.stringify({ md, gdm, rec, isSecure: window.isSecureContext });
  })()`;
  const onMain = JSON.parse(await main.evalJs(probeExpr));
  await main.evalJs(`window.llShell.openOverlay()`);
  const ov = await attach((u) => /\/overlay/.test(u));
  const onOverlay = JSON.parse(await ov.evalJs(probeExpr));
  ov.close(); main.close();

  console.log('main  :', JSON.stringify(onMain));
  console.log('overlay:', JSON.stringify(onOverlay));
  let ok;
  if (MODE === 'repro') {
    ok = onMain.md === 'undefined' && onOverlay.md === 'undefined';
  } else {
    ok = onMain.md !== 'undefined' && onOverlay.md !== 'undefined'
      && onOverlay.isSecure === true && /^tracks=\d+$/.test(onOverlay.rec);
  }
  console.log(ok ? 'MEDIA_ORIGIN_PASS' : 'MEDIA_ORIGIN_FAIL');
  process.exit(ok ? 0 : 1);
})().catch((e) => { console.log('SCRIPT ERROR:', e.message); console.log('MEDIA_ORIGIN_FAIL'); process.exit(1); });
