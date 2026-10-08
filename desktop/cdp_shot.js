// PDF④/B5 验证截图：连 Electron CDP(9222) 抓主窗口画面（browser-use 截图在该页超时）
const http = require('http');
const fs = require('fs');
const WebSocket = require('ws');

const OUT = process.argv[2] || 'e:/LLM/LectureLearnLoop/design/walkthrough/cdp_shot.png';
const SCRIPT = process.argv[3] || ''; // 可选：截图前在页面执行的 JS 表达式

function getJSON(url) {
  return new Promise((res, rej) => http.get(url, (r) => {
    let d = ''; r.on('data', (c) => (d += c)); r.on('end', () => { try { res(JSON.parse(d)); } catch (e) { rej(e); } });
  }).on('error', rej));
}

(async () => {
  const targets = await getJSON('http://127.0.0.1:9222/json');
  const page = targets.find((t) => t.type === 'page' && /online_course|6001/.test(t.url) && !/note-picker|overlay|capture/.test(t.url))
    || targets.find((t) => t.type === 'page');
  if (!page) throw new Error('no page target');
  console.log('target:', page.url);
  const ws = new WebSocket(page.webSocketDebuggerUrl, { perMessageDeflate: false });
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
  await new Promise((res, rej) => { ws.on('open', res); ws.on('error', rej); });
  if (SCRIPT) {
    const r = await send('Runtime.evaluate', { expression: SCRIPT, awaitPromise: true, returnByValue: true });
    console.log('script result:', JSON.stringify(r.result && r.result.value).slice(0, 400));
    await new Promise((s) => setTimeout(s, 700)); // 等过渡动画
  }
  const shot = await send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(OUT, Buffer.from(shot.data, 'base64'));
  console.log('saved:', OUT);
  ws.close();
  process.exit(0);
})().catch((e) => { console.error('ERR', e.message); process.exit(1); });
