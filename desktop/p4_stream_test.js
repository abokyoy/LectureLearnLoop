/**
 * P4 步骤2 de-risk：验证 Deepgram 流式 WS 通道。
 * 用 lecture_sample.wav 的 PCM 数据按时间分块发送，收增量/最终字幕。
 * 用法: node p4_stream_test.js <wav路径> <api_key>
 */
const fs = require('fs');
const WebSocket = require('ws');

const wavPath = process.argv[2] || '../server/tests/fixtures/lecture_sample.wav';
const API_KEY = process.argv[3] || 'a88b5a5a7e9a750bcc8f984ac48a2c9f62bcaef4';

const raw = fs.readFileSync(wavPath);
// 最小 WAV 头解析：找 data 子块
function findData(buf) {
  let off = 12;
  while (off + 8 <= buf.length) {
    const id = buf.toString('ascii', off, off + 4);
    const size = buf.readUInt32LE(off + 4);
    if (id === 'data') return { start: off + 8, size };
    off += 8 + size + (size % 2);
  }
  return { start: 44, size: buf.length - 44 };
}
const d = findData(raw);
const pcm = raw.slice(d.start, d.start + d.size);
console.log(`pcm bytes: ${pcm.length} (~${(pcm.length / 32000).toFixed(1)}s @16k16bit mono)`);

const url = `wss://api.deepgram.com/v1/listen?model=nova-2&language=multi&encoding=linear16&sample_rate=16000&channels=1&interim_results=true&punctuate=true`;
const ws = new WebSocket(url, { headers: { Authorization: `token ${API_KEY}` } });

let finals = [];
let openBytes = 0;
const CHUNK = 3200; // 100ms @16k16mono
const sent = Buffer.alloc(0);

ws.on('open', () => {
  console.log('WS open, streaming...');
  let idx = 0;
  const timer = setInterval(() => {
    if (idx >= pcm.length) {
      clearInterval(timer);
      setTimeout(() => ws.close(), 1500);
      return;
    }
    const end = Math.min(idx + CHUNK, pcm.length);
    ws.send(pcm.slice(idx, end));
    idx = end;
    openBytes = idx;
  }, 25); // 加速 4x 发送（25ms 发 100ms 音频）
});

ws.on('message', (msg) => {
  try {
    const j = JSON.parse(msg.toString());
    if (j.type === 'Results' && j.channel && j.channel.alternatives && j.channel.alternatives[0]) {
      const alt = j.channel.alternatives[0];
      if (j.is_final && alt.transcript && alt.transcript.trim()) {
        finals.push(alt.transcript.trim());
        console.log(`[final] ${alt.transcript.trim()}`);
      }
    } else if (j.type === 'Metadata') {
      console.log('metadata: microphone_opened=', !!j.metadata.request_id);
    } else if (j.type === 'Error') {
      console.log('DG error:', JSON.stringify(j));
    }
  } catch (e) { /* ignore non-json */ }
});

ws.on('close', (code, reason) => {
  console.log(`WS close code=${code} reason=${reason}`);
  const full = finals.join(' ');
  const ok = full.toLowerCase().includes('eigen') && full.split(/\s+/).length > 30;
  console.log(`\n=== total final words: ${full.split(/\s+/).filter(Boolean).length} ===`);
  console.log('RESULT:', ok ? 'PASS' : 'FAIL');
  try {
    fs.writeFileSync('../server/tests/fixtures/lecture_stream.txt', full, 'utf-8');
  } catch (e) {}
  process.exit(ok ? 0 : 2);
});

ws.on('error', (err) => {
  console.log('WS error:', err.message);
  process.exit(1);
});
