"""诊断：在 Electron 中分别采 麦克风(getUserMedia) 与 系统声音(loopback)，对比 peak。"""
from __future__ import annotations

import json
import sys
import threading
import time
import urllib.request
import winsound

sys.path.insert(0, "tests")
from p2d_cdp_check import ws_connect, ws_send, ws_recv  # noqa: E402

CDP = "127.0.0.1:9222"

JS_SAMPLE = """
async (kind) => {
  try {
    let st;
    if (kind === 'mic') {
      st = await navigator.mediaDevices.getUserMedia({audio: true});
    } else {
      st = await navigator.mediaDevices.getDisplayMedia({video: true, audio: true});
    }
    const tracks = st.getAudioTracks();
    if (!tracks.length) return {ok: false, reason: 'NO_AUDIO_TRACK'};
    const ac = new AudioContext();
    const src = ac.createMediaStreamSource(st);
    const proc = ac.createScriptProcessor(4096, 1, 1);
    const sink = ac.createGain(); sink.gain.value = 0;
    proc.connect(sink); sink.connect(ac.destination);
    let peak = 0, chunks = 0, nonZeroChunks = 0;
    await new Promise(res => {
      proc.onaudioprocess = (e) => {
        const d = e.inputBuffer.getChannelData(0);
        chunks += 1;
        let nz = false;
        for (let i = 0; i < d.length; i++) { const a = Math.abs(d[i]); if (a > peak) peak = a; if (a > 0.0005) nz = true; }
        if (nz) nonZeroChunks += 1;
      };
      setTimeout(res, 4000);
    });
    st.getTracks().forEach(t => t.stop());
    try { ac.close(); } catch (e) {}
    return {ok: true, peak: peak, chunks: chunks, nonZeroChunks: nonZeroChunks, label: tracks[0].label, rate: ac.sampleRate};
  } catch (err) { return {ok: false, reason: String(err)}; }
}
"""


def evaluate_await(expr_js: str, arg: str, timeout_s: int = 30):
    targets = json.loads(urllib.request.urlopen(f"http://{CDP}/json/list", timeout=10).read())
    pages = [t for t in targets if t.get("type") == "page"]
    s = ws_connect(pages[0]["webSocketDebuggerUrl"])
    s.settimeout(timeout_s)
    # 把 kind 作为实参立即调用
    expr = f"(({expr_js}))('{arg}')"
    ws_send(s, json.dumps({
        "id": 1, "method": "Runtime.evaluate",
        "params": {"expression": expr, "returnByValue": True, "awaitPromise": True},
    }).encode())
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            obj = json.loads(ws_recv(s))
        except Exception:  # noqa: BLE001
            continue
        if obj.get("id") == 1:
            s.close()
            if "error" in obj:
                print("CDP error:", json.dumps(obj["error"])[:400])
            res = obj.get("result", {})
            if res.get("exceptionDetails"):
                print("JS exception:", json.dumps(res["exceptionDetails"])[:400])
            return res.get("result", {}).get("value")
    s.close()
    raise RuntimeError("timeout")


def main():
    # 持续播放提示音（loopback 与麦克风都可能拾取）
    stop = threading.Event()

    def play_loop():
        while not stop.is_set():
            winsound.PlaySound(r"C:\Windows\Media\Alarm01.wav", winsound.SND_FILENAME | winsound.SND_ASYNC)
            time.sleep(3.0)
    threading.Thread(target=play_loop, daemon=True).start()
    time.sleep(0.3)

    mic = evaluate_await(JS_SAMPLE, "mic")
    print("MIC :", json.dumps(mic, ensure_ascii=False))
    loop = evaluate_await(JS_SAMPLE, "loop")
    print("LOOP:", json.dumps(loop, ensure_ascii=False))
    stop.set()
    winsound.PlaySound(None, winsound.SND_PURGE)


if __name__ == "__main__":
    main()
