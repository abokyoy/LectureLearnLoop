"""P4 音量诊断：用 pycaw 读默认 render endpoint 的音量/静音，必要时解除静音并设 80%。"""
import sys
import threading
import time

from ctypes import POINTER
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
from dotenv import load_dotenv  # noqa: F401  # 确保环境一致（可去）


def main():
    devices = AudioUtilities.GetSpeakers()
    print("default device:", devices)
    print("attrs:", [a for a in dir(devices) if not a.startswith('_')])
    inner = getattr(devices, "device", getattr(devices, "_device", devices))
    vol = devices.EndpointVolume  # pycaw 新版直接暴露 IAudioEndpointVolume
    v = vol.GetMasterVolumeLevelScalar()
    mute = vol.GetMute()
    print(f"master scalar={v:.3f} mute={mute}")
    if mute or v < 0.05:
        vol.SetMute(0, None)
        vol.SetMasterVolumeLevelScalar(0.8, None)
        print(f"unmuted + set 0.8 -> now scalar={vol.GetMasterVolumeLevelScalar():.3f} mute={vol.GetMute()}")

    # 再验证 loopback 采样（复用诊断脚本的 CDP evaluate）
    sys.path.insert(0, "tests")
    import p4_diag_audio as diag
    stop = threading.Event()

    def play_loop():
        import winsound
        while not stop.is_set():
            winsound.PlaySound(r"C:\Windows\Media\Alarm01.wav", winsound.SND_FILENAME | winsound.SND_ASYNC)
            time.sleep(3.0)
    threading.Thread(target=play_loop, daemon=True).start()
    time.sleep(0.3)
    res = diag.evaluate_await(diag.JS_SAMPLE, "loop", timeout_s=30)
    stop.set()
    import winsound
    winsound.PlaySound(None, winsound.SND_PURGE)
    print("LOOP after volume fix:", res)


if __name__ == "__main__":
    main()
