"""诊断2：loopback audio track 的 muted/enabled/readyState 及 enabled 强开后的采样。"""
from __future__ import annotations

import json
import sys
import threading
import time
import winsound

sys.path.insert(0, "tests")
from p4_diag_audio import evaluate_await  # noqa: E402

JS = """
async () => {
  try {
    const st = await navigator.mediaDevices.getDisplayMedia({video: true, audio: true});
    const t = st.getAudioTracks()[0];
    if (!t) return {ok:false, reason:'NO_TRACK'};
    const before = {muted: t.muted, enabled: t.enabled, readyState: t.readyState};
    t.enabled = true;
    t.onmute = () => {}; 
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
    const after = {muted: t.muted, enabled: t.enabled, readyState: t.readyState};
    st.getTracks().forEach(x => x.stop());
    try { ac.close(); } catch (e) {}
    return {ok: true, before, after, peak, chunks, settings: t.getSettings ? t.getSettings() : null};
  } catch (err) { return {ok: false, reason: String(err)}; }
}
"""


def main():
    stop = threading.Event()

    def play_loop():
        while not stop.is_set():
            winsound.PlaySound(r"C:\Windows\Media\Alarm01.wav", winsound.SND_FILENAME | winsound.SND_ASYNC)
            time.sleep(3.0)
    threading.Thread(target=play_loop, daemon=True).start()
    time.sleep(0.3)
    res = evaluate_await(JS, "x", timeout_s=40)
    stop.set()
    winsound.PlaySound(None, winsound.SND_PURGE)
    print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
