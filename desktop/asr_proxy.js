/**
 * Deepgram 流式 ASR 会话管理（主进程持有，key 不落盘分发到渲染层）。
 * 对接 /api/asr/config 下发的参数：model=nova-2, language（默认 zh-CN，实测 multi 对中文返回空）,
 * encoding=linear16, sample_rate=16000, channels=1。
 */
const WebSocket = require('ws');

function buildUrl(cfg) {
  const p = new URLSearchParams({
    model: cfg.model || 'nova-2',
    language: cfg.language || 'zh-CN',
    encoding: cfg.encoding || 'linear16',
    sample_rate: String(cfg.sample_rate || 16000),
    channels: String(cfg.channels || 1),
    interim_results: 'true',
    punctuate: 'true',
    smart_format: 'true',
    utterance_end_ms: '1000',
    vad_events: 'true',
  });
  return `${cfg.ws_url || 'wss://api.deepgram.com/v1/listen'}?${p.toString()}`;
}

/**
 * 开启一个流式识别会话。
 * @param {object} cfg        /api/asr/config 的 data
 * @param {(ev:object)=>void} onEvent  字幕事件 {type:'interim'|'final'|'error'|'open'|'close', text}
 * @returns {{send:(buf:Buffer)=>void, close:()=>void}}
 */
function startSession(cfg, onEvent) {
  if (!cfg || !cfg.api_key) {
    onEvent({ type: 'error', text: '缺少 ASR 配置' });
    return { send() {}, close() {} };
  }
  const url = buildUrl(cfg);
  const ws = new WebSocket(url, { headers: { Authorization: `token ${cfg.api_key}` } });

  let open = false;
  const queue = [];

  ws.on('open', () => {
    open = true;
    onEvent({ type: 'open', text: '' });
    while (queue.length && ws.readyState === WebSocket.OPEN) {
      ws.send(queue.shift());
    }
  });

  ws.on('message', (msg) => {
    let j;
    try { j = JSON.parse(msg.toString()); } catch (e) { return; }
    if (j.type === 'Results' && j.channel && j.channel.alternatives && j.channel.alternatives[0]) {
      const alt = j.channel.alternatives[0];
      const text = (alt.transcript || '').trim();
      if (text) {
        onEvent({ type: j.is_final ? 'final' : 'interim', text, start: alt.start, end: alt.end });
      }
    } else if (j.type === 'Error') {
      onEvent({ type: 'error', text: JSON.stringify(j) });
    }
  });

  ws.on('error', (err) => onEvent({ type: 'error', text: err.message }));
  ws.on('close', (code) => onEvent({ type: 'close', text: `code=${code}` }));

  return {
    send(buf) {
      if (open && ws.readyState === WebSocket.OPEN) ws.send(buf);
      else if (queue.length < 2000) queue.push(buf); // 未就绪时暂存(上限~200s)
    },
    close() {
      try { if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) ws.close(); }
      catch (e) { /* ignore */ }
    },
  };
}

module.exports = { startSession, buildUrl };
