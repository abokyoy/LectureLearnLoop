"""诊断6：A) 单独进程同步播放的耗时（秒级=真在播，瞬时=失败）；B) 播放期间主进程读 meter。"""
import subprocess
import sys
import time

from pycaw.pycaw import AudioUtilities

WAV = r"C:\Windows\Media\Alarm01.wav"

# A: 纯播放耗时
t0 = time.time()
subprocess.run([sys.executable, "-c",
                f"import winsound; winsound.PlaySound(r'{WAV}', winsound.SND_FILENAME)"],
               timeout=30)
dur = time.time() - t0
print(f"sync play duration: {dur:.2f}s  (>1s 说明真实播放完成)")

# B: 后台进程播放时读 meter
p = subprocess.Popen([sys.executable, "-c",
                      f"import winsound; winsound.PlaySound(r'{WAV}', winsound.SND_FILENAME)"])
time.sleep(0.5)
sessions = AudioUtilities.GetAllSessions()
print("sessions:", len(sessions))
max_peak = 0.0
for _ in range(50):
    for s in sessions:
        try:
            max_peak = max(max_peak, s.AudioMeterInformation.MasterPeakValue)
        except Exception:  # noqa: BLE001
            pass
    time.sleep(0.1)
p.wait()
print(f"meter max_peak during subprocess play: {max_peak:.4f}")
