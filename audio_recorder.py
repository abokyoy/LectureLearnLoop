import pyaudio
import wave
import numpy as np
import threading
import time
import os

# ----- 配置 -----
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100
DEVICE_INDEX_KEYWORD = "CABLE Output"
OUTPUT_DIR = "recorded_audio_segments"
SILENCE_THRESHOLD = 0.005 # 触发静音的最小音量
SILENCE_SECONDS = 1.5     # 连续静音多久后切分段落
MAX_RECORD_SECONDS = 30   # 最大录制时长，到时强制切分文件

# --------------------------

stop_event = threading.Event()

def find_device_index(p, device_name_keyword):
    """根据关键字查找音频设备索引"""
    for i in range(p.get_device_count()):
        dev_info = p.get_device_info_by_index(i)
        if device_name_keyword.lower() in dev_info['name'].lower() and dev_info['maxInputChannels'] > 0:
            return i
    return None

def record_audio():
    """
    主要录制逻辑，负责音频捕获和文件切分。
    """
    p = pyaudio.PyAudio()
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    try:
        device_index = find_device_index(p, DEVICE_INDEX_KEYWORD)
        if device_index is None:
            raise Exception("未找到指定的音频输入设备。")

        stream = p.open(format=FORMAT,
                        channels=CHANNELS,
                        rate=RATE,
                        input=True,
                        frames_per_buffer=CHUNK,
                        input_device_index=device_index)

        print("开始录制音频... 按 Ctrl+C 停止。")
        print(f"音频将保存到目录: ./{OUTPUT_DIR}")

        frames = []
        silence_frames = 0
        is_recording = False
        
        while not stop_event.is_set():
            data = stream.read(CHUNK, exception_on_overflow=False)
            audio_np = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
            
            is_silent = np.max(np.abs(audio_np)) < SILENCE_THRESHOLD
            
            # 如果当前是静音帧
            if is_silent:
                if is_recording:
                    silence_frames += 1
                
                # 如果连续静音超过阈值且frames不为空，则认为一个音频片段结束
                if is_recording and silence_frames >= int(SILENCE_SECONDS * RATE / CHUNK) and len(frames) > 0:
                    print(f"检测到静音，保存片段 ({len(frames) * CHUNK / RATE:.2f} 秒)...")
                    filename = os.path.join(OUTPUT_DIR, f"segment_{int(time.time())}.wav")
                    with wave.open(filename, 'wb') as wf:
                        wf.setnchannels(CHANNELS)
                        wf.setsampwidth(p.get_sample_size(FORMAT))
                        wf.setframerate(RATE)
                        wf.writeframes(b''.join(frames))
                    frames = []
                    is_recording = False
                    silence_frames = 0
                
            # 如果当前是非静音帧
            else:
                is_recording = True
                silence_frames = 0
                frames.append(data)
            
            # 达到最大录制时长，强制保存片段
            if len(frames) >= int(MAX_RECORD_SECONDS * RATE / CHUNK):
                print(f"达到最大录制时长，强制保存片段 ({len(frames) * CHUNK / RATE:.2f} 秒)...")
                filename = os.path.join(OUTPUT_DIR, f"segment_force_{int(time.time())}.wav")
                with wave.open(filename, 'wb') as wf:
                    wf.setnchannels(CHANNELS)
                    wf.setsampwidth(p.get_sample_size(FORMAT))
                    wf.setframerate(RATE)
                    wf.writeframes(b''.join(frames))
                frames = []
                is_recording = False
                silence_frames = 0

    except KeyboardInterrupt:
        print("\n收到退出信号...")
    except Exception as e:
        print(f"发生错误: {e}")
    finally:
        print("正在停止录制...")
        stop_event.set()
        if 'stream' in locals():
            if stream.is_active():
                stream.stop_stream()
            stream.close()
        p.terminate()
        print("录制程序已停止。")

if __name__ == "__main__":
    record_audio()