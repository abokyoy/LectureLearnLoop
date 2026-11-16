/**
 * 电脑小智 · 主进程设备层与会话编排（2026-11-05）。
 *
 * 定位：exe 客户端冒充一台 xiaozhi-esp32 设备（APK XiaozhiDevice.java 同款做法）：
 *  - 设备身份跟账号走（2026-11-05 v0.2.1）：上课/注册前先向服务器 GET
 *    /api/board/xzdevice/identity 领账号绑定的小智身份（设置页生成虚拟小智或绑真 ESP32）；
 *    本地 xz_voice.json 降级为缓存+迁移源：服务器未绑而本机有旧身份 → 自动 POST
 *    migrate 上传（用户无感，不再要码）；服务器未绑且本机无身份 → 面板引导去设置页绑定。
 *    未注入 serverApi（旧用法/测试）时回退本机种子派生旧行为，向后兼容。
 *  - MAC 本地派生算法：md5(seed+'|xiaozhi-device-v1')，首字节 (b&0xFE)|0x02 置本地位，
 *    UUID 一次生成永久复用。与服务端 services/xz_device.py 的 mac_from_seed 同款，
 *    **改一处两处同步**（否则存量迁移后 OTA 字节变化会被云端当新设备）。
 *  - register()：POST OTA（body 照抄固件 board.cc GetJson），服务端回 websocket
 *    地址+token；未激活回 6 位激活码，用户在 xiaozhi.me 控制台输一次即永久认机。
 *  - 防乒乓熔断（ROG v1.9.55 同 MAC 抢播事故借鉴）：连上很快就被另一端顶下线，
 *    连续 3 轮即停止重连，避免两台电脑无限互顶。
 *  - 语音会话：XzSocket（ws）+ libopus-wasm（Node 侧编解码实测 bestcorr 0.998）
 *    + xz_dsp（回声剥离 + 先停后判打断）。渲染窗只做采集/播放/UI，
 *    所有协议与 DSP 逻辑留在主进程 Node 内，可被 node 断言直接测试。
 *
 * 依赖全部注入（createXzVoice(deps)），测试可换成 mock：
 *   configDir, httpPost(url, bodyStr, headers) -> Promise<{status, text}>,
 *   serverApi(method, path, body) -> Promise<json.data>（可选：账号级身份，主进程带 token 实现）,
 *   WebSocketImpl, codec({createEncoder,createDecoder,...} 或 loader),
 *   windowOps({open, close, send(channel,payload), onMessage(cb)}),
 *   ipc (ipcMain), allowSender(sender) -> bool（IPC 呼叫方白名单，缺省放行）,
 *   now(), otaUrl
 */
'use strict';

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { XzSocket } = require('./xz_socket');
const { EchoGauge, BargeGate } = require('./xz_dsp');

const DEFAULT_OTA = 'https://api.tenclass.net/xiaozhi/ota/';
const BOUNCE_MS = 2500;              // 连上不足此时长即断 = 被顶一轮（防乒乓计数用）
const BOUNCE_MAX = 3;                // 连续被顶轮数上限 → 熔断停重连
// 重连递进封顶（课堂永不自动结束 2026-11-15 用户裁定）：待机断线/网络瞬断都走这条链，
// 只有用户下课（lessonStop）或被别的设备顶线熔断才停
const RECONNECT_LADDER = [800, 2000, 3000, 5000, 8000, 15000, 30000, 60000];
const MIC_RATE = 16000;
const MIC_FRAME_SAMPLES = 960;             // 60ms @16k
const SLIDE_SAMPLES = 4800;               // 300ms 滑动窗（对齐/回声处理粒度）

function md5hex(s) { return crypto.createHash('md5').update(s, 'utf8').digest('hex'); }

/** IPC 缓冲（ArrayBuffer/Buffer/TypedArray）→ Int16Array 视图（共享内存，不拷贝） */
function toI16(buf) {
  let u8;
  if (buf instanceof ArrayBuffer) u8 = new Uint8Array(buf);
  else if (ArrayBuffer.isView(buf)) u8 = new Uint8Array(buf.buffer, buf.byteOffset, buf.byteLength);
  else u8 = new Uint8Array(buf);   // 普通数组兜底
  return new Int16Array(u8.buffer, u8.byteOffset, Math.floor(u8.byteLength / 2));
}

/** 从种子派生固定 MAC（XiaozhiDevice.deviceId 同款算法） */
function macFromSeed(seed) {
  const d = crypto.createHash('md5').update(seed + '|xiaozhi-device-v1', 'utf8').digest();
  const parts = [];
  for (let i = 0; i < 6; i++) {
    let b = d[i];
    if (i === 0) b = (b & 0xFE) | 0x02;
    parts.push(('0' + b.toString(16)).slice(-2));
  }
  return parts.join(':');
}

function frameRms(i16) {
  // Int16Array → RMS（约 0..32767 标度）
  let sum = 0;
  for (let i = 0; i < i16.length; i++) sum += i16[i] * i16[i];
  return Math.sqrt(sum / Math.max(1, i16.length));
}

class XzVoiceEngine {
  constructor(deps) {
    this.deps = deps;
    this.cfgFile = path.join(deps.configDir, 'xz_voice.json');
    this.cfg = this._loadCfg();
    this.socket = null;
    this.session = null;      // {downRate, enc, dec, gauge, gate, slide, slideLen}
    this.status = 'idle';     // idle | registering | connecting | ready | error
    this.lastError = '';
    this.reconnect = { timer: null, tries: 0, wantLive: false };
    this.bounce = { lastOpenAt: 0, consec: 0, fused: false };
    this.identitySource = '';   // '' | local | server | local-legacy（resolveIdentity 后定）
    this.devType = '';
    this.needBind = false;      // 服务器未绑且本机无可迁移身份 → 面板引导去设置页
    // 听话窗（v0.2.5 手动打断，2026-11-06 用户裁定；2026-11-16 实弹改版：
    // manual 升级为 PTT 举手发言——用户裁定：点「举手」后系统持续听，
    // 直到点「发言完毕」才提交，根治“话说一半被云端 VAD 判停抢话”）：
    // auto=声控打断现状（服务端 VAD 判停）；manual=举手↔发言完毕（listen mode=manual）
    this.bargeMode = 'auto';    // auto | manual（引擎级字段，面板持久化记忆后同步）
    this.micWinOpen = true;     // manual 模式的麦窗开关；auto 模式恒 true 不参与逻辑
    this._idPromise = null;     // resolveIdentity 并发去重
    this._codecMod = deps.codec || null;
  }

  /* ---------------- 配置与身份 ---------------- */

  _loadCfg() {
    try { return JSON.parse(fs.readFileSync(this.cfgFile, 'utf8')); } catch (e) { return {}; }
  }
  _saveCfg() {
    try {
      fs.mkdirSync(path.dirname(this.cfgFile), { recursive: true });
      fs.writeFileSync(this.cfgFile, JSON.stringify(this.cfg, null, 2), 'utf8');
    } catch (e) { this._note('配置写盘失败：' + e.message); }
  }

  ensureIdentity() {
    let changed = false;
    if (!this.cfg.seed) { this.cfg.seed = crypto.randomUUID(); changed = true; }
    if (!this.cfg.device_mac) { this.cfg.device_mac = macFromSeed(this.cfg.seed); changed = true; }
    if (!this.cfg.client_uuid) { this.cfg.client_uuid = crypto.randomUUID(); changed = true; }
    if (changed) this._saveCfg();
  }

  get deviceId() { this.ensureIdentity(); return this.cfg.device_mac; }
  get clientId() { this.ensureIdentity(); return this.cfg.client_uuid; }

  /* ---------------- 账号级身份（2026-11-05 v0.2.1，register 前置步骤） ---------------- */

  /**
   * 领服务器身份（幂等 + 并发去重）。三态：
   *  bound → 直接用账号 MAC/UUID 冒充注册（identitySource='server'）；
   *  未绑但本机有旧身份 → 自动 migrate 上传后重领（用户无感，不再要码）；
   *  未绑且无可迁（或 migrate 被拒）→ needBind=true，本机身份仅留作缓存。
   *  无 serverApi / 请求异常（旧包对旧服务器）→ 回退本机身份 local-legacy，旧行为不变。
   */
  resolveIdentity() {
    if (this.identitySource === 'server') return Promise.resolve();
    if (this._idPromise) return this._idPromise;
    this._idPromise = this._resolveIdentity().finally(() => { this._idPromise = null; });
    return this._idPromise;
  }

  async _resolveIdentity() {
    if (typeof this.deps.serverApi !== 'function') {
      this.ensureIdentity();
      this.identitySource = 'local-legacy';
      this.needBind = false;
      return;
    }
    let d = null;
    try { d = await this.deps.serverApi('GET', '/api/board/xzdevice/identity'); }
    catch (e) {
      this._note('领账号小智身份失败，暂用本机身份：' + e.message);
      this.ensureIdentity();
      this.identitySource = 'local-legacy';
      return;
    }
    d = d || {};
    if (!d.bound && d.has_device === false && (this.cfg.device_mac || this.cfg.seed)) {
      // 存量迁移：本机已有且已认领过的身份上传账号（一次性的无感升级）
      this.ensureIdentity();
      try {
        await this.deps.serverApi('POST', '/api/board/xzdevice/migrate',
          { mac: this.cfg.device_mac, client_uuid: this.cfg.client_uuid });
        // 迁移成功后一律重领：不依赖 migrate 响应形态，也兼容服务端写库后的最新 state
        d = (await this.deps.serverApi('GET', '/api/board/xzdevice/identity')) || d;
      } catch (e) { this._note('本机身份迁移上传失败：' + e.message); }
    }
    if (d.bound && d.mac && d.client_uuid) {
      this.cfg.device_mac = String(d.mac);
      this.cfg.client_uuid = String(d.client_uuid);
      this._saveCfg();
      this.identitySource = 'server';
      this.devType = d.dev_type || '';
      this.needBind = false;
      // 账号级换机/换绑后旧的云端地址作废，强制重新 OTA
      this.cfg.wsUrl = ''; this.cfg.token = ''; this.cfg.activationCode = '';
      return;
    }
    this.identitySource = '';
    this.devType = '';
    this.needBind = true;    // 面板展示「去设置页绑定小智设备」引导
    this._emitState();
  }

  /* ---------------- OTA 注册 ---------------- */

  _otaBody() {
    // 照抄固件 ota.cc/board.cc：报 MAC/UUID/固件版本过去
    const mac = this.deviceId;
    return JSON.stringify({
      version: 2,
      language: 'zh-CN',
      flash_size: 16777216,
      minimum_free_heap_size: '120000',
      mac_address: mac,
      uuid: this.clientId,
      chip_model_name: 'esp32s3',
      chip_info: { model: 1, cores: 2, revision: 0, features: 0 },
      application: {
        name: 'xiaozhi-music-desktop', version: '1.0.0',
        compile_time: '2026-01-01T00:00:00Z', idf_version: 'v5.4', elf_sha256: '',
      },
      partition_table: [],
      ota: { label: 'ota_0' },
      board: { type: 'bread-compact-wifi', mac: mac },
    });
  }

  /** silent=true：课中后台重连专用——不做 registering/idle/error 状态翻转，
   *  面板保持「上课中」，失败只记 lastError（断线重连对课堂隐身） */
  async register(opts) {
    const silent = !!(opts && opts.silent);
    await this.resolveIdentity();
    if (this.needBind) {
      // EXE 不再自行生成新设备：未绑定就引导去设置页（替代旧「直接出码」流程）
      const e = new Error('账号还没有绑定小智设备：请在设置页「小智智能教室连接」生成虚拟小智或绑定已有 ESP32');
      if (!silent) { this.status = 'error'; this.lastError = e.message; this._emitState(); }
      else this.lastError = e.message;
      throw e;
    }
    this.ensureIdentity();
    if (!silent) { this.status = 'registering'; this._emitState(); }
    try {
      const url = this.deps.otaUrl || DEFAULT_OTA;
      const res = await this.deps.httpPost(url, this._otaBody(), {
        'Content-Type': 'application/json',
        'Activation-Version': '1',
        'Device-Id': this.deviceId,
        'Client-Id': this.clientId,
        'Accept-Language': 'zh-CN',
        'User-Agent': 'xiaozhi-music-desktop/1.0.0',
      });
      if (res.status >= 400) throw new Error('HTTP ' + res.status + '：' + this._trim(res.text));
      const o = JSON.parse(res.text);
      const r = { bound: true, code: '', message: '', wsUrl: '', token: '', wsVersion: 1 };
      if (o.websocket) {
        r.wsUrl = String(o.websocket.url || '');
        r.token = String(o.websocket.token || '');
        r.wsVersion = Number(o.websocket.version) >= 1 && Number(o.websocket.version) <= 3 ? Number(o.websocket.version) : 1;
      }
      if (o.activation) {
        r.code = String(o.activation.code || '');
        r.message = String(o.activation.message || '');
        if (r.code) r.bound = false;
      }
      if (r.wsUrl) {
        this.cfg.wsUrl = r.wsUrl;
        this.cfg.token = r.token;
        this.cfg.wsVersion = r.wsVersion;
      }
      this.cfg.activationCode = r.bound ? '' : r.code;
      this._saveCfg();
      if (!silent) { this.status = 'idle'; this._emitState(); }
      return r;
    } catch (e) {
      this.lastError = e.message;
      if (!silent) { this.status = 'error'; this._emitState(); }
      throw e;
    }
  }

  getState() {
    return {
      status: this.status,
      registered: !!this.cfg.wsUrl,
      bound: !this.cfg.activationCode && !!this.cfg.wsUrl,
      activationCode: this.cfg.activationCode || '',
      deviceMac: this.deviceId,
      clientId: this.clientId,
      wsVersion: this.cfg.wsVersion || 1,
      devType: this.devType || '',
      identitySource: this.identitySource,
      needBind: !!this.needBind,
      sessionActive: !!this.session,
      bargeMode: this.bargeMode,
      micWinOpen: this.micWinOpen,
      downRate: this.session ? this.session.downRate : 0,
      lastError: this.lastError,
    };
  }

  /* ---------------- 上课会话 ---------------- */

  async _loadCodec() {
    if (this._codecMod) return this._codecMod;
    this._codecMod = await import('libopus-wasm');
    return this._codecMod;
  }

  /** 开始上课：注册检查 → 建 socket → hello 就绪后 listenStart(auto) */
  async lessonStart() {
    if (this.session) return { started: true, note: '已在上课中' };
    // CodeReview P1-2：每次开课重领身份（轻量 GET）——运行期间在设置页换绑/解绑才能生效；
    // 课中重连（register 路径）不重置，保持一节课内身份稳定。
    this.identitySource = '';
    await this.resolveIdentity();
    if (this.needBind) return { started: false, needBind: true };
    if (!this.cfg.wsUrl) {
      const r = await this.register();
      if (!r.bound) return { started: false, needActivation: true, code: r.code, message: r.message };
    }
    const codec = await this._loadCodec();
    this._codecMod = codec;
    const enc = await codec.createEncoder({
      sampleRate: MIC_RATE, channels: 1, frameSize: MIC_FRAME_SAMPLES,
      application: codec.Application.Voip, bitrate: 24000,
    });
    const self = this;
    const session = {
      enc: enc,
      dec: null,               // hello 带回下行采样率后建
      downRate: 24000,
      gauge: new EchoGauge({ micRate: MIC_RATE, refRate: 24000 }),
      gate: new BargeGate({}, (a) => self._onGateEvent(a)),
      slide: new Int16Array(SLIDE_SAMPLES),  // 300ms 滑动窗（原始 mic）
      slideLen: 0,
      holdQ: [],              // hold 期暂存的下行帧（参考 holdQueue）：resume 补播 / abort 作废
      speechQ: [],            // 字幕跟播放同步 {text, atMs}：atMs=这句之前已收音频累计时长（播放位置预估）
      playT0: 0,              // 本轮首帧音频送面板出声的时刻（播放钟原点，mic 帧驱动字幕上报）
      holdStartMs: 0,         // hold 开始时刻（resume 时把字幕时间轴整体前移这段静音间隔）
      // 云端常快于实时把整句音频推完就发 tts stop；本地还在播 → stop 延迟到
      // 放音排空估计点才落状态机，否则“老师声音还在响、打断哨兵已下班”（E5 实弹 L6 实测）
      ttsStartMs: 0, ttsRecvMs: 0, pendingStopAt: 0,
      // 云端每轮回答（tts start）即关掉听话窗，需设备重新 listen start 才继续收声；
      // 真 ESP32 固件每次播完自动重开。窗开合状态跟在这里，落地 stop 时才补开、
      // abort 路径已重开的不重复发（重发会截断用户刚开头的活）
      listenOpen: false,
      closed: false,
    };
    this.session = session;
    this.reconnect.wantLive = true;
    this.reconnect.tries = 0;
    this.bounce = { lastOpenAt: 0, consec: 0, fused: false };   // 新一轮开课重置熔断计数
    this._clearReconnect();
    this._connectSocket(session);
    return { started: true };
  }

  _connectSocket(session) {
    const self = this;
    const socket = new XzSocket({
      url: this.cfg.wsUrl, token: this.cfg.token, version: this.cfg.wsVersion || 1,
      deviceId: this.deviceId, clientId: this.clientId,
      WebSocketImpl: this.deps.WebSocketImpl, now: this._now,
      listener: {
        onOpen() {
          self.bounce.lastOpenAt = self._now();
          self._emit({ type: 'sock', note: 'open' });
        },
        async onReady(sessionId, sampleRate, frameDuration) {
          if (session.closed) return;
          self.status = 'ready';
          // 重连计数只在真连上时清零：曾漏了这步，待机断线每轮烧 1 次配额，
          // 长课攒满 5 次就误判「重连失败」把用户踢出课堂（2026-11-15 实弹）
          self.reconnect.tries = 0;
          try {
            const codec = self._codecMod;
            session.dec = await codec.createDecoder({ sampleRate: sampleRate, channels: 1 });
            session.downRate = sampleRate;
            session.gauge = new EchoGauge({ micRate: MIC_RATE, refRate: sampleRate });
          } catch (e) { self._note('下行解码器创建失败：' + e.message); }
          // auto：开课即开服务端 VAD 听话窗（与固件一致）；manual（PTT）：
          // 不预开窗——收声窗只由用户点「举手」打开，免得云端 VAD 乱判停；
          // 重连评审修复：窗态不变量跨重连保持——举手途中断线重开 manual 窗，
          // 否则陈旧 listenOpen 归零（不带着旧旗号在新 socket 上盲发 stop）
          if (self.bargeMode !== 'manual') {
            socket.listenStart('auto');
            session.listenOpen = true;
          } else if (self.micWinOpen) {
            socket.listenStart('manual');
            session.listenOpen = true;
          } else {
            session.listenOpen = false;
          }
          self._emitState();
          self._emit({ type: 'ready', sessionId, downRate: sampleRate, frameDuration });
        },
        onStt(text) { self._emit({ type: 'stt', text }); },
        onTtsStart() {
          self._emit({ type: 'tts', state: 'start' });
          const now = self._now();
          // CodeReview P1-2：上一轮押后 stop 未落地就被新一轮 start 抢跑（云端连答/mic 停顿）：
          // 残余句子先补报再复位，存档脚本不丢句（被打断轮已由 abort 清空，此处自然 no-op）
          self._flushSpeechQ(session);
          session.listenOpen = false;            // 云端开答即关听话窗（固件同语义）
          session.ttsStartMs = now; session.ttsRecvMs = 0; session.pendingStopAt = 0;
          session.speechQ = []; session.playT0 = 0; session.holdStartMs = 0;   // 新一轮：字幕钟复位（上轮残余已在 stop/abort 时清算）
          session.gate.ttsStart(now);
          // 手动模式（用户裁定）：老师开口说话=学生说完了，自动闭麦，
          // 根治"采集到老师声音→哨兵又打断→无限自我打断"循环
          if (self.bargeMode === 'manual' && self.micWinOpen) {
            self.micWinOpen = false;
            self._emit({ type: 'micwin', open: false });
          }
        },
        onTtsSentence(text) {
          // 打断后在途丢弃窗内的残余句子连字幕一起吞（v1.9.101：只丢音频不丢字幕，
          // 用户仍看到老师"话没停"，等于打断没用）
          if (session.gate.shouldDropIncoming(self._now())) return;
          // 字幕跟声音同步（2026-11-06 用户裁定 A 方案）：云端常快于实时预推文字，
          // 到达即上黑板会让字幕跑在声音前、打断后"声没了字幕还在"。改为入队，
          // 播放钟（首帧出声起，mic 帧驱动）走到这句的播放位置才 _emit 上报；
          // 云端按"句文字→句音频"流式推送，故此刻的已收音频累计时长=这句的播放起点。
          // 软上限 500 句（CodeReview P2-3，与 holdQ 100 帧硬顶对称）：mic 帧被节流等异常时防队列无界增长
          session.speechQ.push({ text: text, atMs: session.ttsRecvMs });
          if (session.speechQ.length > 500) self._flushSpeechQ(session);
        },
        onTtsStop() {
          self._emit({ type: 'tts', state: 'stop' });
          // 收到的音频还没播完：把 stop 押后到排空估计点（mic 帧驱动落地，见 handleMicFrame）
          const now = self._now();
          const drainEnd = session.ttsStartMs + session.ttsRecvMs + 800;
          if (drainEnd > now) { session.pendingStopAt = drainEnd; }
          else { session.pendingStopAt = 0; session.gate.ttsStop(now); self._flushSpeechQ(session); self._reopenListen(session); }
        },
        onEmotion(emotion) { self._emit({ type: 'emotion', emotion }); },
        onAudio(opus) { self._handleDownAudio(session, opus); },
        onClose(reason) {
          self._emit({ type: 'sock', note: 'closed:' + reason });
          // 断线=云端本轮文本推送终止，但已送面板的音频仍会播完（CodeReview P2-4：
          // 断线≠打断，这里补报排队句使字幕匹配将要播完的声音，与 stop 收口同语义）
          if (session && !session.closed) self._flushSpeechQ(session);
          // 防乒乓熔断（ROG v1.9.55 同 MAC 抢播事故借鉴）：连上不足 BOUNCE_MS 就被顶下线，
          // 连续 BOUNCE_MAX 轮即停——两台电脑同账号互顶时不能无限轮流“各抢半句话”。
          // 正常待机断线（连够时长后 close）重置计数，不污染熔断判定。
          if (self.reconnect.wantLive && session && !session.closed && self.bounce.lastOpenAt) {
            if (self._now() - self.bounce.lastOpenAt < BOUNCE_MS) {
              self.bounce.consec += 1;
              if (self.bounce.consec >= BOUNCE_MAX) {
                self.bounce.fused = true;
                self.bounce.consec = 0;
                self.reconnect.wantLive = false;
                self._clearReconnect();
                self._emit({ type: 'error', message: '这台小智已在别的电脑上课中（连续被顶下线 ' + BOUNCE_MAX + ' 次，已停止重连）。请到另一台电脑下课，或在设置页解绑后重新绑定。' });
                self._emitState();
                return;
              }
            } else {
              self.bounce.consec = 0;
            }
          }
          self._maybeReconnect();
        },
        onError(msg) { self._note(msg); self._emit({ type: 'error', message: msg }); },
      },
    });
    this.socket = socket;
    socket.connect();
  }

  /** 下行 opus → 解码 → 打断闸门（在途丢弃/退下静音）→ ttsRing 参考 + 送面板播放 */
  _handleDownAudio(session, opus) {
    const now = this._now();
    if (!session.dec) return;
    if (session.gate.shouldDropIncoming(now)) return;  // abort 后在途帧丢弃：持续到 tts stop（带兜底阀）
    if (session.gate.muted) return;                     // 退下后静音闸
    let pcm;
    try { pcm = session.dec.decode(opus); } catch (e) { this._note('解码失败：' + e.message); return; }
    if (!pcm || !pcm.length) return;
    const i16 = pcm instanceof Int16Array ? pcm : Int16Array.from(pcm);
    session.ttsRecvMs += (i16.length / session.downRate) * 1000;   // 排空估计：已收音频总时长
    session.gauge.pushRef(i16, session.downRate);       // 回声参考始终留副本（hold 期也不能断参考）
    const frame = { pcm: Buffer.from(i16.buffer, i16.byteOffset, i16.byteLength), rate: session.downRate };
    if (session.gate.hold) {
      // hold 期下行帧不丢（参考 v1.9.110 holdQueue）：误触 resume 后补播不缺一帧；
      // 真打断由 abort 分支清空作废。上限 ~100 帧(6s) 防爆内存
      if (session.holdQ.length < 100) session.holdQ.push(frame);
      return;
    }
    if (!session.playT0) session.playT0 = now;   // 出声=播放钟起（字幕从此按播放进度上报）
    this._toPanel('play', frame);
  }

  /** 字幕跟播放同步：本轮已收声播完/收口，队列里剩余句子全部补报（课件存档脚本不丢句）；
   *  容错缺字段旧 session（手工构造/测试桩），任何路径不得抛断事件链 */
  _flushSpeechQ(session) {
    const q = session.speechQ || []; session.speechQ = [];
    for (const it of q) this._emit({ type: 'tts', state: 'sentence', text: it.text });
  }

  /** 字幕跟播放同步：本轮作废（被打断/被顶掉），没播到的句子永不上板——声音字幕同生共死 */
  _clearSpeechQ(session) {
    session.speechQ = [];
  }

  /**
   * 上行 mic 帧（渲染窗采集的 16k Int16 原始 PCM，60ms/帧）。
   * 路径：滑动窗累积 → 回声剥离（300ms 粒度对齐+逐窗掩蔽）→ 取窗尾 60ms 编码发送；
   *       能量哨兵喂 BargeGate（用原始帧能量，剥离不能影响"听到我说话"的判定）。
   */
  handleMicFrame(buf) {
    const session = this.session;
    if (!session || !session.enc || session.closed) return;
    const i16 = toI16(buf);
    const frame = i16.length >= MIC_FRAME_SAMPLES ? i16.subarray(0, MIC_FRAME_SAMPLES) : i16;
    const now = this._now();

    // 0) 押后的 tts stop 到点落地（本地排空估计走完，哨兵才下班）；同点重开听话窗。
    //    hold 中不拆台（CodeReview P2-2）：holdQ 音频/面板 held 现场留给 resume/abort 处置，
    //    stop 押后再试下一帧（BargeGate hold 超 1.6s 会自动发 resume，不会卡死）
    if (session.pendingStopAt && now >= session.pendingStopAt && !session.gate.hold) {
      session.pendingStopAt = 0;
      session.gate.ttsStop(now);
      this._flushSpeechQ(session);        // 声音播完=字幕收口，剩余句子补报（押后 stop 路径）
      this._reopenListen(session);
    }

    // M) 手动模式（PTT，2026-11-16 实弹改版）：闭麦=没有听话窗，零上行（旧静音帧
    //    保活手法只为服务端 VAD 窗存在，现在窗只在举手期间开）；开麦时真帧上行但
    //    哨兵不喂，押后 stop/字幕播放钟照常被帧驱动
    if (this.bargeMode === 'manual') {
      if (!this.micWinOpen) {
        this._drainSubtitleClock(session, now, false);
        return;
      }
      // 开麦：真帧走回声剥离+上行（供云端识别），但哨兵不喂，字幕钟照常
      this._drainSubtitleClock(session, now, true);
      this._micUplinkFrame(session, frame, now);
      return;
    }

    // 1) 打断哨兵（原始帧能量，auto 模式）
    const acts = session.gate.onFrame(frameRms(frame), 60, now);
    for (const a of acts) this._applyGateAction(session, a);

    // 1b) 字幕跟播放同步（A 方案）：播放钟走到句子的播放位置才上报（mic 帧驱动，同 pendingStopAt 模式）；
    //     排在哨兵之后：voiced 首帧即 hold，同帧冻住字幕钟零漏网（abort 则整队作废，resume 由时间轴前移补偿）
    this._drainSubtitleClock(session, now, true);

    this._micUplinkFrame(session, frame, now);
  }

  /** 字幕播放钟 drain（三处共用：auto 1b / manual 开麦 / manual 闭麦）：
   *  freezeOnHold=true 时 hold 中冻钟（哨兵可能活跃的路径）；manual 闭麦态 hold 永假，传 false 等价 */
  _drainSubtitleClock(session, now, freezeOnHold) {
    if (freezeOnHold && session.gate.hold) return;
    if (!session.playT0 || !session.speechQ.length) return;
    while (session.speechQ.length && now - session.playT0 >= session.speechQ[0].atMs) {
      this._emit({ type: 'tts', state: 'sentence', text: session.speechQ.shift().text });
    }
  }

  /** 上行链路（auto/manual 共用）：滑动窗累积 → 回声剥离（开麦后老师余音仍在放，剥离照做）→ 编码发送 */
  _micUplinkFrame(session, frame, now) {
    // 2) 滑动窗（原始 PCM 入窗，窗口不足 60ms 不发）
    const s = session.slide;
    if (session.slideLen + frame.length <= SLIDE_SAMPLES) {
      s.set(frame, session.slideLen);
      session.slideLen += frame.length;
    } else {
      const drop = session.slideLen + frame.length - SLIDE_SAMPLES;
      s.copyWithin(0, drop);
      s.set(frame, SLIDE_SAMPLES - frame.length);
      session.slideLen = SLIDE_SAMPLES;
    }
    if (session.slideLen < MIC_FRAME_SAMPLES) return;

    // 3) 回声剥离：处理满窗，取尾部 60ms
    let outFrame = frame;
    if (session.slideLen >= SLIDE_SAMPLES / 2) {
      const win = s.subarray(0, session.slideLen);
      const cleaned = session.gauge.process(win, now);
      outFrame = cleaned.subarray(cleaned.length - MIC_FRAME_SAMPLES);
    }

    // 4) 编码发送
    try {
      const packet = session.enc.encode(outFrame);
      if (this.socket && this.socket.isReady()) this.socket.sendAudio(Buffer.from(packet.buffer, packet.byteOffset, packet.byteLength));
    } catch (e) { this._note('编码失败：' + e.message); }
  }

  _onGateEvent() { /* 观测钩子（voiced 累计等），编排动作走 _applyGateAction */ }

  _applyGateAction(session, a) {
    if (a.action === 'hold') {
      if (!session.holdStartMs) session.holdStartMs = this._now();   // 字幕时间轴要补偿这段静音间隔
      this._toPanel('hold', {});
    } else if (a.action === 'resume') {
      // 误触解除：先放行面板出声，再补播 hold 期暂存帧（面板 held 标志会拦 play，顺序不能反）
      this._toPanel('resume', {});
      if (session.holdStartMs) {
        const dh = this._now() - session.holdStartMs; session.holdStartMs = 0;
        // CodeReview P1-1：字幕钟已在走才需要补偿暂停段；若 hold 开始时首帧尚未出声
        // （全部帧在 holdQ），resume 才起钟，atMs 本就以接收序相对新原点，再补 dh 会慢一个 hold 时长
        if (session.playT0) { for (const q of session.speechQ) q.atMs += dh; }
      }
      if (!session.playT0 && session.holdQ.length) session.playT0 = this._now();
      const q = session.holdQ; session.holdQ = [];
      for (const f of q) this._toPanel('play', f);
    } else if (a.action === 'abort') {
      session.holdQ = [];       // 被打断这一轮的暂存帧作废
      session.holdStartMs = 0;  // CodeReview P2-1：防异常路径（abort 后无 stop 重入 hold）时 dh 含旧值
      this._clearSpeechQ(session);   // 没播到的句子一并作废：打断后黑板不再残留没讲的字幕
      // 确认打断：发 abort + 重开一轮 listen + 清播放缓冲。参考 bargeIn 是
      // abort → listen start(auto) 单发：中间不插 listenStop（"stop 再 start"是早期
      // 误读，abort 紧挨的多余 listen stop 会被云端当取消，反把这一轮收声弄丢）
      if (this.socket) {
        this.socket.abort();
        this.socket.listenStart('auto');
        session.listenOpen = true;
      }
      this._toPanel('flush', {});
      this._emit({ type: 'barge' });
    }
  }

  /** 面板控制指令 */
  ctl(cmd, arg) {
    const session = this.session;
    if (cmd === 'exit') {
      // 退下：静音闸 + 停当前播报，连接保留（可直接再"继续"）
      if (session) { session.gate.exit(this._now()); this._toPanel('flush', {}); }
      // stop 只在窗真开着且连接就绪时发（PTT 语义下 stop=提交发言，没窗时盲发会
      // 多提交一次；评审二审 Minor-2：断连中发只会触发「未连接」误报错误，与 commit 分支同口径）
      if (this.socket && this.socket.isReady() && session && session.listenOpen) { this.socket.listenStop(); session.listenOpen = false; }
      // 评审 Major-1：退下一律闭麦——否则举手后点退下留下 micWinOpen=true/
      // listenOpen=false 分裂态：麦开分支照常零上行、按钮还卡在「发言完毕」
      if (this.bargeMode === 'manual' && this.micWinOpen) {
        this.micWinOpen = false;
        this._emit({ type: 'micwin', open: false });
      }
      return { ok: true };
    }
    if (cmd === 'resumeListen') {
      if (session) session.gate.unmute();
      // manual（PTT）：继续听只解静音，收声窗仍由用户点「举手」打开
      if (this.bargeMode !== 'manual' && this.socket && this.socket.isReady()) { this.socket.listenStart('auto'); if (session) session.listenOpen = true; }
      return { ok: true };
    }
    if (cmd === 'abort') {
      if (this.socket) this.socket.abort();
      return { ok: true };
    }
    if (cmd === 'setMode') {                 // 'auto' | 'manual'（面板记忆同步，无 session 也安全）
      const m = arg === 'manual' ? 'manual' : 'auto';
      const session = this.session;
      // 切走时若正 hold 在半截（auto 误触现场）：先放行补播不留哑音，再换模式。
      // gate 内部标志必须同步清掉（与 onFrame 自发 resume 同口径），否则 manual 下
      // 无人喂 onFrame，hold 永久卡死：押后 stop 不能落地、开麦字幕钟永久冻结
      if (session && session.gate.hold) {
        session.gate.hold = false;
        session.gate.voicedMs = 0;
        session.gate.lastResumeMs = this._now();
        this._applyGateAction(session, { action: 'resume' });
      }
      this.bargeMode = m;
      this.micWinOpen = (m === 'auto');      // 手动=默认闭麦；回 auto=恢复现状恒开
      if (m === 'manual' && session) session.slideLen = 0;   // 清滑窗防旧帧串入
      this._emit({ type: 'mode', mode: m, micWinOpen: this.micWinOpen });
      return { ok: true, mode: m, micWinOpen: this.micWinOpen };
    }
    if (cmd === 'bargeToggle') {             // 手动模式「举手/发言完毕」按钮（PTT）
      if (this.bargeMode !== 'manual') return { ok: false, error: '非手动模式' };
      const session = this.session;
      if (!session) return { ok: false, error: '未在上课' };
      if (this.micWinOpen) {
        // 发言完毕：本路发言唯一提交点——发 listen stop，云端据此整段送 STT 并回答；
        // 不再靠服务端 VAD 判停（旧坑：用户换气/想词就被提前提交抢话）
        this.micWinOpen = false;
        if (this.socket && this.socket.isReady() && session.listenOpen) {
          this.socket.listenStop();
          session.listenOpen = false;
          this._emit({ type: 'talk', state: 'commit' });
        } else {
          // 评审二审 Minor-1：断连中点发言完毕不得虚假确认——窗没提交成功，
          // 发 lost 让面板如实提示（listenOpen 残留旗号由重连 onReady 归位兜底）
          this._emit({ type: 'talk', state: 'lost' });
        }
      } else {
        // 评审 Minor-2：连接未就绪（拨号中/后台重连）举手不得置位——
        // 否则留下麦开无窗分裂态，对着没开的窗说话还会虚假提交
        if (!(this.socket && this.socket.isReady())) {
          return { ok: false, error: '连接未就绪，请稍候再举手' };
        }
        this.micWinOpen = true;
        session.slideLen = 0;                // 清窗：开麦首帧不混入闭麦前的旧声音
        // 举手即打断老师并开始持续送话；mode=manual 告诉云端不要自行判停，
        // 直到收到 listen stop（发言完毕）才提交整段
        this.socket.abort();
        this.socket.listenStart('manual');
        session.listenOpen = true;
        const g = session.gate;
        g.hold = false; g.voicedMs = 0;
        // 退下静音中点「说话」：一并解静音，否则问了问题听不到回答（半死状态只剩双击字幕区可解）
        if (g.muted) g.unmute();
        // 仅在老师真在播报时才开丢弃窗（与哨兵 abort 只在 play 态触发同口径）；
        // 否则 idle 点「说话」会把丢弃窗白打开，下一轮播报被整轮吞掉
        if (g.mode === 'play') {
          g.bargeGuard = true;
          g.dropUntil = Number.MAX_SAFE_INTEGER; g.dropSafetyMs = this._now() + 12000;
        }
        session.holdQ = [];
        session.holdStartMs = 0;
        this._clearSpeechQ(session);
        this._toPanel('flush', {});
        this._emit({ type: 'barge' });
      }
      this._emit({ type: 'micwin', open: this.micWinOpen });
      return { ok: true, micWinOpen: this.micWinOpen };
    }
    return { ok: false, error: '未知指令：' + cmd };
  }

  async lessonStop() {
    this.reconnect.wantLive = false;
    this._clearReconnect();
    const session = this.session;
    this.session = null;
    if (session) {
      session.closed = true;
      try { if (session.gate && session.gate.hold) this._toPanel('resume', {}); } catch (e) { /* 面板已关 */ }
      try { if (session.enc) session.enc.free(); } catch (e) { /* noop */ }
      try { if (session.dec) session.dec.free(); } catch (e) { /* noop */ }
    }
    if (this.socket) { this.socket.close(); this.socket = null; }
    this.status = 'idle';
    this._emitState();
    return { stopped: true };
  }

  /** 每轮回答落地后重开听话窗（用户插话能被继续听到）；退下静音/已开/断开都不重发。
   *  manual（PTT）不自动开窗：下一句由用户点「举手」主动开始 */
  _reopenListen(session) {
    if (this.bargeMode === 'manual') return;
    if (!this.socket || !this.socket.isReady() || session.closed || session.listenOpen) return;
    if (session.gate.muted) return;              // 退下状态：由 resumeListen 手动重开
    this.socket.listenStart('auto');
    session.listenOpen = true;
    this._emit({ type: 'listen', note: 'reopen_after_stop' });
  }

  _maybeReconnect() {
    if (this.bounce.fused) return;   // 熔断后不再自动重连（开课/手动重试才重置）
    if (!this.reconnect.wantLive || !this.session || this.session.closed) return;
    // 课中云端待机断线（道别后 close）属常态，首连提速到 800ms 减少丢话窗口；
    // 不设失败上限（2026-11-15 用户裁定：没点下课=同一堂课还在上，DNS 瞬断
    // GetAddrInfo 曾撞 5 次窗口被踢「请下课后再点上课」）——递进封顶 60s 无限重试，
    // 真断网也只是后台空转，恢复后老师经「续讲指导语」无缝接上（见 lecture_board）
    const delay = RECONNECT_LADDER[Math.min(this.reconnect.tries, RECONNECT_LADDER.length - 1)];
    this.reconnect.tries += 1;
    if (this.reconnect.tries === 4) {
      // 连续失败超 10 秒才弱提示一次（连上后 tries 清零，正常待机重连不会触发）
      this._emit({ type: 'error', message: '课堂网络暂时不通，后台持续自动重连中——恢复后接着上这堂课，不用下课重开' });
    }
    this._emit({ type: 'sock', note: 'reconnect_in:' + delay });
    this._clearReconnect();        // 旧链未跑就先撤：多个 onClose 迟到会让重连计时器叠排
    this.reconnect.timer = setTimeout(async () => {
      this.reconnect.timer = null;
      if (!this.reconnect.wantLive || !this.session || this.session.closed) return;
      try {
        // silent：重连全程不翻面板状态，课中保持「上课中」
        const r = await this.register({ silent: true });   // 重取 OTA：token 可能已换新
        // 评审 W1：OTA 往返期间用户可能已下课——不复査就建连会把僵尸 socket 留到下次开课，
        // 且 null session 进 onReady 抛未捕获异常
        if (!this.reconnect.wantLive || !this.session || this.session.closed) return;
        if (!r.bound) {
          this._note('设备绑定失效，后台继续重试；可到设置页重新绑定接入点');
          this._maybeReconnect();
          return;   // 旧语义在这里断链，把可恢复的瞬态故障变成了死局
        }
        const old = this.socket;
        if (old) { try { old.close(); } catch (e) { /* noop */ } }
        this._connectSocket(this.session);
      } catch (e) {
        this._note('重连注册失败，继续重试：' + e.message);
        this._maybeReconnect();
      }
    }, delay);
    if (this.reconnect.timer.unref) this.reconnect.timer.unref();
  }

  _clearReconnect() {
    if (this.reconnect.timer) { clearTimeout(this.reconnect.timer); this.reconnect.timer = null; }
  }

  /* ---------------- 通道：面板 / 事件 ---------------- */

  get _now() { return this.deps.now || Date.now; }

  _toPanel(channel, payload) {
    try { if (this.deps.windowOps) this.deps.windowOps.send(channel, payload); } catch (e) { /* 面板未开 */ }
  }
  _emit(evt) {
    this._toPanel('evt', evt);
    try { if (this.deps.onEvent) this.deps.onEvent(evt); } catch (e) { /* 观察器异常不断链 */ }
  }
  _emitState() { this._emit({ type: 'state', state: this.getStatus() }); }
  _note(msg) { this.lastError = String(msg); this._emit({ type: 'log', message: msg }); }
  _trim(s) { return String(s == null ? '' : s).slice(0, 200); }

  /** 渲染窗 → 主进程消息入口（preload 桥过来的 channel 已定） */
  onPanelMessage(msg) {
    if (!msg || typeof msg !== 'object') return;
    if (msg.kind === 'mic') { this.handleMicFrame(msg.pcm); return; }
    if (msg.kind === 'ctl') { const r = this.ctl(msg.cmd, msg.arg); this._emit({ type: 'ctl', cmd: msg.cmd, result: r }); }
  }

  /* ---------------- 测试辅助 ---------------- */

  getStatus() { return this.getState(); }

  dispose() {
    this.lessonStop();
  }
}

/**
 * 组装并接 IPC（Electron 主进程调用；测试传空 ipc 即可跳过）。
 * 返回 engine 实例。
 */
function createXzVoice(deps) {
  const engine = new XzVoiceEngine(deps);
  const ipc = deps.ipc;
  if (ipc && typeof ipc.handle === 'function') {
    // 安全闸：语音 IPC 只接语音窗的呼叫（主窗口加载远程 Flask 页，共享 preload 不能
    // 让它驱动麦/上下课）。未注入 allowSender 时全放行，保持 node 断言直接组装的用法。
    const allow = typeof deps.allowSender === 'function' ? deps.allowSender : () => true;
    const guard = (fn) => (e, ...args) => {
      if (!allow(e && e.sender)) return { error: 'sender not authorized' };
      return fn(e, ...args);
    };
    ipc.handle('xz:register', guard(() => engine.register()));
    ipc.handle('xz:state', guard(() => engine.getState()));
    ipc.handle('xz:start', guard(() => engine.lessonStart()));
    ipc.handle('xz:stop', guard(() => engine.lessonStop()));
    ipc.handle('xz:ctl', guard((e, cmd, arg) => engine.ctl(cmd, arg)));
    ipc.on('xz:mic', (e, pcmBuf) => { if (allow(e && e.sender)) engine.handleMicFrame(pcmBuf); });
    ipc.on('xz:panelMsg', (e, msg) => { if (allow(e && e.sender)) engine.onPanelMessage(msg); });
  }
  return engine;
}

module.exports = { createXzVoice, XzVoiceEngine, macFromSeed, frameRms, DEFAULT_OTA, MIC_RATE, MIC_FRAME_SAMPLES };
