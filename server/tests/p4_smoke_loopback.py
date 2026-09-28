"""P4 第0步冒烟测试：Electron getDisplayMedia loopback 能否录到系统声音。

方法：winsound 循环播放系统提示音（真实声音进入播放混音），同时通过 CDP 让
Electron 主窗口执行 getDisplayMedia({video,audio}) + ScriptProcessor 采样，
断言 peak RMS > 0.0005。失败则按计划切换退路 A（外部录音→Deepgram 预录接口）。

前置：Electron 已带 --remote-debugging-port=9222 运行（tests/p2d_launch_electron.ps1 只跑前半段亦可）。
运行：python tests/p4_smoke_loopback.py
"""
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
WAV = r"C:\Windows\Media\Alarm01.wav"

JS_LOOPBACK_SAMPLE = """
(async () => {
  try {
    const st = await navigator.mediaDevices.getDisplayMedia({video: true, audio: true});
    const audioTracks = st.getAudioTracks();
    if (!audioTracks.length) { st.getTracks().forEach(t => t.stop()); return {ok: false, reason: 'NO_AUDIO_TRACK'}; }
    const ac = new (window.AudioContext || window.webkitAudioContext)();
    const src = ac.createMediaStreamSource(st);
    const proc = ac.createScriptProcessor(4096, 1, 1);
    const sink = ac.createGain(); sink.gain.value = 0;
    proc.connect(sink); sink.connect(ac.destination);
    let peak = 0, samples = 0, chunks = 0;
    await new Promise(res => {
      proc.onaudioprocess = (e) => {
        const d = e.inputBuffer.getChannelData(0);
        chunks += 1;
        for (let i = 0; i < d.length; i++) { const a = Math.abs(d[i]); if (a > peak) peak = a; }
        samples += d.length;
      };
      setTimeout(res, 5000);
    });
    st.getTracks().forEach(t => t.stop());
    try { ac.close(); } catch (e) {}
    return {ok: true, peak: peak, samples: samples, chunks: chunks, track: audioTracks[0].label};
  } catch (err) { return {ok: false, reason: String(err)}; }
})()
"""


def evaluate(expr: str, timeout_s: int = 30):
    targets = json.loads(urllib.request.urlopen(f"http://{CDP}/json/list", timeout=10).read())
    pages = [t for t in targets if t.get("type") == "page"]
    if not pages:
        raise RuntimeError("no CDP page target")
    s = ws_connect(pages[0]["webSocketDebuggerUrl"])
    s.settimeout(timeout_s)
    ws_send(s, json.dumps({"id": 1, "method": "Runtime.evaluate",
                           "params": {"expression": expr, "returnByValue": True,
                                      "awaitPromise": True}}).encode())
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            msg = ws_recv(s)
        except Exception as e:  # noqa: BLE001
            s.close()
            raise RuntimeError(f"ws recv failed: {e}")
        try:
            obj = json.loads(msg)
        except Exception:  # noqa: BLE001
            continue
        if obj.get("id") == 1:
            s.close()
            return obj.get("result", {}).get("result", {}).get("value")
    s.close()
    raise RuntimeError("evaluate timeout")


def main():
    # 1. 确认 Electron 活着
    try:
        urllib.request.urlopen(f"http://{CDP}/json/list", timeout=5).read()
    except Exception as e:  # noqa: BLE001
        print(f"FAIL: CDP {CDP} 不可连，先启动 Electron（--remote-debugging-port=9222）。err={e}")
        sys.exit(1)

    # 2. 后台线程持续循环播放提示音（喂给 loopback）
    stop = threading.Event()

    def play_loop():
        while not stop.is_set():
            winsound.PlaySound(WAV, winsound.SND_FILENAME | winsound.SND_ASYNC)
            time.sleep(3.0)  # Alarm01 约3s，循环触发
        winsound.PlaySound(None, winsound.SND_PURGE)

    t = threading.Thread(target=play_loop, daemon=True)
    t.start()
    time.sleep(0.5)  # 让声音先起来

    # 3. 在 Electron 里录 5 秒并算 peak
    result = evaluate(JS_LOOPBACK_SAMPLE, timeout_s=40)
    stop.set()
    winsound.PlaySound(None, winsound.SND_PURGE)

    print("loopback result:", json.dumps(result, ensure_ascii=False))
    if not result or not result.get("ok"):
        print("== SMOKE FAIL：系统声音 loopback 不可用 → 切退路A（准实时分段） ==")
        sys.exit(1)
    peak = float(result.get("peak", 0))
    if peak > 0.0005 and result.get("chunks", 0) > 10:
        print(f"== SMOKE PASS：peak={peak:.4f} track={result.get('track')} chunks={result.get('chunks')} ==")
        sys.exit(0)
    print(f"== SMOKE FAIL：peak={peak} 过低/无数据，RMS≈{peak:.6f} ==")
    sys.exit(1)


if __name__ == "__main__":
    main()
