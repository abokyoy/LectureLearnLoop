// 轻量截图：jpeg + 长超时（大 DOM 页面 captureScreenshot 会超 20s）
const http = require('http');
const fs = require('fs');
const WebSocket = require('ws');
const OUT = process.argv[2] || 'e:/LLM/LectureLearnLoop/design/walkthrough/mdfix_shot.jpg';
function getJSON(url) {
  return new Promise((res, rej) => http.get(url, (r) => {
    let d = ''; r.on('data', (c) => (d += c)); r.on('end', () => { try { res(JSON.parse(d)); } catch (e) { rej(e); } });
  }).on('error', rej));
}
(async () => {
  const targets = await getJSON('http://127.0.0.1:9222/json');
  const page = targets.find((t) => t.type === 'page' && /6001/.test(t.url));
  const ws = new WebSocket(page.webSocketDebuggerUrl, { perMessageDeflate: false });
  let id = 0;
  const send = (method, params, toMs) => new Promise((res, rej) => {
    const mid = ++id;
    const to = setTimeout(() => rej(new Error(method + ' timeout')), toMs || 20000);
    const onMsg = (raw) => {
      const m = JSON.parse(raw);
      if (m.id === mid) { ws.off('message', onMsg); clearTimeout(to); m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result); }
    };
    ws.on('message', onMsg);
    ws.send(JSON.stringify({ id: mid, method, params: params || {} }));
  });
  await new Promise((res, rej) => { ws.on('open', res); ws.on('error', rej); });
  const r = await send('Page.captureScreenshot', { format: 'jpeg', quality: 60 }, 90000);
  fs.writeFileSync(OUT, Buffer.from(r.data, 'base64'));
  console.log('saved', OUT);
  ws.close();
})().catch((e) => { console.error('ERR', e.message); process.exit(2); });
