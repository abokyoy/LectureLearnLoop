"""诊断7：Electron 页面内 OscillatorNode 外放 440Hz 音，同时 getDisplayMedia loopback 自采。
若 peak>0 → 捕获管线正常（此前 winsound 情形特殊）；若 =0 → 本机渲染端点驱动级静音，切退路。"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, "tests")
from p4_diag_audio import evaluate_await  # noqa: E402

JS = """
async () => {
  try {
    const out = new AudioContext();
    const osc = out.createOscillator();
    const g = out.createGain();
    g.gain.value = 0.5;
    osc.connect(g); g.connect(out.destination);
    osc.start();
    const st = await navigator.mediaDevices.getDisplayMedia({video: true, audio: true});
    const t = st.getAudioTracks()[0];
    if (!t) { osc.stop(); return {ok:false, reason:'NO_TRACK'}; }
    const ac = new AudioContext();
    const src = ac.createMediaStreamSource(st);
    const proc = ac.createScriptProcessor(4096, 1, 1);
    const sink = ac.createGain(); sink.gain.value = 0;
    proc.connect(sink); sink.connect(ac.destination);
    let peak = 0, chunks = 0;
    await new Promise(res => {
      proc.onaudioprocess = (e) => { const d = e.inputBuffer.getChannelData(0); chunks++; for (let i=0;i<d.length;i++){const a=Math.abs(d[i]); if(a>peak)peak=a;} };
      setTimeout(res, 4000);
    });
    osc.stop(); st.getTracks().forEach(x => x.stop());
    try { ac.close(); } catch (e) {}
    try { out.close(); } catch (e) {}
    return {ok: true, peak, chunks};
  } catch (err) { return {ok: false, reason: String(err)}; }
}
"""

print(json.dumps(evaluate_await(JS, "x", timeout_s=40), ensure_ascii=False))
