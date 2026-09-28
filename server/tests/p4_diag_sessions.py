"""诊断3：winsound 播放时读取系统级 AudioMeterInformation（与 WASAPI 混音同源），
证明声音确实进入渲染管线；若 session peak>0 而 Electron loopback=0，则定性为捕获端问题。"""
from __future__ import annotations

import threading
import time
import winsound

from pycaw.pycaw import AudioUtilities


def main():
    stop = threading.Event()

    def play_loop():
        while not stop.is_set():
            winsound.PlaySound(r"C:\Windows\Media\Alarm01.wav", winsound.SND_FILENAME | winsound.SND_ASYNC)
            time.sleep(2.5)
    threading.Thread(target=play_loop, daemon=True).start()
    time.sleep(0.4)

    sessions = AudioUtilities.GetAllSessions()
    print(f"sessions: {len(sessions)}")
    for _ in range(3):
        lines = []
        for s in sessions:
            try:
                peak = s.AudioMeterInformation.MasterPeakValue
                if peak > 0:
                    lines.append(f"{s.Process.name if s.Process else '?':>24} pid={s.pid} peak={peak:.3f}")
            except Exception:  # noqa: BLE001
                continue
        print("active peaks:", lines or ["NONE — 系统内无任何可测播放活动"])
        time.sleep(1.0)

    stop.set()
    winsound.PlaySound(None, winsound.SND_PURGE)


if __name__ == "__main__":
    main()
