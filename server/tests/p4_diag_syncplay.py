"""诊断4：同步阻塞播放（确保真在播）同时读 session meter + Electron loopback 采样。"""
from __future__ import annotations

import json
import sys
import threading
import time
import winsound

from pycaw.pycaw import AudioUtilities

sys.path.insert(0, "tests")
from p4_diag_audio import evaluate_await  # noqa: E402
from p4_diag_track import JS as JS_TRACK  # noqa: E402


def meter_watch(stop, out):
    sessions = AudioUtilities.GetAllSessions()
    max_peak = 0.0
    while not stop.is_set():
        for s in sessions:
            try:
                p = s.AudioMeterInformation.MasterPeakValue
                max_peak = max(max_peak, p)
            except Exception:  # noqa: BLE001
                pass
        time.sleep(0.1)
    out["max_peak"] = max_peak


def main():
    stop = threading.Event()
    out = {}
    threading.Thread(target=meter_watch, args=(stop, out), daemon=True).start()

    def play_sync():
        # 阻塞式连播 3 次（每次约3.5秒）
        for _ in range(3):
            if stop.is_set():
                break
            winsound.PlaySound(r"C:\Windows\Media\Alarm01.wav", winsound.SND_FILENAME)

    threading.Thread(target=play_sync, daemon=True).start()
    time.sleep(0.5)

    res = evaluate_await(JS_TRACK, "x", timeout_s=40)
    stop.set()
    winsound.PlaySound(None, winsound.SND_PURGE)
    print("ELECTRON LOOPBACK:", json.dumps(res, ensure_ascii=False))
    print("SYSTEM METER max peak during playback:", out.get("max_peak"))


if __name__ == "__main__":
    main()
