/**
 * 二期共享录音引擎（悬浮窗 overlay.html 与主面板 online_course_notes.html 复用）。
 *
 * 职责：
 * - Deepgram 流式 ASR 会话（经 preload 暴露的 window.llAsr，与悬浮窗原实现同源）；
 * - 开始/暂停/完成 三态状态机：pause 仅门控供帧，不关闭 WS 会话；
 * - 实时自动保存：final 句子到达后防抖 1.5s 调 /api/notes/autosave，另每 60s 兜底；
 * - 笔记合成：开始时读取既有正文为 base，本会话内容（转写全文/段落总结/截图）追加其后，
 *   单一写者原则——截图由调用方 recorder.addScreenshot(md) 纳入会话，避免与
 *   /api/vault/screenshot 的文件追加互相覆盖；
 * - 录制中标识：start/done 联动 /api/notes/recording on:true|false（主面板横幅数据源）。
 *
 * 事件（onEvent）：{type:'status'|'state'|'interim'|'final'|'saved'|'saving'|'error'|'level'}
 */
(function (global) {
    'use strict';

    var TOKEN_KEY = 'll_token';

    function LLRecorder(opts) {
        opts = opts || {};
        this.onEvent = opts.onEvent || function () {};
        this.getToken = opts.getToken || function () {
            // 四期：双存储（未勾选记住登录时 token 在 sessionStorage）
            return (global.llGetToken ? global.llGetToken() : (localStorage.getItem(TOKEN_KEY) || ''));
        };
        this.autoSaveMs = opts.autoSaveMs || 60000;   // 兜底周期
        this.debounceMs = opts.debounceMs || 1500;    // 句子级防抖

        this.state = 'idle';            // idle | recording | paused
        this.note = null;               // { path, name }
        this.baseContent = '';          // 会话开始前笔记既有正文
        this.transcript = '';           // 本次会话 final 全文
        this.finalLines = [];           // 四期：逐句 final 历史（SPA 片段切换后回填转写面板）
        this.sinceSummary = '';         // 上次总结以来新增（UI 侧总结逻辑使用）
        this.summaryLog = '';           // 段落总结累计（markdown）
        this.shotsLog = '';             // 截图 markdown 累计

        // 音频/会话内部状态
        this.audioCtx = null; this.analyser = null; this.procNode = null;
        this.mediaStream = null; this._fileTimer = null;
        this.pcm16 = null; this.chunkCursor = 0;
        this.offResult = null; this._debTimer = null; this._cycleTimer = null;
        this._saving = null;            // 进行中的保存 Promise（串行化）
        this._dirty = false;
        this._recSec = 0;               // 2026-09-28 积分：实际录制秒数（暂停停表）
        this._tickTimer = null;
    }

    // ---------------------------------------------------------------- HTTP
    LLRecorder.prototype.api = function (path, options) {
        var headers = { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + this.getToken() };
        return fetch(path, Object.assign({ headers: headers }, options || {}))
            .then(function (r) { return r.json().catch(function () { return { success: false, error: '非JSON响应' }; }); });
    };
    LLRecorder.prototype.emit = function (type, payload) {
        var ev = { type: type };
        if (payload) Object.assign(ev, payload);
        try { this.onEvent(ev); } catch (e) { /* 事件消费方异常不自毁 */ }
    };

    // ---------------------------------------------------------------- 音频工具（与悬浮窗原实现同源）
    function resampleTo16k(float32, inRate) {
        var ratio = inRate / 16000;
        var outLen = Math.floor(float32.length / ratio);
        var out = new Int16Array(outLen);
        for (var i = 0; i < outLen; i++) {
            var pos = i * ratio, idx = Math.floor(pos), frac = pos - idx;
            var a = float32[idx] || 0, b = float32[idx + 1] || a;
            var v = a + (b - a) * frac;
            if (v > 1) v = 1; else if (v < -1) v = -1;
            out[i] = v < 0 ? v * 32768 : v * 32767;
        }
        return out;
    }
    LLRecorder.prototype.resampleTo16k = resampleTo16k;

    function parseWavPcm(arrayBuffer) {
        var dv = new DataView(arrayBuffer);
        if (dv.byteLength < 12) return null;
        if (dv.getUint32(0, false) !== 0x52494646) return null; // RIFF
        var off = 12, fmt = { rate: 16000, ch: 1, bits: 16 }, dataStart = -1, dataLen = 0;
        while (off + 8 <= dv.byteLength) {
            var id = dv.getUint32(off, false);
            var size = dv.getUint32(off + 4, true);
            if (id === 0x666d7420) { // fmt
                fmt.rate = dv.getUint32(off + 12, true);
                fmt.ch = dv.getUint16(off + 10, true);
                fmt.bits = dv.getUint16(off + 14, true);
            } else if (id === 0x64617461) { dataStart = off + 8; dataLen = size; }
            off += 8 + size + (size % 2);
        }
        if (dataStart < 0) return null;
        var total = Math.floor(dataLen / 2);
        var f32 = new Float32Array(total);
        for (var i = 0; i < total; i++) f32[i] = dv.getInt16(dataStart + i * 2, true) / 32768;
        return { f32: f32, rate: fmt.rate };
    }

    /** 解码音频文件 → pcm16（供 UI 的"选择音频"入口复用） */
    LLRecorder.prototype.loadFile = function (file) {
        var self = this;
        self.emit('status', { text: '解析音频…' });
        return file.arrayBuffer().then(function (arr) {
            var tmp = new (global.AudioContext || global.webkitAudioContext)();
            return tmp.decodeAudioData(arr).catch(function () { return null; }).then(function (decoded) {
                var f32, rate;
                if (decoded) {
                    var n = decoded.length, ch = decoded.numberOfChannels;
                    f32 = new Float32Array(n);
                    for (var c = 0; c < ch; c++) {
                        var d = decoded.getChannelData(c);
                        for (var i = 0; i < n; i++) f32[i] += d[i] / ch;
                    }
                    rate = decoded.sampleRate;
                } else {
                    var parsed = parseWavPcm(arr);
                    if (!parsed) { tmp.close(); self.emit('error', { text: '无法解码该音频' }); return false; }
                    f32 = parsed.f32; rate = parsed.rate;
                }
                self.pcm16 = resampleTo16k(f32, rate);
                self.chunkCursor = 0;
                tmp.close().catch(function () {});
                self.emit('status', { text: '音频就绪：' + file.name + '（约 ' + (self.pcm16.length / 16000).toFixed(0) + ' 秒）' });
                return true;
            });
        });
    };

    // ---------------------------------------------------------------- 状态机
    /**
     * 开始录音。opts: { notePath, noteName, source:'loopback'|'mic'|'file', language }
     * 调用前 UI 须已完成笔记选择（独立选择窗 / 浏览器兜底新建）。
     */
    LLRecorder.prototype.start = async function (o) {
        if (this.state !== 'idle') return false;
        if (!global.llAsr) { this.emit('error', { text: 'Electron 桥不可用（请在桌面端打开）' }); return false; }
        if (!o || !o.notePath) { this.emit('error', { text: '未选择学习笔记' }); return false; }
        this.emit('status', { text: '获取 ASR 配置…' });
        var cfgResp = await this.api('/api/asr/config');
        if (!cfgResp.success) { this.emit('error', { text: 'ASR 配置失败: ' + (cfgResp.error || '') }); return false; }
        var cfg = cfgResp.data;
        if (o.language) cfg.language = o.language;

        this.note = { path: o.notePath, name: o.noteName || o.notePath };
        // 读取既有正文作为会话块基座（库为准，文件兜底）
        try {
            var cur = await this.api('/api/notes/content?path=' + encodeURIComponent(o.notePath));
            this.baseContent = (cur && cur.data && cur.data.exists) ? (cur.data.content || '') : '';
        } catch (e) { this.baseContent = ''; }
        this.transcript = ''; this.finalLines = []; this.sinceSummary = ''; this.summaryLog = ''; this.shotsLog = '';

        await global.llAsr.start(cfg);
        var self = this;
        this.offResult = global.llAsr.onResult(function (ev) {
            if (ev.type === 'interim') {
                self.emit('interim', { text: ev.text });
                self.emit('level', {});
            } else if (ev.type === 'final') {
                if (self.state !== 'recording') return;  // 暂停期丢弃迟到结果
                self.transcript += (self.transcript ? ' ' : '') + ev.text;
                self.finalLines.push(ev.text);
                self.sinceSummary += (self.sinceSummary ? ' ' : '') + ev.text + ' ';
                self.emit('final', { text: ev.text });
                self.markDirty();
            } else if (ev.type === 'error') {
                self.emit('error', { text: '识别错误: ' + ev.text });
            } else if (ev.type === 'close') {
                if (self.state !== 'idle') self.emit('status', { text: '识别连接关闭' });
            }
        });

        // 音源（四期：缺省 loopback；mic 为新增主音源；file 仅供演示脚本）
        var src = o.source || 'loopback';
        try {
            if (src === 'loopback') await this._startLoopback();
            else if (src === 'mic') await this._startMic();
            else await this._startFile();
        } catch (err) {
            var name = (err && err.name) || '';
            var hint = err;
            if (name === 'NotAllowedError' || name === 'SecurityError') {
                hint = (src === 'mic' ? '麦克风未授权，请在系统/浏览器设置中允许麦克风访问' : '未获得屏幕共享音频授权');
            } else if (name === 'NotFoundError' || name === 'OverconstrainedError') {
                hint = (src === 'mic' ? '未检测到可用麦克风设备' : '未检测到可用音频轨道');
            }
            this.emit('error', { text: '启动音源失败: ' + hint });
            await this._teardown();
            return false;
        }

        this.state = 'recording';
        this._recSec = 0;
        this._tickStart();
        this.emit('state', { state: this.state });
        this.emit('status', { text: '录制中 · 笔记保存到 ' + this.note.name });
        // 实时保存：周期兜底（句子级由 markDirty 防抖触发）
        this._cycleTimer = setInterval(function () { self.saveNow(); }, this.autoSaveMs);
        // 录制中标识（失败不阻断录音）
        this.api('/api/notes/recording', { method: 'POST', body: JSON.stringify({ path: this.note.path, on: true }) })
            .catch(function () {});
        return true;
    };

    LLRecorder.prototype.pause = function () {
        if (this.state !== 'recording') return false;
        this.state = 'paused';
        this._tickStop();   // 暂停期不计时（积分按实际录制时长）
        this.emit('state', { state: this.state });
        this.emit('status', { text: '已暂停（笔记保留）' });
        return true;
    };

    LLRecorder.prototype.resume = function () {
        if (this.state !== 'paused') return false;
        this.state = 'recording';
        this._tickStart();
        this.emit('state', { state: this.state });
        this.emit('status', { text: '录制中 · 笔记保存到 ' + this.note.name });
        return true;
    };

    // ------------------------------------------------ 录音时长计时（积分计费用）
    LLRecorder.prototype._tickStart = function () {
        var self = this;
        if (this._tickTimer) clearInterval(this._tickTimer);
        this._tickTimer = setInterval(function () {
            if (self.state === 'recording') self._recSec++;
        }, 1000);
    };
    LLRecorder.prototype._tickStop = function () {
        if (this._tickTimer) { clearInterval(this._tickTimer); this._tickTimer = null; }
    };

    /** 完成：末次保存 + 清录制标识 + 关会话。返回 {saved:boolean} */
    LLRecorder.prototype.done = async function () {
        if (this.state === 'idle') return { saved: false };
        this.emit('saving', { text: '正在保存学习笔记' });
        var secs = this._recSec;
        this._tickStop();
        var saved = await this.saveNow(true);
        await this._teardown();
        this.state = 'idle';
        this.emit('state', { state: this.state });
        if (this.note) {
            this.api('/api/notes/recording', { method: 'POST', body: JSON.stringify({ path: this.note.path, on: false }) })
                .catch(function () {});
        }
        // 2026-09-28 积分：录音转文字按实际时长上报扣分（失败不自毁，仅事件提示）
        if (secs > 0) {
            try {
                var cr = await this.api('/api/credits/asr-charge', { method: 'POST', body: JSON.stringify({ seconds: secs }) });
                if (cr && cr.success) {
                    this.emit('credit', { seconds: secs, minutes: cr.data.minutes, credits: cr.data.credits,
                                          balance: cr.data.balance, exempt_admin: !!cr.data.exempt_admin });
                } else {
                    this.emit('credit', { seconds: secs, error: (cr && cr.error) || '扣分上报失败' });
                }
            } catch (e) {
                this.emit('credit', { seconds: secs, error: String(e) });
            }
        }
        this.emit('status', { text: '已完成，笔记已保存' });
        this.emit('done', { saved: saved, note: this.note });
        return { saved: saved };
    };

    // ---------------------------------------------------------------- 实时保存
    LLRecorder.prototype.markDirty = function () {
        var self = this;
        this._dirty = true;
        if (this._debTimer) clearTimeout(this._debTimer);
        this._debTimer = setTimeout(function () { self.saveNow(); }, this.debounceMs);
    };

    /** UI 侧总结逻辑产出后回填（同样进入单一写者会话块） */
    LLRecorder.prototype.appendSummary = function (mdText) {
        this.summaryLog += (this.summaryLog ? '\n\n' : '') + mdText;
        this.sinceSummary = '';
        this.markDirty();
    };

    /** 截图 markdown（![](截图/xxx.png)）纳入会话，由 autosave 单写者入库 */
    LLRecorder.prototype.addScreenshot = function (markdown) {
        this.shotsLog += (this.shotsLog ? '\n\n' : '') + markdown;
        this.markDirty();
    };

    LLRecorder.prototype.buildContent = function () {
        var session = '# 听课笔记\n\n## 转写全文\n\n' + this.transcript +
            '\n\n## 段落总结\n\n' + (this.summaryLog || '') +
            ((this.shotsLog) ? '\n\n## 截图\n\n' + this.shotsLog + '\n' : '\n');
        var base = (this.baseContent || '').trim();
        if (!base) return session;
        return base + '\n\n---\n\n' + session;
    };

    /** 串行化保存；force=done() 末次保存。返回是否成功 */
    LLRecorder.prototype.saveNow = function (force) {
        var self = this;
        if (!this.note) return Promise.resolve(false);
        if (!this._dirty && !force) return Promise.resolve(true);
        var run = (this._saving || Promise.resolve()).then(function () {
            self._dirty = false;
            var content = self.buildContent();
            return self.api('/api/notes/autosave', {
                method: 'POST',
                body: JSON.stringify({ path: self.note.path, content: content }),
            }).then(function (r) {
                var ok = !!(r && r.success && r.data && r.data.success);
                self.emit('saved', { ok: ok, updated_time: ok ? (r.data.updated_time || '') : '', force: !!force });
                return ok;
            }).catch(function (e) {
                self.emit('saved', { ok: false, error: String(e) });
                return false;
            });
        });
        this._saving = run;
        return run;
    };

    // ---------------------------------------------------------------- 音源/会话内部
    LLRecorder.prototype._feedInt16 = function (int16) {
        if (this.state !== 'recording') return;  // 暂停=不供帧（保留 WS 会话）
        var BYTES = 3200; // 100ms
        var buf = int16.buffer;
        for (var off = 0; off + 2 <= buf.byteLength; off += BYTES) {
            var end = Math.min(off + BYTES, buf.byteLength);
            global.llAsr.sendChunk(buf.slice(off, end));
        }
    };

    /** 公用采集管线：MediaStream → analyser → ScriptProcessor → 16k PCM 喂帧 */
    LLRecorder.prototype._connectStream = function (stream) {
        this.mediaStream = stream;
        var ctx = new AudioContext();
        this.audioCtx = ctx;
        var srcNode = ctx.createMediaStreamSource(stream);
        this.analyser = ctx.createAnalyser(); this.analyser.fftSize = 512;
        var proc = ctx.createScriptProcessor(4096, 1, 1);
        this.procNode = proc;
        var self = this;
        proc.onaudioprocess = function (e) {
            var inp = e.inputBuffer.getChannelData(0);
            self._feedInt16(resampleTo16k(inp, ctx.sampleRate));
        };
        srcNode.connect(this.analyser);
        this.analyser.connect(proc);
        var sink = ctx.createGain(); sink.gain.value = 0;
        proc.connect(sink); sink.connect(ctx.destination);
    };

    LLRecorder.prototype._startLoopback = async function () {
        var stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
        var at = stream.getAudioTracks()[0];
        if (!at) {
            stream.getTracks().forEach(function (t) { t.stop(); });
            throw new Error('无音频轨道（本机 loopback 可能不可用）');
        }
        this._connectStream(stream);
    };

    /** 四期新增：麦克风音源（getUserMedia audio + 现有采帧管线复用） */
    LLRecorder.prototype._startMic = async function () {
        var stream;
        try {
            stream = await navigator.mediaDevices.getUserMedia({
                audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 }, video: false });
        } catch (err) {
            // 包装为带 name 的 Error，上层按类型给明确提示
            var e = new Error((err && err.message) || String(err));
            e.name = (err && err.name) || 'NotSupportedError';
            throw e;
        }
        if (!stream.getAudioTracks().length) {
            stream.getTracks().forEach(function (t) { t.stop(); });
            throw new Error('未检测到可用麦克风音轨');
        }
        this._connectStream(stream);
    };

    LLRecorder.prototype._startFile = async function () {
        if (!this.pcm16 || !this.pcm16.length) throw new Error('请先选择音频文件');
        var self = this;
        this.audioCtx = new AudioContext();
        this.analyser = this.audioCtx.createAnalyser(); this.analyser.fftSize = 512;
        var CHUNK_SAMPLES = 1600, PACE_MS = 60;
        this._fileTimer = setInterval(function () {
            if (self.state !== 'recording') return;  // 暂停：游标停走
            if (self.chunkCursor >= self.pcm16.length) {
                clearInterval(self._fileTimer); self._fileTimer = null;
                self.emit('status', { text: '文件音源播放完毕' });
                return;
            }
            var slice = self.pcm16.subarray(self.chunkCursor, self.chunkCursor + CHUNK_SAMPLES);
            self.chunkCursor += CHUNK_SAMPLES;
            var out = new Int16Array(slice);
            self._feedInt16(out);
        }, PACE_MS);
    };

    LLRecorder.prototype._teardown = async function () {
        if (this._cycleTimer) { clearInterval(this._cycleTimer); this._cycleTimer = null; }
        if (this._debTimer) { clearTimeout(this._debTimer); this._debTimer = null; }
        try { await global.llAsr.stop(); } catch (e) {}
        if (this.offResult) { this.offResult(); this.offResult = null; }
        if (this.procNode) { try { this.procNode.disconnect(); } catch (e) {} this.procNode = null; }
        if (this.mediaStream) { this.mediaStream.getTracks().forEach(function (t) { t.stop(); }); this.mediaStream = null; }
        if (this.audioCtx) { try { this.audioCtx.close(); } catch (e) {} this.audioCtx = null; }
        if (this._fileTimer) { clearInterval(this._fileTimer); this._fileTimer = null; }
        this.analyser = null;
    };

    global.LLRecorder = LLRecorder;
})(window);
