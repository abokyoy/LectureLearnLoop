/**
 * P4f 端到端冒烟（Node 驱动，复用主进程 asr_proxy.js）。
 * 全链路：注册/登录 → /api/asr/config → 文件音源 PCM → Deepgram 流式 WS →
 *         字幕增长 → /api/llm/summarize-text 段落总结 → /api/vault/note 落库 →
 *         /api/vault/screenshot 截图入库。
 * 仅覆盖服务端点 + ASR 代理 + 数据流；Electron 渲染层采集胶水由 CDP/P6 验证。
 * 运行: node p4_smoke_e2e.js
 */
const fs = require('fs');
const path = require('path');
const asr = require('./asr_proxy');

const BASE = process.env.LL_SERVER || 'http://127.0.0.1:6001';
const WAV = path.join(__dirname, '..', 'server', 'tests', 'fixtures', 'lecture_sample.wav');
const USER = 'p4_user_' + Date.now().toString().slice(-6);
const PWD = 'P4pass123!';

let failures = [];
function check(cond, name, detail) {
  console.log(`[${cond ? 'PASS' : 'FAIL'}] ${name}${detail ? '  ' + detail : ''}`);
  if (!cond) failures.push(name);
}

async function jfetch(p, opts, token) {
  const headers = Object.assign({ 'Content-Type': 'application/json' }, opts && opts.headers || {});
  if (token) headers.Authorization = 'Bearer ' + token;
  const r = await fetch(BASE + p, Object.assign({}, opts, { headers }));
  let j;
  try { j = await r.json(); } catch (e) { j = { _nonjson: true, _status: r.status }; }
  return { status: r.status, body: j };
}

// 解析 WAV data 块 → 原始 16k Int16 PCM Buffer
function parseWav(file) {
  const raw = fs.readFileSync(file);
  let off = 12, dataStart = -1, dataLen = 0, rate = 16000;
  while (off + 8 <= raw.length) {
    const id = raw.toString('ascii', off, off + 4);
    const size = raw.readUInt32LE(off + 4);
    if (id === 'fmt ') rate = raw.readUInt32LE(off + 12);
    if (id === 'data') { dataStart = off + 8; dataLen = size; }
    off += 8 + size + (size % 2);
  }
  if (dataStart < 0) throw new Error('no data chunk');
  return { pcm: raw.slice(dataStart, dataStart + dataLen), rate };
}

// 生成一张极小 PNG（1x1）的 base64，用于截图端点测试
const TINY_PNG_B64 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';

(async () => {
  console.log('BASE', BASE, '| WAV', WAV);

  // 1) 注册
  const reg = await jfetch('/api/auth/register', { method: 'POST', body: JSON.stringify({ username: USER, password: PWD }) });
  check(reg.body && reg.body.success, '注册成功', JSON.stringify(reg.body).slice(0, 120));
  let token = reg.body && reg.body.data && reg.body.data.token;
  if (!token) {
    const lg = await jfetch('/api/auth/login', { method: 'POST', body: JSON.stringify({ username: USER, password: PWD }) });
    token = lg.body && lg.body.data && lg.body.data.token;
  }
  check(!!token, '获得 JWT token');
  if (!token) { finish(); return; }

  // 2) ASR 配置（测试音源为英文 TTS，显式指定 multi；中文场景实测用 zh-CN，服务端默认已改 zh-CN）
  const cfgR = await jfetch('/api/asr/config?language=' + (process.env.P4_SMOKE_LANG || 'multi'), { method: 'GET' }, token);
  check(cfgR.body && cfgR.body.success && cfgR.body.data.api_key, '获取 ASR 配置', 'model=' + (cfgR.body.data && cfgR.body.data.model));
  const cfg = cfgR.body.data;

  // 3) 文件音源 PCM → Deepgram 流式 WS → 字幕增长
  const { pcm } = parseWav(WAV);
  console.log('pcm bytes', pcm.length, '(~' + (pcm.length / 32000).toFixed(1) + 's)');
  const finals = [];
  let wsOpened = false, gotInterim = false;
  const streamResult = await new Promise((resolve) => {
    const sess = asr.startSession(cfg, (ev) => {
      if (ev.type === 'open') wsOpened = true;
      else if (ev.type === 'interim') gotInterim = true;
      else if (ev.type === 'final') finals.push(ev.text);
      else if (ev.type === 'close') resolve({ ok: true });
      else if (ev.type === 'error') resolve({ ok: false, err: ev.text });
    });
    let idx = 0;
    const CHUNK = 3200;
    const t = setInterval(() => {
      if (idx >= pcm.length) { clearInterval(t); setTimeout(() => sess.close(), 1200); return; }
      sess.send(pcm.slice(idx, idx + CHUNK)); idx += CHUNK;
    }, 20);
    setTimeout(() => { try { sess.close(); } catch (e) {} resolve({ ok: finals.length > 0, timeout: true }); }, 60000);
  });

  const transcript = finals.join(' ');
  const words = transcript.split(/\s+/).filter(Boolean).length;
  check(wsOpened, 'WS 会话建立');
  check(gotInterim || finals.length > 0, '收到转写结果');
  check(finals.length >= 3 && words > 30, '字幕随流增长', `finals=${finals.length} words=${words}`);
  check(/eigen/i.test(transcript), '转写命中专业词 eigen', transcript.slice(0, 80));
  fs.writeFileSync(path.join(__dirname, '..', 'server', 'tests', 'fixtures', 'p4_e2e_transcript.txt'), transcript, 'utf-8');

  // 4) 段落总结（DeepSeek）
  const sum = await jfetch('/api/llm/summarize-text', { method: 'POST', body: JSON.stringify({ text: transcript || 'eigenvalue eigenvector linear algebra lecture.' }) }, token);
  const summaryText = sum.body && sum.body.data && sum.body.data.summary;
  check(sum.body && sum.body.success && sum.body.data && sum.body.data.success && summaryText && summaryText.length > 5,
    '段落总结非空', (summaryText || '').slice(0, 80).replace(/\n/g, ' '));

  // 5) 笔记落库
  const noteR = await jfetch('/api/vault/note', { method: 'POST', body: JSON.stringify({ folder_path: 'vault' }) }, token);
  const noteName = noteR.body && typeof noteR.body.data === 'string' ? noteR.body.data : '';
  check(!!noteName && noteName.endsWith('.md'), '创建笔记', noteName);
  const noteRel = 'vault/' + noteName;
  const noteContent = '# 听课笔记\n\n## 转写全文\n\n' + transcript + '\n\n## 段落总结\n\n' + (summaryText || '') + '\n';
  const saveR = await jfetch('/api/vault/rawfile', { method: 'PUT', body: JSON.stringify({ path: noteRel, content: noteContent }) }, token);
  check(saveR.body && saveR.body.data === true, '写入笔记内容');
  const readR = await jfetch('/api/vault/rawfile?path=' + encodeURIComponent(noteRel), { method: 'GET' }, token);
  const readBack = readR.body && typeof readR.body.data === 'string' ? readR.body.data : '';
  check(readBack.includes('转写全文') && readBack.length >= noteContent.length - 5, '读回笔记校验', 'len=' + readBack.length);

  // 6) 截图入库 + 插入笔记
  const shot = await jfetch('/api/vault/screenshot', { method: 'POST', body: JSON.stringify({ image_b64: TINY_PNG_B64, note_path: noteRel }) }, token);
  const sd = shot.body && shot.body.data;
  check(shot.body && shot.body.success && sd && sd.success && sd.rel, '截图保存', sd && sd.rel);
  check(sd && sd.appended_to_note === true, '截图引用插入笔记');
  const readAfter = await jfetch('/api/vault/rawfile?path=' + encodeURIComponent(noteRel), { method: 'GET' }, token);
  check(readAfter.body && readAfter.body.data && readAfter.body.data.includes('![截屏]'), '笔记含截图 markdown 引用');

  // 7) 非法路径越权防护（多用户隔离回归）
  const bad = await jfetch('/api/vault/screenshot', { method: 'POST', body: JSON.stringify({ image_b64: TINY_PNG_B64, note_path: '../../../etc/passwd' }) }, token);
  const bd = bad.body && bad.body.data;
  check(bad.body && bad.body.success && bd && (bd.appended_to_note === false), '越权 note_path 不追加', JSON.stringify(bd).slice(0, 100));

  finish();
})().catch((e) => { console.log('EXCEPTION', e); failures.push('exception:' + e.message); finish(); });

function finish() {
  console.log('\n==== P4 E2E: ' + (failures.length ? 'FAIL(' + failures.length + ')' : 'ALL PASS') + ' ====');
  if (failures.length) console.log('failures:', failures.join(' | '));
  process.exit(failures.length ? 2 : 0);
}
