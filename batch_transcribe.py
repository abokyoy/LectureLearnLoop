import os
import whisper
import torch
import sys

def batch_transcribe_audio_files(folder_path):
    """
    批量转录指定文件夹下的所有.wav音频文件。
    """
    if not torch.cuda.is_available():
        print("警告: 未检测到CUDA设备，将使用CPU进行转录，速度会非常慢。")
        device = "cpu"
    else:
        print(f"使用 {torch.cuda.get_device_name(0)} 进行转录。")
        device = "cuda"

    try:
        print("正在加载 Whisper 'large-v2' 模型...")
        model = whisper.load_model("large-v2", device=device)
        print("模型加载完成。")
    except Exception as e:
        print(f"加载模型时发生错误: {e}")
        return

    if not os.path.isdir(folder_path):
        print(f"错误: 文件夹 '{folder_path}' 不存在。请检查路径是否正确。")
        return

    audio_files = [f for f in os.listdir(folder_path) if f.endswith('.wav')]
    if not audio_files:
        print(f"在文件夹 '{folder_path}' 中未找到任何 .wav 文件。")
        return

    audio_files.sort()  # 按文件名排序，通常可以按时间顺序处理

    print(f"在文件夹 '{folder_path}' 中找到 {len(audio_files)} 个音频文件。")
    print("--- 开始批量转录 ---")

    results = {}
    for filename in audio_files:
        file_path = os.path.join(folder_path, filename)
        print(f"\n正在转录文件: {filename}")
        
        try:
            # 使用模型进行转录，并强制指定语言为中文
            result = model.transcribe(file_path, language="zh", fp16=True, beam_size=5)
            text = result["text"].strip()
            
            if text:
                print(f"转录结果: {text}")
                results[filename] = text
            else:
                print("转录结果为空。")
                results[filename] = "（转录失败或结果为空）"
        except Exception as e:
            print(f"转录文件 '{filename}' 时发生错误: {e}")
            results[filename] = f"错误: {e}"

    print("\n--- 批量转录完成 ---")
    print("总览:")
    for filename, text in results.items():
        print(f"文件: {filename}\n结果: {text}\n")

if __name__ == "__main__":
    # 请将下面的路径修改为你的音频文件夹的绝对路径
    folder_to_transcribe = r"E:\LLM\summary\debug_audio_segments"
    batch_transcribe_audio_files(folder_to_transcribe)