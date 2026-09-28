"""诊断5：后台线程阻塞播放 winsound，主线程轮询 session meter（COM 已初始化）。"""
from __future__ import annotations

import threading
import time
import winsound

from pycaw.pycaw import AudioUtilities


def main():
    stop = threading.Event()

    def play_loop():
        while not stop.is_set():
            try:
                winsound.PlaySound(r"C:\Windows\Media\Alarm01.wav", winsound.SND_FILENAME)  # 阻塞 ~3.5s
            except Exception as e:  # noqa: BLE001
                print("play error:", e)
                return
    t = threading.Thread(target=play_loop, daemon=True)
    t.start()

    sessions = AudioUtilities.GetAllSessions()
    print("total sessions:", len(sessions), [(s.Process.name if s.Process else '?') for s in sessions])
    max_peak = 0.0
    seen = set()
    for _ in range(40):
        for s in sessions:
            try:
                p = s.AudioMeterInformation.MasterPeakValue
                if p > 0:
                    name = s.Process.name if s.Process else "?"
                    seen.add(name)
                    max_peak = max(max_peak, p)
            except Exception:  # noqa: BLE001
                pass
        # 定期刷新会话列表（新进程播放会新建 session）
        if _ % 10 == 9:
            sessions = AudioUtilities.GetAllSessions()
        time.sleep(0.1)
    stop.set()
    winsound.PlaySound(None, winsound.SND_PURGE)
    print(f"max_peak={max_peak:.4f} active_processes={seen or 'NONE'}")


if __name__ == "__main__":
    main()
