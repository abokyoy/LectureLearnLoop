/**
 * 电脑小智 · Node 断言套件（E1 设备/协议 + E2 音频回路 + E3 打断/回声）。
 * 运行：node desktop/xz_voice_test.js   （结果落盘 desktop/_xztest_result.txt，ascii）
 * 覆盖：
 *  A 设备层：MAC 派生稳定/本地位、持久化、OTA body/headers、激活码流、错误路径
 *  B 协议层：hello 握手、v1/v2/v3 帧头对称、控制消息、stt/tts/llm/alert 分发、stale 丢弃
 *  C 引擎编排：lessonStart→listen、opus 回路上行、下行解码送播、打断全链、在途丢弃、静音闸
 *  D DSP：alignedDelayMs 找回延迟、subtract 能量下降、无相关透传、BargeGate 状态机
 *  E 账号级身份（v0.2.1）：server 领身份/存量迁移/未绑引导/异常回退 + 防乒乓熔断
 *  F 字幕上报（v0.2.2）：tts 逐句=老师 / stt=学生、空句与超长闸、失败静默不断链、main.js 接线
 *  H 手动打断模式（v0.2.5）：闭麦零帧上行不打断、开关麦协议、tts start 自动闭麦、回 auto 链复原
 */
'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const os = require('os');
const http = require('http');
const { WebSocketServer } = require('ws');
const { XzSocket } = require('./xz_socket');
const { XzVoiceEngine, macFromSeed } = require('./xz_voice');
const DSP = require('./xz_dsp');

const OUT = [];
const fails = [];
let count = { pass: 0, total: 0 };
function ok(name, cond, extra) {
  count.total++;
  if (cond) { count.pass++; OUT.push('PASS ' + name + (extra ? ' [' + extra + ']' : '')); }
  else { fails.push(name); OUT.push('FAIL ' + name + (extra ? ' [' + extra + ']' : '')); }
}
function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

/* ---------------- mock 小智云（真 ws server，端口 0 随机） ---------------- */
function startMockCloud(opts) {
  opts = opts || {};
  const state = { conns: [] };
  const wss = new WebSocketServer({ port: 0 });
  wss.on('connection', (ws, req) => {
    const conn = { ws, headers: req.headers, texts: [], binaries: [], helloReplied: false };
    state.conns.push(conn);
    ws.on('message', (data, isBinary) => {
      if (isBinary) { conn.binaries.push(Buffer.from(data)); return; }
      const text = data.toString();
      conn.texts.push(text);
      try {
        const o = JSON.parse(text);
        if (o.type === 'hello' && !conn.helloReplied) {
          conn.helloReplied = true;
          ws.send(JSON.stringify({
            type: 'hello', session_id: 'sess-test-1',
            audio_params: { format: 'opus', sample_rate: opts.downRate || 24000, frame_duration: 60 },
          }));
        }
      } catch (e) { /* 非 JSON 忽略 */ }
    });
  });
  return new Promise((resolve) => {
    wss.on('listening', () => resolve({
      state,
      url: 'ws://127.0.0.1:' + wss.address().port,
      last: () => state.conns[state.conns.length - 1],
      close: () => new Promise((r) => wss.close(r)),
    }));
  });
}

/** v2/v3 二进制帧封包（mock 云端下行用，与 xz_socket 封包对偶） */
function packDown(opusPayload, version) {
  if (version === 2) {
    const f = Buffer.alloc(16 + opusPayload.length);
    f[1] = 2;
    f.writeUInt32BE(12345, 8);
    f.writeUInt32BE(opusPayload.length, 12);
    opusPayload.copy(f, 16);
    return f;
  }
  if (version === 3) {
    const f = Buffer.alloc(4 + opusPayload.length);
    f.writeUInt16BE(opusPayload.length, 2);
    opusPayload.copy(f, 4);
    return f;
  }
  return opusPayload;
}

function sineI16(n, rate, amp, freq) {
  const a = new Int16Array(n);
  for (let i = 0; i < n; i++) a[i] = Math.round(amp * Math.sin(2 * Math.PI * freq * i / rate));
  return a;
}
/** 幅度分段调制正弦：纯单频正弦每 20ms 帧能量包络恒定（方差 0），帧相关无从谈起——
 *  必须用幅度变化的语音样信号（D5b 实锤教训） */
function speechLike(n, rate) {
  const amps = [2000, 9000, 400, 7000, 3000, 500, 8000, 1500];
  const a = new Int16Array(n);
  const seg = Math.max(1, Math.floor(n / amps.length));
  for (let i = 0; i < n; i++) {
    const amp = amps[Math.min(amps.length - 1, Math.floor(i / seg))];
    a[i] = Math.round(amp * Math.sin(2 * Math.PI * 500 * i / rate));
  }
  return a;
}
function i16ToBuf(i16) { return Buffer.from(i16.buffer, i16.byteOffset, i16.byteLength); }

/* ================= A. 设备层 ================= */
async function testDeviceLayer() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'xzdev-'));
  const file = path.join(dir, 'xz_voice.json');
  let posted = null;
  const deps = {
    configDir: dir,
    now: () => 1780000000000,
    httpPost: async (url, body, headers) => {
      posted = { url, body: JSON.parse(body), headers };
      return { status: 200, text: JSON.stringify(posted._resp || {
        websocket: { url: 'wss://mock/xiaozhi', token: 'tk-1', version: 2 },
        activation: {},
      }) };
    },
  };

  // A1 MAC 派生稳定 + 本地位
  const mac1 = macFromSeed('seed-abc');
  const mac2 = macFromSeed('seed-abc');
  const mac3 = macFromSeed('seed-other');
  ok('A1a mac stable', mac1 === mac2);
  ok('A1b mac differs', mac1 !== mac3);
  ok('A1c mac format', /^[0-9a-f]{2}(:[0-9a-f]{2}){5}$/.test(mac1), mac1);
  const b0 = parseInt(mac1.split(':')[0], 16);
  ok('A1d local bit set & unicast', (b0 & 0x02) === 0x02 && (b0 & 0x01) === 0, 'byte0=' + b0);

  // A2 持久化：同目录两实例同 mac
  const e1 = new XzVoiceEngine(deps);
  const m1 = e1.deviceId;
  const e2 = new XzVoiceEngine(deps);
  ok('A2 identity persisted', e2.deviceId === m1 && fs.existsSync(file));

  // A3 register：OTA body/headers
  const r = await e1.register();
  ok('A3a ota url', posted.url === 'https://api.tenclass.net/xiaozhi/ota/');
  ok('A3b body chip', posted.body.chip_model_name === 'esp32s3' && posted.body.version === 2);
  ok('A3c body mac/uuid', posted.body.mac_address === m1 && !!posted.body.uuid);
  ok('A3d body board/app', posted.body.board.type === 'bread-compact-wifi' && posted.body.application.name === 'xiaozhi-music-desktop');
  ok('A3e headers', posted.headers['Activation-Version'] === '1' && posted.headers['Device-Id'] === m1 && !!posted.headers['Client-Id']);
  ok('A3f bound result', r.bound === true && r.wsUrl === 'wss://mock/xiaozhi');
  const st = e1.getState();
  ok('A3g cfg persisted', st.bound === true && st.wsVersion === 2 && st.registered === true);

  // A4 未激活：返回 6 位码
  deps.httpPost = async (url, body, headers) => ({ status: 200, text: JSON.stringify({
    activation: { code: '123456', message: '请输入' },
  }) });
  const e3 = new XzVoiceEngine(deps);
  const r2 = await e3.register();
  ok('A4a need activation', r2.bound === false && r2.code === '123456');
  ok('A4b state code', e3.getState().activationCode === '123456' && e3.getState().bound === false);

  // A5 HTTP 错误路径
  deps.httpPost = async () => ({ status: 403, text: 'forbidden' });
  const e4 = new XzVoiceEngine(deps);
  let threw = false;
  try { await e4.register(); } catch (e) { threw = /403/.test(e.message); }
  ok('A5 http 4xx throws + status error', threw && e4.getState().status === 'error');
}

/* ================= B. 协议层 ================= */
async function testProtocol() {
  const cloud = await startMockCloud({ downRate: 24000 });
  const evts = [];
  const mk = (version) => {
    const rec = { audio: [], stt: [], tts: [], ready: null, closed: [] };
    const s = new XzSocket({
      url: cloud.url, token: 'Bearer abc', version,
      deviceId: '3c:aa:bb:cc:dd:ee', clientId: 'cid-1',
      listener: {
        onOpen() {},
        onReady(sid, rate, fd) { rec.ready = { sid, rate, fd }; },
        onStt(t) { rec.stt.push(t); },
        onTtsStart() { rec.tts.push('start'); },
        onTtsSentence(t) { rec.tts.push('sent:' + t); },
        onTtsStop() { rec.tts.push('stop'); },
        onEmotion(e) { evts.push('emo:' + e); },
        onAudio(b) { rec.audio.push(b); },
        onClose(rsn) { rec.closed.push(rsn); },
        onError() {},
      },
    });
    return { s, rec };
  };

  // B1 hello 握手 + 头部
  const v2 = mk(2);
  v2.s.connect();
  await sleep(200);
  const conn = cloud.last();
  ok('B1a handshake headers', conn.headers.authorization === 'Bearer abc' && conn.headers['protocol-version'] === '2' && conn.headers['device-id'] === '3c:aa:bb:cc:dd:ee');
  const hello = JSON.parse(conn.texts[0]);
  ok('B1b hello body', hello.type === 'hello' && hello.version === 2 && hello.transport === 'websocket'
    && hello.audio_params.format === 'opus' && hello.audio_params.sample_rate === 16000
    && hello.audio_params.frame_duration === 60 && !hello.features.mcp);
  ok('B1c onReady from server hello', v2.rec.ready && v2.rec.ready.sid === 'sess-test-1' && v2.rec.ready.rate === 24000, JSON.stringify(v2.rec.ready));

  // B2 listen/abort 控制消息
  v2.s.listenStart('auto');
  v2.s.abort();
  await sleep(100);
  const m1 = JSON.parse(conn.texts[1]);
  const m2 = JSON.parse(conn.texts[2]);
  ok('B2a listen start', m1.type === 'listen' && m1.state === 'start' && m1.mode === 'auto' && m1.session_id === 'sess-test-1');
  ok('B2b abort', m2.type === 'abort' && m2.session_id === 'sess-test-1');

  // B3 stt/tts/llm/alert 分发
  conn.ws.send(JSON.stringify({ type: 'stt', text: '你好老师' }));
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'start' }));
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'sentence_start', text: '今天讲函数' }));
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'stop' }));
  conn.ws.send(JSON.stringify({ type: 'llm', emotion: 'happy' }));
  conn.ws.send(JSON.stringify({ type: 'alert', message: '系统提示' }));
  await sleep(100);
  ok('B3 dispatch', v2.rec.stt[0] === '你好老师' && v2.rec.tts.join(',') === 'start,sent:今天讲函数,stop,sent:系统提示' && evts[0] === 'emo:happy', v2.rec.tts.join('|'));

  // B4 帧头对称（v2/v3/v1）
  const payload = Buffer.from([1, 2, 3, 4, 5]);
  // v2 socket 只会解 v2 封包：v3 头包(9B)与裸包(5B)长度不足 16 字节头 → 丢弃（协议层防脏数据）
  conn.ws.send(packDown(payload, 2));
  conn.ws.send(packDown(payload, 3));
  conn.ws.send(payload);
  await sleep(100);
  ok('B4a v2 down unhead', v2.rec.audio.length === 1 && Buffer.compare(v2.rec.audio[0], payload) === 0, 'n=' + v2.rec.audio.length);
  const v3 = mk(3); v3.s.connect(); await sleep(150);
  const c3 = cloud.last();
  c3.ws.send(packDown(payload, 3));
  await sleep(80);
  ok('B4b v3 down unhead', v3.rec.audio.length === 1 && v3.rec.audio[0].length === 5);
  const v1 = mk(1); v1.s.connect(); await sleep(150);
  cloud.last().ws.send(payload);
  await sleep(80);
  ok('B4c v1 raw down', v1.rec.audio.length === 1 && v1.rec.audio[0].length === 5);

  // B5 sendAudio 上行帧头（v2：16字节头，size 在 [12..15]，version 字节=2）
  v2.s.sendAudio(Buffer.from([9, 8, 7]));
  await sleep(80);
  const up = conn.binaries[0];
  ok('B5 v2 up header', up && up.length === 19 && up[1] === 2 && up.readUInt32BE(12) === 3 && up[16] === 9, up ? up.length : 'none');

  // B6 stale：close 后迟到消息丢弃
  const recBefore = v3.rec.audio.length;
  v3.s.close();
  c3.ws.send(packDown(payload, 3)); // 服务端迟到（客户端已 stale/关闭）
  await sleep(120);
  ok('B6 stale drop', v3.rec.audio.length === recBefore);

  await Promise.all([v1.s.close(), v2.s.close()]);
  await sleep(100);
  await cloud.close();
}

/* ================= C. 引擎编排（真 libopus-wasm + mock 云） ================= */
async function testEngine() {
  const codec = await import('libopus-wasm');
  const cloud = await startMockCloud({ downRate: 24000 });
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'xzeng-'));
  // 预写 cfg：跳过 register，直连 mock
  fs.writeFileSync(path.join(dir, 'xz_voice.json'), JSON.stringify({
    seed: 'test-seed', device_mac: macFromSeed('test-seed'), client_uuid: 'test-uuid',
    wsUrl: cloud.url, token: 'tk', wsVersion: 1, activationCode: '',
  }));
  let clock = 500000;
  const panel = { sent: [], events: [] };
  const deps = {
    configDir: dir,
    now: () => clock,
    codec: codec,
    httpPost: async () => ({ status: 200, text: '{}' }),
    windowOps: { send: (ch, p) => panel.sent.push({ ch, p }) },
    onEvent: (e) => panel.events.push(e),
  };
  const eng = new XzVoiceEngine(deps);
  const st = await eng.lessonStart();
  ok('C0 lessonStart', st.started === true);
  await sleep(250);
  const conn = cloud.last();
  ok('C1 listen started after ready', conn.texts.some((t) => { const o = JSON.parse(t); return o.type === 'listen' && o.state === 'start'; }));

  // C2 上行：喂 5 帧 960 样本（满 300ms 滑窗）→ mock 云收到二进制帧
  const voiced = sineI16(960, 16000, 6000, 300);
  const quiet = sineI16(960, 16000, 40, 300);
  for (let i = 0; i < 5; i++) { eng.handleMicFrame(i16ToBuf(quiet)); clock += 60; }
  await sleep(150);
  ok('C2 mic uplink opus frames', conn.binaries.length >= 1, 'n=' + conn.binaries.length);
  // v1 版本 mock 收到的是裸 opus：首字节 TOC 合理 + 长度>0
  ok('C2b packet sane', conn.binaries[0].length > 1 && conn.binaries[0].length < 400, 'len=' + conn.binaries[0].length);

  // C3 下行：mock 云发 tts start + 真 opus 包 → 引擎解码送面板 play
  const enc24 = await codec.createEncoder({ sampleRate: 24000, channels: 1, frameSize: 1440, application: codec.Application.Voip, bitrate: 32000 });
  const downPacket = Buffer.from(enc24.encode(sineI16(1440, 24000, 8000, 440)));
  enc24.free();
  conn.ws.send(JSON.stringify({ type: 'stt', text: '我被打断了' }));
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'start' }));
  await sleep(60);
  conn.ws.send(downPacket);
  await sleep(120);
  ok('C3a stt event', panel.events.some((e) => e.type === 'stt' && e.text === '我被打断了'));
  const play = panel.sent.filter((s) => s.ch === 'play');
  ok('C3b down decoded to panel play', play.length === 1 && play[0].p.rate === 24000 && play[0].p.pcm.length === 1440 * 2, 'n=' + play.length + ' bytes=' + (play[0] && play[0].p.pcm.length));

  // C3.5 排空延迟 stop（E5 实弹 L6 根因回归）：云端推完就发 stop，本地刚起步→哨兵不得下班
  const stopAt = clock;
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'stop' }));
  await sleep(60);
  ok('C3c stop deferred while draining', eng.session.gate.mode === 'play' && eng.session.pendingStopAt > stopAt);
  eng.handleMicFrame(i16ToBuf(quiet));
  clock += 2000;                      // 下一帧 mic 时排空估计已过
  eng.handleMicFrame(i16ToBuf(quiet)); clock += 60;
  await sleep(60);
  ok('C3d stop lands after drain estimate', eng.session.gate.mode === 'talk' && eng.session.pendingStopAt === 0);
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'start' }));   // 重新开一轮，给 C4 打断链用
  await sleep(60);

  // C4 打断全链：播放期持续喂高声帧 → 先 hold，累计 400ms 后 abort+重listen+flush
  panel.sent.length = 0;
  for (let i = 0; i < 8; i++) { eng.handleMicFrame(i16ToBuf(voiced)); clock += 60; }
  await sleep(150);
  ok('C4a hold first', panel.sent.some((s) => s.ch === 'hold'));
  const textsNow = conn.texts.map((t) => JSON.parse(t));
  ok('C4b abort sent', textsNow.some((o) => o.type === 'abort'));
  const starts = textsNow.filter((o) => o.type === 'listen' && o.state === 'start').length;
  ok('C4c relisten', starts >= 2, 'starts=' + starts);
  ok('C4d flush panel', panel.sent.some((s) => s.ch === 'flush'));
  // hold 期间下行帧被丢：不发 play
  const playBefore = panel.sent.filter((s) => s.ch === 'play').length;
  conn.ws.send(downPacket); // 在途帧（dropUntil 内）
  await sleep(100);
  ok('C4e inflight frames dropped after abort', panel.sent.filter((s) => s.ch === 'play').length === playBefore);

  // C4.5 hold 期下行帧入队不丢（参考 holdQueue）：resume 后补播，且 tts stop 闭合丢弃窗
  clock += 3000;
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'stop' }));   // 云端停嘴：tts stop 闭合在途丢弃
  await sleep(60);
  panel.sent.length = 0;
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'start' }));
  await sleep(60);
  eng.handleMicFrame(i16ToBuf(voiced)); clock += 60;              // 一声过线 → hold
  await sleep(60);
  const heldPlay0 = panel.sent.filter((s) => s.ch === 'play').length;
  conn.ws.send(downPacket);                                       // hold 期下行：入队不送面板
  await sleep(120);
  ok('C4f hold queues downlink', panel.sent.filter((s) => s.ch === 'play').length === heldPlay0 && eng.session.holdQ.length === 1);
  for (let i = 0; i < 35; i++) { eng.handleMicFrame(i16ToBuf(quiet)); clock += 60; }  // 静默 ≥1600ms → resume
  await sleep(150);
  ok('C4g resume replays queue', panel.sent.filter((s) => s.ch === 'play').length > heldPlay0 && panel.sent.some((s) => s.ch === 'resume'));

  // C5 静音闸：exit 后下行不播；退下静音不自动到期（v1.9.101），resumeListen 才解
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'stop' }));
  await sleep(60);
  eng.ctl('exit');
  const playN = panel.sent.filter((s) => s.ch === 'play').length;
  clock += 60000;  // 退下 1 分钟后迟到的收尾句仍静音（旧 4s 自开窗="退下了还突然出声" bug）
  conn.ws.send(downPacket);
  await sleep(120);
  ok('C5b muted gate blocks after exit', panel.sent.filter((s) => s.ch === 'play').length === playN);
  eng.ctl('resumeListen');
  conn.ws.send(downPacket);
  await sleep(120);
  ok('C5c unmute restores', panel.sent.filter((s) => s.ch === 'play').length > playN);

  // C5.5 每轮回答 stop 落地后自动重开听话窗（2026-11-05 实弹缺口：云端答完即关窗，
  // 不重开则用户后续插话全丢——"十句听不到一句"根因）；abort 路径已重开的不重复发
  {
    const t0 = conn.texts.length;
    clock += 60;
    conn.ws.send(JSON.stringify({ type: 'tts', state: 'start' }));   // 开答 → listenOpen=false
    await sleep(60);
    conn.ws.send(JSON.stringify({ type: 'tts', state: 'stop' }));    // 无已收音频 → 押后 800ms 落地
    await sleep(60);
    for (let i = 0; i < 18; i++) { eng.handleMicFrame(i16ToBuf(quiet)); clock += 60; }  // 推过排空估计点
    await sleep(120);
    const reopenN = conn.texts.slice(t0).map((s) => JSON.parse(s))
      .filter((m) => m.type === 'listen' && m.state === 'start').length;
    ok('C5.5 relisten auto after stop lands (exactly once)', reopenN === 1, 'n=' + reopenN);
    // 已在途新一轮：start→stop 再来一次，仍只重开一次（不连发截断用户话头）
    const t1 = conn.texts.length;
    clock += 60;
    conn.ws.send(JSON.stringify({ type: 'tts', state: 'start' }));
    await sleep(60);
    conn.ws.send(JSON.stringify({ type: 'tts', state: 'stop' }));
    await sleep(60);
    for (let i = 0; i < 18; i++) { eng.handleMicFrame(i16ToBuf(quiet)); clock += 60; }
    await sleep(120);
    const reopen2 = conn.texts.slice(t1).map((s) => JSON.parse(s))
      .filter((m) => m.type === 'listen' && m.state === 'start').length;
    ok('C5.5b second round reopens once', reopen2 === 1, 'n=' + reopen2);
  }

  // C6 lessonStop 收尾
  await eng.lessonStop();
  ok('C6 stopped', eng.getState().sessionActive === false);
  await cloud.close();
}

/* ================= D. DSP 纯函数 ================= */
function testDsp() {
  const R = 16000;
  // D1 alignedDelayMs 找回真实延迟（幅度调制信号，包络有信息）
  const ref = speechLike(R, R);                 // 1s 参考
  for (const dMs of [40, 90, 150]) {
    const d = Math.round(R * dMs / 1000);
    const mic = new Int16Array(d + ref.length + 800);
    mic.set(ref.subarray(0, mic.length - d - 800 >= 0 ? ref.length : mic.length - d), d); // 回声=延迟版
    const got = DSP.alignedDelayMs(mic, R, ref, R, 200);
    ok('D1 delay ' + dMs + 'ms found', Math.abs(got - dMs) <= 20 || got === -1 ? Math.abs(got - dMs) <= 20 : false, 'got=' + got);
  }
  // D2 无回声（纯噪声）→ -1
  const noise = new Int16Array(3200);
  for (let i = 0; i < noise.length; i++) noise[i] = Math.round((Math.random() - 0.5) * 600);
  ok('D2 no-echo returns -1', DSP.alignedDelayMs(noise, R, ref, R, 200) === -1);
  // D3 subtract 掩蔽：回声段能量显著下降
  const d = Math.round(R * 0.1);
  const mic2 = new Int16Array(ref.length + d);
  mic2.set(ref, d);
  const out = DSP.subtract(mic2, R, ref, R, 100, 1.2);
  const segStart = d; // mic 里回声所在段
  let eIn = 0, eOut = 0;
  for (let i = segStart; i < mic2.length; i++) { eIn += mic2[i] * mic2[i]; eOut += out[i] * out[i]; }
  ok('D3 subtract reduces echo energy', eOut < eIn * 0.6, 'ratio=' + (eOut / eIn).toFixed(3));
  // D4 BargeGate 状态机
  const acts = [];
  const g = new DSP.BargeGate({}, (a) => acts.push(a));
  let t = 1000;
  g.ttsStart(t);
  // 静音帧不触发
  g.onFrame(30, 60, t); // base 学习
  const none = g.onFrame(50, 60, t += 60);
  ok('D4a quiet no action', none.length === 0);
  // 一声人声 → 先停（hold）
  const a1 = g.onFrame(3000, 60, t += 60);
  ok('D4b first voiced holds', a1.some((a) => a.action === 'hold'));
  // hangover：300ms 内的停顿不清零
  g.onFrame(20, 60, t += 60);
  g.onFrame(20, 60, t += 250);
  // 继续人声累计（60ms/帧），此前累计 60，再 6 帧=420 ≥ 400 → abort
  let aborted = null;
  for (let i = 0; i < 8 && !aborted; i++) {
    const aa = g.onFrame(2500, 60, t += 60);
    if (aa.some((x) => x.action === 'abort')) aborted = t;
  }
  ok('D4c confirm abort at ~400ms voiced', aborted !== null);
  // 在途丢弃：持续到 tts stop（v1.9.101 教训：固定 1s 窗后尾巴照常播="打断没用"）
  ok('D4d drop persists past old 1s window', g.shouldDropIncoming(aborted + 500) === true && g.shouldDropIncoming(aborted + 6000) === true);
  // 重入闸：再次持续人声不重复 abort（ttsStop 前）
  let again = false;
  for (let i = 0; i < 20; i++) { if (g.onFrame(3000, 60, t += 60).some((x) => x.action === 'abort')) again = true; }
  ok('D4e guard blocks re-abort', !again);
  // tts stop 闭合丢弃窗；云端不另发 stop 时 12s 兜底阀自开
  const closedAtStop = (g.ttsStop(t), g.shouldDropIncoming(t + 1) === false);
  g.ttsStart(t += 60);
  let ab2 = -1;
  for (let i = 0; i < 24 && ab2 < 0; i++) { g.onFrame(3000, 60, t += 60); if (g.dropUntil === Number.MAX_SAFE_INTEGER) ab2 = t; }
  const valve = ab2 > 0 && g.shouldDropIncoming(ab2 + 11000) === true && g.shouldDropIncoming(ab2 + 13000) === false;
  ok('D4e2 drop closes at tts stop / 12s valve', closedAtStop && valve);
  // 误触恢复：新一轮播放，一声后长静默 ≥1600ms → resume
  g.ttsStop(t); g.ttsStart(t += 100);
  g.onFrame(2800, 60, t += 60);
  let resumed = false;
  for (let i = 0; i < 40 && !resumed; i++) { const aa = g.onFrame(10, 60, t += 60); if (aa.some((x) => x.action === 'resume')) resumed = true; }
  ok('D4f false alarm resumes', resumed);
  // 退下静音闸
  g.exit(t);
  ok('D4g exit mutes', g.muted === true);
  g.unmute();
  ok('D4h unmute', g.muted === false);
  // D5 EchoGauge：喂对齐参考+回声窗，process 输出长度不变且当前延迟被找到
  const eg = new DSP.EchoGauge({ micRate: R, refRate: R, alignEveryMs: 300 });
  eg.pushRef(ref, R);
  const micWin = new Int16Array(4800);
  // 回声必须是 ring 【尾部】（最新播放）内容的延迟拷贝：tail 对齐窗才能配上
  micWin.set(ref.subarray(ref.length - 4800 + 1600 - 1600, ref.length - 1600), 1600); // = ref[11200..14400)，延迟 100ms
  const proc = eg.process(micWin, 1000);
  ok('D5a process keeps length', proc.length === micWin.length);
  ok('D5b delay aligned', eg.currentDelayMs >= 80 && eg.currentDelayMs <= 160, 'delay=' + eg.currentDelayMs);
}

/* ================= E. 账号级身份与防乒乓熔断（v0.2.1） ================= */
async function testServerIdentity() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'xzid-'));
  const base = () => ({
    configDir: dir,
    now: () => 1780000000000,
    httpPost: async () => ({ status: 200, text: JSON.stringify({ websocket: { url: 'wss://mock/x', token: 'tk', version: 2 }, activation: {} }) }),
  });

  // E1 未注入 serverApi（旧用法）：回退本机身份，旧行为不变
  const e1 = new XzVoiceEngine(base());
  const r1 = await e1.register();
  ok('E1a legacy fallback', e1.identitySource === 'local-legacy' && r1.bound === true && e1.needBind === false);

  // E2 服务器 bound：直接冒充账号身份，旧缓存 wsUrl 作废强制重注册
  const calls = [];
  const d2 = base();
  d2.serverApi = async (m, p, body) => { calls.push([m, p, body]); return { has_device: true, bound: true, dev_type: 'virtual', mac: '11:22:33:44:55:66', client_uuid: 'uuid-server' }; };
  const e2 = new XzVoiceEngine(d2);
  e2.cfg.wsUrl = 'wss://stale';   // 换绑前的旧云端地址
  const r2 = await e2.register();
  ok('E2a server identity used', e2.identitySource === 'server' && r2.bound === true && e2.cfg.device_mac === '11:22:33:44:55:66' && e2.cfg.client_uuid === 'uuid-server');
  ok('E2b stale wsUrl invalidated then refreshed', r2.wsUrl === 'wss://mock/x' && e2.cfg.wsUrl === 'wss://mock/x');
  ok('E2c only identity called', calls.length === 1 && calls[0][1] === '/api/board/xzdevice/identity');
  ok('E2d state carries devType', e2.getState().devType === 'virtual' && e2.getState().needBind === false);

  // E3 未绑且本机无身份：needBind 引导，不再自行出码；绑定后重注册即领身份（重新绑定链路）
  const dir3 = fs.mkdtempSync(path.join(os.tmpdir(), 'xzid3-'));
  const d3 = base(); d3.configDir = dir3;
  let got3 = null, get3 = 0;
  d3.serverApi = async () => { get3++; return get3 >= 2 ? { has_device: true, bound: true, dev_type: 'virtual', mac: 'fe:ed:ce:de:be:ef', client_uuid: 'u3' } : { has_device: false, bound: false }; };
  const e3 = new XzVoiceEngine(d3);
  got3 = await e3.lessonStart();
  ok('E3a lessonStart needBind', got3.started === false && got3.needBind === true);
  ok('E3a2 state needBind', e3.getState().needBind === true && e3.getState().status === 'idle');
  // 第二次：领到 bound → 正常注册成功（btnRebind/重新开课走的就是这条路）
  const r3 = await e3.register();
  ok('E3b re-register adopts identity', e3.identitySource === 'server' && r3.bound === true && e3.cfg.device_mac === 'fe:ed:ce:de:be:ef' && e3.needBind === false);

  // E4 未绑但本机有旧身份 → 自动 migrate 后重领（用户无感，不再要码）
  let phase = 0;
  const mig = [];
  const d4 = base();
  const e4 = new XzVoiceEngine(d4);
  e4.ensureIdentity();
  const localMac = e4.cfg.device_mac, localUuid = e4.cfg.client_uuid;
  const localOf = () => localMac;
  d4.serverApi = async (m, p, body) => {
    if (m === 'POST') { mig.push(body); phase = 1; return { has_device: true, bound: false }; }
    return phase === 0 ? { has_device: false, bound: false } : { has_device: true, bound: true, dev_type: 'virtual', mac: localOf(e4), client_uuid: 'uuid-migrated' };
  };
  const r4 = await e4.register();
  ok('E4a migrate payload', mig.length === 1 && mig[0].mac === localMac && mig[0].client_uuid === localUuid);
  ok('E4b identity adopted', e4.identitySource === 'server' && r4.bound === true);

  // E5 serverApi 异常（旧服务器无端点/断网）：回退本机身份，不断旧链路
  const d5 = base();
  d5.serverApi = async () => { throw new Error('HTTP 404'); };
  const e5 = new XzVoiceEngine(d5);
  const r5 = await e5.register();
  ok('E5a legacy on api error', e5.identitySource === 'local-legacy' && r5.bound === true);

  // E6 防乒乓熔断：连上不足 2.5s 就被顶下线，连续 3 轮停重连
  // （mock WS 用 EventEmitter 对齐 ws 事件接口；重连前的 register 桩成即时 bound，不碰真云）
  const { EventEmitter: EE } = require('events');
  let t6 = 100000;
  const d6 = base();
  d6.now = () => t6;   // 可变时钟经 deps 注入（_now 是 getter-only，不能直接覆盖）
  d6.serverApi = async () => ({ has_device: true, bound: true, dev_type: 'real', mac: 'aa:bb:cc:dd:ee:ff', client_uuid: 'u' });
  const mkWS = () => { class FakeWS extends EE { send() {} close() {} ping() {} } return FakeWS; };
  const evts6 = [];
  const e6 = new XzVoiceEngine(d6);
  e6.deps.onEvent = (ev) => { if (ev.type === 'error') evts6.push(ev.message); };   // _emit 动态读 deps，晚注即可
  e6.cfg.wsUrl = 'wss://mock';
  e6.register = async () => ({ bound: true, code: '', message: '', wsUrl: 'wss://mock', token: 'tk', wsVersion: 1 });
  d6.WebSocketImpl = mkWS();
  const sess = { closed: false, enc: null, dec: null, gate: null, gauge: null, holdQ: [], slide: new Int16Array(0), slideLen: 0, listenOpen: false };
  e6.session = sess;
  e6.reconnect.wantLive = true;
  e6.bounce = { lastOpenAt: 0, consec: 0, fused: false };
  for (let i = 0; i < 3; i++) {
    e6._connectSocket(sess);                 // 每轮重建 socket（同真实重连路径；_notified 使 close 幂等只报一次）
    e6.socket.ws.emit('open');               // 连上
    t6 += 300;                               // 300ms 后被顶下线
    e6.socket.ws.emit('close', 1006, Buffer.from('peer'));
  }
  ok('E6a fuse after 3 bounces', e6.bounce.fused === true && e6.reconnect.wantLive === false);
  ok('E6b fuse message', evts6.some((m) => /别的电脑上课中/.test(m)), evts6.join('|').slice(0, 60));
  e6._clearReconnect();

  // E7 连够时长的正常断线重置计数，不误熔断
  let t7 = 500000;
  const d7 = base();
  d7.now = () => t7;
  d7.serverApi = d6.serverApi;
  d7.WebSocketImpl = mkWS();
  const e7 = new XzVoiceEngine(d7);
  e7.cfg.wsUrl = 'wss://mock';
  e7.register = async () => ({ bound: true, code: '', message: '', wsUrl: 'wss://mock', token: 'tk', wsVersion: 1 });
  const sess7 = { closed: false, enc: null, dec: null, gate: null, gauge: null, holdQ: [], slide: new Int16Array(0), slideLen: 0, listenOpen: false };
  e7.session = sess7;
  e7.reconnect.wantLive = true;
  e7.bounce = { lastOpenAt: 0, consec: 2, fused: false };   // 已顶过 2 轮的临界态
  e7._connectSocket(sess7);
  e7.socket.ws.emit('open');
  t7 += 3000;                                  // 连了 3 秒才断：待机断线，不是被顶
  e7.socket.ws.emit('close', 1000, Buffer.from('bye'));
  ok('E7a long session resets consec', e7.bounce.consec === 0 && e7.bounce.fused === false);
  e7.reconnect.wantLive = false;
  e7._clearReconnect();

  // E8 课堂永不自动结束（2026-11-15 用户裁定：没点下课=同一堂课还在上）：
  // 连续失败十余次也不判死；退避封顶 60s；弱提示只在第 4 次发一次
  const e8 = new XzVoiceEngine(Object.assign(base(), { serverApi: d6.serverApi, now: () => 400000 }));
  e8.cfg.wsUrl = 'wss://mock';
  e8.session = { closed: false, listenOpen: false };
  e8.reconnect.wantLive = true;
  const notes8 = [], errs8 = [];
  e8.deps.onEvent = (ev) => { if (ev.type === 'sock') notes8.push(ev.note); if (ev.type === 'error') errs8.push(ev.message); };
  for (let i = 0; i < 12; i++) { e8._maybeReconnect(); e8._clearReconnect(); }
  ok('E8a never dies on retries', e8.reconnect.wantLive === true && e8.bounce.fused === false);
  ok('E8b ladder capped 60s', notes8[notes8.length - 1] === 'reconnect_in:60000', notes8.join(','));
  ok('E8c soft warn exactly once', errs8.length === 1 && /持续自动重连/.test(errs8[0]), errs8.join('|'));

  // E9 待机断线不烧重连配额：ready 成功把 tries 清零（曾攒满 5 次误踢下课，实弹主因）
  const cloud9 = await startMockCloud({});
  const d9 = base();
  const e9 = new XzVoiceEngine(d9);
  e9.cfg.wsUrl = cloud9.url;   // 共享 dir 里 E1 存过假地址，必须显式指向 mock 云
  e9.cfg.token = 'tk'; e9.cfg.wsVersion = 1;
  e9.register = async () => ({ bound: true, code: '', message: '', wsUrl: cloud9.url, token: 'tk', wsVersion: 1 });
  const notes9 = [];
  e9.deps.onEvent = (ev) => { if (ev.type === 'sock') notes9.push(ev.note); };
  await e9.lessonStart();
  for (let w = 0; w < 60 && e9.status !== 'ready'; w++) await sleep(50);
  ok('E9a lesson ready', e9.status === 'ready');
  e9.reconnect.tries = 3;                       // 模拟历史上已失败过 3 轮
  cloud9.last().ws.close(1000, Buffer.from('bye'));
  await sleep(150);
  ok('E9b 待机断线按已消耗梯级排重连', e9.reconnect.tries === 4 && notes9[notes9.length - 1] === 'reconnect_in:5000', notes9.join(','));
  for (let w = 0; w < 140 && !(e9.reconnect.tries === 0 && e9.status === 'ready' && cloud9.state.conns.length >= 2); w++) await sleep(50);
  ok('E9c 重连成功 ready 把 tries 清零（曾漏此步攒满 5 次误踢下课）', e9.reconnect.tries === 0 && cloud9.state.conns.length >= 2);
  e9.reconnect.wantLive = false;
  e9._clearReconnect();
  await e9.lessonStop();
  await cloud9.close();

  // E10 课中重连 register 静默：失败不翻面板状态（保持「上课中」），只记 lastError
  const badPost = async () => { throw new Error('getaddrinfo ENOTFOUND mock'); };
  const e10 = new XzVoiceEngine(Object.assign(base(), { httpPost: badPost }));
  e10.status = 'ready';
  let threw10 = false;
  try { await e10.register({ silent: true }); } catch (err) { threw10 = /ENOTFOUND/.test(err.message); }
  ok('E10a silent keeps status', threw10 && e10.status === 'ready' && /ENOTFOUND/.test(e10.lastError));
  const e10b = new XzVoiceEngine(Object.assign(base(), { httpPost: async () => { throw new Error('boom'); } }));
  try { await e10b.register(); } catch (err) { /* noop */ }
  ok('E10b non-silent still errors', e10b.status === 'error');

  // E11 绑定失效不再断重连链（可恢复态，课堂不死）：下一轮仍在排
  const e11 = new XzVoiceEngine(Object.assign(base(), { serverApi: d6.serverApi }));
  e11.cfg.wsUrl = 'wss://mock';
  e11.session = { closed: false, listenOpen: false };
  e11.reconnect.wantLive = true;
  e11.register = async () => ({ bound: false, code: '1234', message: '', wsUrl: '', token: '', wsVersion: 1 });
  e11._connectSocket = () => { throw new Error('不该在 bound 前建连'); };
  e11._maybeReconnect();
  await sleep(1100);                             // 首轮 800ms 到点：bound=false 后应再排下一轮
  ok('E11a unbound keeps retrying', e11.reconnect.wantLive === true && e11.reconnect.tries === 2, 'tries=' + e11.reconnect.tries);
  e11.reconnect.wantLive = false;
  e11._clearReconnect();

  // E12 重连 OTA 在途时用户下课：await 回来不得再建连（防僵尸连接，评审 W1）
  const e12 = new XzVoiceEngine(Object.assign(base(), { serverApi: d6.serverApi }));
  e12.cfg.wsUrl = 'wss://mock';
  e12.session = { closed: false, listenOpen: false };
  e12.reconnect.wantLive = true;
  e12.register = async () => { await sleep(300); return { bound: true, code: '', message: '', wsUrl: 'wss://mock', token: 'tk', wsVersion: 1 }; };
  let conned12 = 0;
  e12._connectSocket = () => { conned12 += 1; };
  e12._maybeReconnect();
  await sleep(900);                              // 800ms 到点，register 在途（300ms）
  await e12.lessonStop();                        // OTA 往返途中下课
  await sleep(500);                              // 等 register 回来过守卫
  ok('E12 no zombie connect after stop', conned12 === 0, 'connects=' + conned12);
}

/* ================= G 字幕跟播放同步（2026-11-06 裁定 A） =================
 * 云端常快于实时预推文字：字幕不得在文字到达即发出，必须等播放钟（首帧送面板起）
 * 走到该句位置；打断/断线时未播句子作废；stop 落地收口补报剩余。
 */
async function testSpeechSync() {
  const codec = await import('libopus-wasm');
  const cloud = await startMockCloud({ downRate: 24000 });
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'xzsub-'));
  fs.writeFileSync(path.join(dir, 'xz_voice.json'), JSON.stringify({
    seed: 'sub-seed', device_mac: macFromSeed('sub-seed'), client_uuid: 'sub-uuid',
    wsUrl: cloud.url, token: 'tk', wsVersion: 1, activationCode: '',
  }));
  let clock = 700000;
  const panel = { sent: [], events: [] };
  const eng = new XzVoiceEngine({
    configDir: dir, now: () => clock, codec: codec,
    httpPost: async () => ({ status: 200, text: '{}' }),
    windowOps: { send: (ch, p) => panel.sent.push({ ch, p }) },
    onEvent: (e) => panel.events.push(e),
  });
  await eng.lessonStart();
  await sleep(250);
  const conn = cloud.last();
  const enc24 = await codec.createEncoder({ sampleRate: 24000, channels: 1, frameSize: 1440, application: codec.Application.Voip, bitrate: 32000 });
  const packet = Buffer.from(enc24.encode(sineI16(1440, 24000, 8000, 440)));
  const quiet = sineI16(960, 16000, 40, 300);
  const voiced = sineI16(960, 16000, 6000, 300);
  const micQuiet = (n) => { for (let i = 0; i < n; i++) { eng.handleMicFrame(i16ToBuf(quiet)); clock += 60; } };
  const sents = () => panel.events.filter((e) => e.type === 'tts' && e.state === 'sentence').map((e) => e.text);

  // G1 播放位置到点才报：先到的文字不抢跑
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'start' })); await sleep(60);
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'sentence_start', text: 'G1第一句' })); await sleep(40);
  ok('G1a sentence arrival not emitted immediately', sents().length === 0, sents().join(','));
  for (let i = 0; i < 3; i++) { conn.ws.send(packet); }
  await sleep(120);   // 收 3 帧×60ms，playT0 起钟
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'sentence_start', text: 'G1第二句' })); await sleep(60);
  micQuiet(1); await sleep(60);        // 播放钟起步：时刻 0 → 第一句（atMs=0）上报
  ok('G1b first sentence on play clock start', sents().join(',') === 'G1第一句', sents().join(','));
  ok('G1c second sentence waits its play position',
    eng.session.speechQ.length === 1 && eng.session.speechQ[0].atMs === 180, JSON.stringify(eng.session.speechQ));
  micQuiet(3); await sleep(60);        // 钟走到 240ms > 180ms → 第二句报
  ok('G1d second sentence emitted at its position', sents().join(',') === 'G1第一句,G1第二句', sents().join(','));

  // G2 abort 后没播的句子永不上板（声音字幕同生共死）
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'stop' })); await sleep(60);
  clock += 2000; micQuiet(2); await sleep(60);        // 押后 stop 落地，收口本轮
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'start' })); await sleep(60);
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'sentence_start', text: 'G2听到的' })); await sleep(40);
  conn.ws.send(packet); await sleep(80);              // 首帧出声 → playT0
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'sentence_start', text: 'G2被打断的' })); await sleep(60);
  micQuiet(1); await sleep(60);                        // G2听到的（atMs=0）上报
  const nBefore = sents().length;
  for (let i = 0; i < 8; i++) { eng.handleMicFrame(i16ToBuf(voiced)); clock += 60; }   // 播放期持续高声→abort
  await sleep(150);
  ok('G2a abort cleared pending sentence', eng.session.speechQ.length === 0);
  clock += 5000; micQuiet(3); await sleep(120);
  ok('G2b unintelligible sentence never reported',
    sents().length === nBefore && !sents().includes('G2被打断的'), sents().join(','));

  // G3 正常播完收口：stop 落地把未报句补报（课件存档脚本不丢句）
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'stop' })); await sleep(60);
  clock += 2000; micQuiet(2); await sleep(60);
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'start' })); await sleep(60);
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'sentence_start', text: 'G3无声句一' })); await sleep(40);
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'sentence_start', text: 'G3无声句二' })); await sleep(40);
  ok('G3a no voice keeps queued', !sents().includes('G3无声句一'));
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'stop' })); await sleep(60);
  clock += 1500; micQuiet(1); await sleep(60);   // 无音频→排空押后 800ms 后落地
  ok('G3b stop landing flushes remainder',
    sents().includes('G3无声句一') && sents().includes('G3无声句二'), sents().slice(-2).join(','));

  // G4 hold 期字幕钟冻结：resume 时间轴前移静音间隔（前提：字幕钟已在走；单元级直接驱动闸门动作）
  const s4 = eng.session;
  s4.playT0 = clock - 5000;            // 有音频的常规轮：钟早起了
  s4.speechQ.push({ text: 'x', atMs: 1000 });
  eng._applyGateAction(s4, { action: 'hold' });
  clock += 700;
  eng._applyGateAction(s4, { action: 'resume' });
  ok('G4a resume shifts timeline only when clock running', s4.speechQ.length === 1 && s4.speechQ[0].atMs === 1700, 'atMs=' + s4.speechQ[0].atMs);
  s4.speechQ = []; s4.holdStartMs = 0; s4.playT0 = 0;

  // G5（CodeReview P1-1 回归）：hold 时首帧尚未出声（全在 holdQ）→ resume 才起钟，
  // atMs 不得被 dh 推后（修复前会慢整整一个 hold 时长：声音播到第二句字幕停在第一句）
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'stop' })); await sleep(60);
  clock += 2000; micQuiet(2); await sleep(60);                 // 收口 G4 轮
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'start' })); await sleep(60);
  eng.handleMicFrame(i16ToBuf(voiced)); clock += 60; await sleep(60);   // 首帧即 hold（playT0 未起）
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'sentence_start', text: 'G5首句' })); await sleep(40);
  conn.ws.send(packet); await sleep(80);                              // 入 holdQ，不起钟
  ok('G5a no playT0 while first-frame-hold', eng.session.playT0 === 0 && eng.session.speechQ[0].atMs === 0, 'atMs=' + eng.session.speechQ[0].atMs);
  micQuiet(30); await sleep(120);                                      // hold 超 1.6s → gate 自动 resume
  // 修复前：dh(≈1600+) 被无守卫加到 atMs → resume 后还要再走 1600ms 钟才报，这 30 帧内报不出来；
  // 修复后：resume 起钟即接着报 → 「字幕不拖后」直接可断
  ok('G5b resume starts clock and reports without dh shift',
    eng.session.playT0 !== 0 && sents().includes('G5首句'), sents().slice(-1).join(','));

  // G6（CodeReview P1-2 回归）：押后 stop 未落地被新一轮 start 抢跑 → 上轮残余补报不丢句
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'stop' })); await sleep(60);
  clock += 2000; micQuiet(2); await sleep(60);                 // 收口 G5 轮
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'start' })); await sleep(60);
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'sentence_start', text: 'G6押后残余' })); await sleep(40);
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'stop' })); await sleep(40);   // 无音频→押后 800ms
  ok('G6a stop deferred not landed', eng.session.pendingStopAt !== 0 && !sents().includes('G6押后残余'));
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'start' })); await sleep(60);  // 新一轮抢跑
  ok('G6b ttsStart flushes prior remainder', sents().includes('G6押后残余') && eng.session.speechQ.length === 0);
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'stop' })); await sleep(60);

  await eng.lessonStop();
  try { enc24.free(); } catch (e) { /* noop */ }
  await cloud.close();
}

/* ================= F 字幕上报（v0.2.2 两段式黑板） =================
 * reporter 不碰 token/fetch（request 由 main.js 注入），因此可纯 Node 断言；
 * main.js 是 Electron 主进程模块（require('electron') 在 Node 下不可用），
 * 接线部分用源码断言兜住（抽公共 serverRequest + onEvent 挂 reporter），免“改了上报入口没人知道”。*/
async function testSpeechReport() {
  const { createSpeechReporter } = require('./xz_speech');

  // ---- 采集桩：记录请求，fail 非空则报错（模拟服务端拒收/断网）----
  const calls = [];
  let throwMode = null;   // null | 'async' | 'sync'
  const req = (method, p, body) => {
    calls.push({ method, p, body });
    if (throwMode === 'sync') throw new Error('sync boom');
    return throwMode ? Promise.reject(new Error('HTTP 500 speech rejected'))
                     : Promise.resolve({ id: calls.length });
  };
  const rp = createSpeechReporter({ request: req, now: () => 1700000000000 });

  // F1 tts 逐句 = 老师口播（黑板上区字幕主力）
  const r1 = await rp.onEvent({ type: 'tts', state: 'sentence', text: 'first edge of the triangle' });
  ok('F1a tts sentence reported', calls.length === 1 && calls[0].method === 'POST'
    && calls[0].p === '/api/board/speech' && calls[0].body.role === 'teacher'
    && calls[0].body.ts === 1700000000000);
  ok('F1b reporter returns sent body', !!r1 && r1.text === 'first edge of the triangle');

  // F2 stt = 学生发言
  const r2 = await rp.onEvent({ type: 'stt', text: 'what about the slope' });
  ok('F2a stt reported as student', calls.length === 2
    && calls[1].body.role === 'student' && calls[1].body.text === 'what about the slope');

  // F3 tts 非逐句态（开始/结束/打字机中间态）不报，免重复字幕
  const n0 = calls.length;
  ok('F3a tts non-sentence ignored',
    rp.onEvent({ type: 'tts', state: 'start', text: 'x' }) === null
    && rp.onEvent({ type: 'tts', state: 'stop', text: 'x' }) === null
    && rp.onEvent({ type: 'tts', text: 'no state' }) === null
    && calls.length === n0);
  ok('F3b other events ignored',
    rp.onEvent({ type: 'state', state: 'listening' }) === null
    && rp.onEvent({ type: 'llm', text: 'thinking' }) === null
    && rp.onEvent(null) === null && rp.onEvent('junk') === null && calls.length === n0);

  // F4 空句/纯控制字符不报（与服务端 append_speech 双闸）
  ok('F4a blank and control-only skipped',
    rp.onEvent({ type: 'stt', text: '   ' }) === null
    && rp.onEvent({ type: 'stt', text: '\u0000\u0001\u0002' }) === null
    && rp.onEvent({ type: 'tts', state: 'sentence' }) === null && calls.length === n0);

  // F5 洗控制字符 + 限长 200
  await rp.onEvent({ type: 'stt', text: 'a\u0007b' });
  ok('F5a control chars collapsed to space', calls[calls.length - 1].body.text === 'a b');
  await rp.onEvent({ type: 'tts', state: 'sentence', text: 'x'.repeat(260) });
  ok('F5b truncated to 200', calls[calls.length - 1].body.text.length === rp.TEXT_MAX
    && rp.TEXT_MAX === 200);

  // F6 上报失败不断链：异步 reject 最-> null，且不抛
  throwMode = 'async';
  const before6 = calls.length;
  let threw6 = false;
  let r6;
  try { r6 = await rp.onEvent({ type: 'tts', state: 'sentence', text: 'server down' }); }
  catch (e) { threw6 = true; }
  ok('F6a async failure swallowed', !threw6 && r6 === null && calls.length === before6 + 1);

  // F7 request 同步抛（token 读取炸等）也不断链
  throwMode = 'sync';
  let threw7 = false, r7;
  try { r7 = rp.onEvent({ type: 'stt', text: 'token boom' }); } catch (e) { threw7 = true; }
  ok('F7a sync failure swallowed', !threw7 && r7 !== null && typeof r7.then === 'function');
  await r7;
  throwMode = null;

  // F8 缺 request 直接拒构造（防“静默不上报”的错配置流进生产）
  let threw8 = false;
  try { createSpeechReporter({}); } catch (e) { threw8 = true; }
  ok('F8a request is mandatory', threw8);
  let threw8b = false;
  try { createSpeechReporter(); } catch (e) { threw8b = true; }
  ok('F8b no deps still throws', threw8b);

  // F9 clean 可直接用（与服务端口径对齐的入口清洗：控制符成一串 → 一个空格，再 trim）
  ok('F9a clean collapses and trims', rp.clean('  \u0000 \u0001 hi \n there ') === 'hi   there'
    && rp.clean('a\u0000\u0001b') === 'a b' && rp.clean(null) === '');

  // ---- F10 main.js 接线源码断言（Electron 主进程不能在 Node 里 require）----
  const mainSrc = fs.readFileSync(path.join(__dirname, 'main.js'), 'utf8');
  ok('F10a module-level serverRequest',
    /^(async )?function serverRequest\(/m.test(mainSrc)
    && mainSrc.includes('serverApi: (method, p, body) => serverRequest(method, p, body)'));
  ok('F10b reporter wired into onEvent',
    mainSrc.includes("xzSpeech.createSpeechReporter({ request: serverRequest")
    && /onEvent:\s*\([\s\S]*boardSpeech\.onEvent\(evt\)/.test(mainSrc));
  ok('F10c speech failure must not break lesson',
    /boardSpeech\.onEvent\(evt\);\s*\}\s*catch/.test(mainSrc));
  ok('F10d event log still appended', mainSrc.includes("'xz_voice_events.log'"));
  // 旧写法已拔除：不能再有第二套“自带鉴权/解包”的 serverApi
  ok('F10e no duplicate serverApi fetch path',
    (mainSrc.match(/SERVER_BASE \+ p/g) || []).length === 1);
}

/* ================= H. 手动打断模式（v0.2.5；2026-11-16 实弹改版 PTT） =================
 * auto=声控打断（现状）；manual=举手↔发言完毕：待机无听话窗、零上行；
 * 举手=abort+listen start(mode=manual) 持续送话；发言完毕=listen stop 唯一提交点；
 * 老师 tts start 自动闭麦兜底；回答落地后 manual 不自动开窗（下句由举手主动开始）。
 */
async function testManualBarge() {
  const codec = await import('libopus-wasm');
  const cloud = await startMockCloud({ downRate: 24000 });
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'xzman-'));
  fs.writeFileSync(path.join(dir, 'xz_voice.json'), JSON.stringify({
    seed: 'man-seed', device_mac: macFromSeed('man-seed'), client_uuid: 'man-uuid',
    wsUrl: cloud.url, token: 'tk', wsVersion: 1, activationCode: '',
  }));
  let clock = 900000;
  const panel = { sent: [], events: [] };
  const eng = new XzVoiceEngine({
    configDir: dir, now: () => clock, codec: codec,
    httpPost: async () => ({ status: 200, text: '{}' }),
    windowOps: { send: (ch, p) => panel.sent.push({ ch, p }) },
    onEvent: (e) => panel.events.push(e),
  });
  await eng.lessonStart();
  await sleep(250);
  const conn = cloud.last();
  const voiced = sineI16(960, 16000, 6000, 300);
  const quiet = sineI16(960, 16000, 40, 300);
  const feed = (f, n) => { for (let i = 0; i < n; i++) { eng.handleMicFrame(i16ToBuf(f)); clock += 60; } };
  const dec16 = await codec.createDecoder({ sampleRate: 16000, channels: 1 });
  const upPeak = () => {
    const pcm = dec16.decode(conn.binaries[conn.binaries.length - 1]);
    let p = 0; for (const v of pcm) p = Math.max(p, Math.abs(v));
    return p;
  };
  // 静音断言专用：新建解码器按序喂进 from 以来的全部上行包，看末帧收敛峰值。
  // 不能只抽 decode 最后一包：SILK 解码器留旧流状态，voiced 段后首包静音解出仍高声
  // （探针实锤：跳包解峰值 3039，顺序连解收敛到 0），发包本身是真静音
  const upSilence = (from) => {
    return codec.createDecoder({ sampleRate: 16000, channels: 1 }).then((d) => {
      let pcm = new Int16Array(0);
      for (let i = from; i < conn.binaries.length; i++) pcm = d.decode(conn.binaries[i]);
      let p = 0; for (const v of pcm) p = Math.max(p, Math.abs(v));
      return p;
    });
  };
  const evtN = (pred) => panel.events.filter(pred).length;
  const sents = () => panel.events.filter((e) => e.type === 'tts' && e.state === 'sentence').map((e) => e.text);
  const enc24 = await codec.createEncoder({ sampleRate: 24000, channels: 1, frameSize: 1440, application: codec.Application.Voip, bitrate: 32000 });
  const downPacket = Buffer.from(enc24.encode(sineI16(1440, 24000, 8000, 440)));

  // H0 模式切换基础：auto 拒绝 toggle；manual 默认闭麦；evt/getState 同步
  ok('H0a bargeToggle rejected in auto', eng.ctl('bargeToggle').ok === false);
  const r0 = eng.ctl('setMode', 'manual');
  ok('H0b setMode manual defaults muted', r0.ok === true && r0.mode === 'manual' && r0.micWinOpen === false);
  ok('H0c mode evt broadcast', evtN((e) => e.type === 'mode' && e.mode === 'manual') === 1);
  const st0 = eng.getState();
  ok('H0d getState carries barge fields', st0.bargeMode === 'manual' && st0.micWinOpen === false);

  // H1 闭麦：高声 voiced 帧不打断 + 零帧上行 + 字幕钟/押后 stop 照常帧驱动
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'start' })); await sleep(60);
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'sentence_start', text: 'H1句' })); await sleep(40);
  conn.ws.send(downPacket); await sleep(120);                 // 首帧出声 → playT0 起钟
  const m0 = conn.texts.length, b0 = conn.binaries.length;
  panel.sent.length = 0;
  feed(voiced, 10); await sleep(150);
  ok('H1a muted never interrupts teacher', !conn.texts.slice(m0).some((t) => JSON.parse(t).type === 'abort')
    && !panel.sent.some((s) => s.ch === 'hold' || s.ch === 'flush'));
  const pk1 = await upSilence(b0);
  ok('H1b muted idle uplinks nothing (PTT: no window)', conn.binaries.length === b0, 'n=' + (conn.binaries.length - b0));
  ok('H1c subtitle clock still drives while muted', sents().includes('H1句'), sents().join(','));
  const t1s = conn.texts.length;
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'stop' })); await sleep(60);
  ok('H1d stop deferred while draining', eng.session.pendingStopAt > clock);
  clock += 2000; feed(voiced, 1); await sleep(120);           // 闭麦零上行，押后 stop 靠字幕钟帧照常落地
  ok('H1e stop lands & NO auto relisten in manual', eng.session.pendingStopAt === 0 && eng.session.gate.hold === false
    && !conn.texts.slice(t1s).some((t) => { const o = JSON.parse(t); return o.type === 'listen' && o.state === 'start'; }));

  // H2 开麦=打断+真帧上行（哨兵仍不喂）：bargeToggle（此刻 talk 态，不开丢弃窗）
  panel.sent.length = 0;
  const t2 = conn.texts.length;
  const r2 = eng.ctl('bargeToggle'); await sleep(100);
  ok('H2a toggle opens mic', r2.ok === true && r2.micWinOpen === true);
  ok('H2b abort + listen start(mode=manual) on raise hand', conn.texts.slice(t2).some((t) => JSON.parse(t).type === 'abort')
    && conn.texts.slice(t2).some((t) => { const o = JSON.parse(t); return o.type === 'listen' && o.state === 'start' && o.mode === 'manual'; }));
  ok('H2c panel flush + micwin evt', panel.sent.some((s) => s.ch === 'flush')
    && evtN((e) => e.type === 'micwin' && e.open === true) === 1);
  ok('H2d no drop window when teacher idle', eng.session.gate.dropUntil === 0);
  const b2 = conn.binaries.length;
  feed(voiced, 6); await sleep(150);
  ok('H2e open mic uplinks real voice', conn.binaries.length > b2 && upPeak() > 200, 'peak=' + upPeak());
  ok('H2f open mic never feeds gate', !panel.sent.some((s) => s.ch === 'hold')
    && conn.texts.slice(t2).map((t) => JSON.parse(t)).filter((o) => o.type === 'abort').length === 1);

  // H3 老师开口（tts start）→ 自动闭麦；此后 voiced 帧再不打断不上真声
  const t3 = conn.texts.length;
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'start' })); await sleep(80);
  ok('H3a tts start auto closes mic', eng.micWinOpen === false
    && evtN((e) => e.type === 'micwin' && e.open === false) === 1);
  const b3 = conn.binaries.length;
  feed(voiced, 8); await sleep(150);
  const ab3 = conn.texts.slice(t3).map((t) => JSON.parse(t)).filter((o) => o.type === 'abort').length;
  ok('H3b after auto-mute uplinks nothing & no abort', ab3 === 0 && conn.binaries.length === b3, 'ab=' + ab3 + ' n=' + (conn.binaries.length - b3) + ' open=' + eng.micWinOpen);

  // H4 播报中点「举手」：与哨兵 abort 同效含在途丢弃窗；再点=发言完毕（提交 listen stop）
  eng.ctl('bargeToggle'); await sleep(100);                    // play 态举手→打断
  ok('H4a play-state open arms inflight drop', eng.micWinOpen === true && eng.session.gate.dropUntil === Number.MAX_SAFE_INTEGER);
  const playP0 = panel.sent.filter((s) => s.ch === 'play').length;
  conn.ws.send(downPacket); await sleep(100);
  ok('H4b residual audio after manual abort dropped', panel.sent.filter((s) => s.ch === 'play').length === playP0);
  const t4 = conn.texts.length;
  const r4 = eng.ctl('bargeToggle'); await sleep(100);          // 再点=发言完毕：提交整段
  ok('H4c commit sends listen stop', r4.ok === true && r4.micWinOpen === false && eng.session.listenOpen === false
    && conn.texts.slice(t4).some((t) => { const o = JSON.parse(t); return o.type === 'listen' && o.state === 'stop'; }));

  // H5 回 auto：丢弃窗由后续 stop 落地闭合，声控打断全链复原（现状行为不变）
  const r5 = eng.ctl('setMode', 'auto');
  ok('H5a auto restores always-open', r5.ok === true && r5.mode === 'auto' && r5.micWinOpen === true);
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'stop' })); await sleep(60);
  clock += 3000; feed(quiet, 2); await sleep(120);             // 押后 stop 落地（H4 开麦轮 drain 估计）
  ok('H5b stop lands closes drop window', eng.session.pendingStopAt === 0 && eng.session.gate.dropUntil === 0);
  panel.sent.length = 0;
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'start' })); await sleep(60);
  conn.ws.send(downPacket); await sleep(120);
  const t5 = conn.texts.length;
  feed(voiced, 8); await sleep(150);
  ok('H5c auto gate restored: hold then abort', panel.sent.some((s) => s.ch === 'hold')
    && conn.texts.slice(t5).some((t) => JSON.parse(t).type === 'abort'));

  // H6 hold 半截切走 manual：先 resume 补播不留哑音，gate.hold 同步清零（防永久卡死）
  clock += 3000;
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'stop' })); await sleep(60);
  clock += 2000; feed(quiet, 2); await sleep(120);             // H5c 打断轮收口
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'start' })); await sleep(60);
  conn.ws.send(downPacket); await sleep(120);
  feed(voiced, 1); await sleep(60);                             // 一声过线 → hold
  conn.ws.send(downPacket); await sleep(100);                   // hold 期下行入队
  ok('H6a holding with queued downlink', eng.session.gate.hold === true && eng.session.holdQ.length === 1);
  panel.sent.length = 0;
  const r6 = eng.ctl('setMode', 'manual'); await sleep(120);
  ok('H6b switch resumes pending hold', panel.sent.some((s) => s.ch === 'resume')
    && eng.session.gate.hold === false && r6.micWinOpen === false);
  ok('H6c holdQ replayed on switch', panel.sent.filter((s) => s.ch === 'play').length >= 1);

  await eng.lessonStop();
  try { dec16.free(); enc24.free(); } catch (e) { /* noop */ }
  await cloud.close();
}

/**
 * I) PTT 举手发言协议契约（2026-11-16 实弹轮，用户裁定：点举手持续聆听，
 * 按「发言完毕」才提交）：引擎级行为契约——
 * 开课不预开 VAD 窗；举手=abort+listen start(mode=manual)；发言完毕=listen stop
 * 唯一提交点；回答落地不自动开窗；闭麦零上行；窗未开 exit 不盲发 stop。
 */
async function testPttProtocol() {
  const codec = await import('libopus-wasm');
  const cloud = await startMockCloud({ downRate: 24000 });
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'xzptt-'));
  fs.writeFileSync(path.join(dir, 'xz_voice.json'), JSON.stringify({
    seed: 'ptt-seed', device_mac: macFromSeed('ptt-seed'), client_uuid: 'ptt-uuid',
    wsUrl: cloud.url, token: 'tk', wsVersion: 1, activationCode: '',
  }));
  let clock = 1200000;
  const panel = { sent: [], events: [] };
  const eng = new XzVoiceEngine({
    configDir: dir, now: () => clock, codec: codec,
    httpPost: async () => ({ status: 200, text: '{}' }),
    windowOps: { send: (ch, p) => panel.sent.push({ ch, p }) },
    onEvent: (e) => panel.events.push(e),
  });
  // 面板恢复记忆的真实时序：开课前面板把持久化模式同步进引擎，再点上课
  eng.bargeMode = 'manual';
  eng.micWinOpen = false;
  await eng.lessonStart();
  await sleep(250);
  const conn = cloud.last();
  const voiced = sineI16(960, 16000, 6000, 300);
  const feed = (f, n) => { for (let i = 0; i < n; i++) { eng.handleMicFrame(i16ToBuf(f)); clock += 60; } };
  const dec16 = await codec.createDecoder({ sampleRate: 16000, channels: 1 });
  const upPeak = () => {
    const pcm = dec16.decode(conn.binaries[conn.binaries.length - 1]);
    let p = 0; for (const v of pcm) p = Math.max(p, Math.abs(v));
    return p;
  };
  const evtN = (pred) => panel.events.filter(pred).length;
  const enc24 = await codec.createEncoder({ sampleRate: 24000, channels: 1, frameSize: 1440, application: codec.Application.Voip, bitrate: 32000 });
  const downPacket = Buffer.from(enc24.encode(sineI16(1440, 24000, 8000, 440)));

  // I1 开课（PTT）：onReady 不预开窗——全程无 listen start，listenOpen=false；举手前零上行
  ok('I1a lesson start opens no listen window (manual)',
    !conn.texts.some((t) => { const o = JSON.parse(t); return o.type === 'listen' && o.state === 'start'; })
    && eng.session.listenOpen === false);
  const b1 = conn.binaries.length;
  feed(voiced, 8); await sleep(120);
  ok('I1b idle before raise-hand uplinks nothing', conn.binaries.length === b1, 'n=' + (conn.binaries.length - b1));

  // I2 举手：abort + listen start(mode=manual)，之后真声持续上行（云端不判停）
  const t2 = conn.texts.length;
  const r2 = eng.ctl('bargeToggle'); await sleep(100);
  ok('I2a raise hand opens manual window', r2.ok === true && r2.micWinOpen === true && eng.session.listenOpen === true);
  ok('I2b abort + listen start mode=manual', conn.texts.slice(t2).some((t) => JSON.parse(t).type === 'abort')
    && conn.texts.slice(t2).some((t) => { const o = JSON.parse(t); return o.type === 'listen' && o.state === 'start' && o.mode === 'manual'; }));
  const b2 = conn.binaries.length;
  feed(voiced, 6); await sleep(150);
  ok('I2c keeps streaming while hand raised', conn.binaries.length > b2 && upPeak() > 200, 'peak=' + upPeak());

  // I3 发言完毕：本路唯一提交点 listen stop；talk commit 事件恰一次；提交后再喂声零上行
  const t3 = conn.texts.length;
  const r3 = eng.ctl('bargeToggle'); await sleep(100);
  ok('I3a commit sends listen stop', r3.ok === true && r3.micWinOpen === false && eng.session.listenOpen === false
    && conn.texts.slice(t3).some((t) => { const o = JSON.parse(t); return o.type === 'listen' && o.state === 'stop'; }));
  ok('I3b talk commit event exactly once', evtN((e) => e.type === 'talk' && e.state === 'commit') === 1);
  const b3 = conn.binaries.length;
  feed(voiced, 6); await sleep(120);
  ok('I3c nothing uplinks after commit', conn.binaries.length === b3, 'n=' + (conn.binaries.length - b3));

  // I4 老师回答一轮收口（tts start→stop，押后 stop 帧驱动落地）：manual 不自动开窗，下句由举手开始
  const t4 = conn.texts.length;
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'start' })); await sleep(60);
  conn.ws.send(downPacket); await sleep(120);
  conn.ws.send(JSON.stringify({ type: 'tts', state: 'stop' })); await sleep(60);
  clock += 2000; feed(voiced, 1); await sleep(120);
  ok('I4a deferred stop landed', eng.session.pendingStopAt === 0 && eng.session.gate.hold === false);
  ok('I4b no auto relisten after answer (PTT)',
    !conn.texts.slice(t4).some((t) => { const o = JSON.parse(t); return o.type === 'listen' && o.state === 'start'; })
    && eng.session.listenOpen === false);

  // I5 窗未开点退下：stop=提交语义，无窗时 exit 不得盲发（云端会把空 stop 当提交）
  const t5 = conn.texts.length;
  eng.ctl('exit'); await sleep(60);
  ok('I5 exit without window sends no listen stop',
    !conn.texts.slice(t5).some((t) => { const o = JSON.parse(t); return o.type === 'listen' && o.state === 'stop'; }));

  // I6 举手后点退下：exit 必先提交再闭麦（评审 Major-1）——发 stop、窗态归位、闭麦后零上行
  const r6a = eng.ctl('bargeToggle'); await sleep(80);
  ok('I6a raise hand after exit works', r6a.ok === true && r6a.micWinOpen === true && eng.session.listenOpen === true);
  const t6 = conn.texts.length;
  eng.ctl('exit'); await sleep(80);
  ok('I6b exit commits and force-closes mic', eng.micWinOpen === false && eng.session.listenOpen === false
    && conn.texts.slice(t6).some((t) => { const o = JSON.parse(t); return o.type === 'listen' && o.state === 'stop'; }));
  const b6 = conn.binaries.length;
  feed(voiced, 6); await sleep(120);
  ok('I6c no uplink after exit closed mic', conn.binaries.length === b6, 'n=' + (conn.binaries.length - b6));

  // I7 断连场景（打桩 isReady）：断连中点「发言完毕」不虚假确认（emit lost、不发 stop）；
  //    断连中举手拒绝且状态不变；恢复后 exit 兜底清残留窗（评审二审 Minor-1/2）
  const r7a = eng.ctl('bargeToggle'); await sleep(80);           // 退下后再举手（bargeToggle 自动解静音）
  ok('I7a raise works again', r7a.ok === true && eng.session.listenOpen === true);
  const t7 = conn.texts.length;
  eng.socket.isReady = () => false;
  eng.ctl('bargeToggle'); await sleep(80);                        // 窗开着但连接断了点「发言完毕」
  ok('I7b offline commit emits lost not commit', eng.micWinOpen === false
    && evtN((e) => e.type === 'talk' && e.state === 'commit') === 1
    && evtN((e) => e.type === 'talk' && e.state === 'lost') === 1
    && !conn.texts.slice(t7).some((t) => { const o = JSON.parse(t); return o.type === 'listen' && o.state === 'stop'; }));
  const r7c = eng.ctl('bargeToggle');                             // 断连中举手：拒绝且态不变
  ok('I7c offline raise refused', r7c.ok === false && eng.micWinOpen === false
    && eng.session.listenOpen === true);                          // 残留旗号等 onReady/exit 兜底，不假清
  delete eng.socket.isReady;
  eng.ctl('exit'); await sleep(80);                               // 恢复后 exit 兜底提交残留窗归位
  ok('I7d exit commits pending window when ready', eng.session.listenOpen === false
    && conn.texts.slice(t7).some((t) => { const o = JSON.parse(t); return o.type === 'listen' && o.state === 'stop'; }));

  await eng.lessonStop();
  try { dec16.free(); enc24.free(); } catch (e) { /* noop */ }
  await cloud.close();
}

/* ================= main ================= */
(async () => {
  try {
    await testDeviceLayer();
    await testProtocol();
    await testEngine();
    testDsp();
    await testServerIdentity();
    await testSpeechSync();
    await testSpeechReport();
    await testManualBarge();
    await testPttProtocol();
  } catch (e) {
    OUT.push('THREW ' + (e && e.stack ? e.stack : String(e)));
    fails.push('UNCAUGHT');
  }
  OUT.push('');
  OUT.push('RESULT ' + count.pass + '/' + count.total + (fails.length ? ' FAILED: ' + fails.join(', ') : ' ALL PASS'));
  fs.writeFileSync(path.join(__dirname, '_xztest_result.txt'), OUT.join('\n'), 'ascii');
})();
