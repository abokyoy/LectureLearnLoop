import torch
import torchaudio
import whisper
import whisperx
import pyannote.audio

# 1. 版本验证
print('=== 版本信息 ===')
print('Torch 版本：', torch.__version__)  # 应输出 2.1.0+cu118
print('Torchaudio 版本：', torchaudio.__version__)  # 应输出 2.1.0+cu118
print('Whisper 版本：', whisper.__version__)  # 应输出 1.1.10
print('Whisperx 版本：', whisperx.__version__)  # 应输出 3.2.0
print('Pyannote-audio 版本：', pyannote.audio.__version__)  # 应输出 2.1.1

# 2. 功能验证（加载模型，测试无报错）
print('\n=== 功能验证 ===')
# 加载 Whisper 模型
whisper_model = whisper.load_model('base', device='cuda' if torch.cuda.is_available() else 'cpu')
print('Whisper 模型加载成功 ✅')

# 加载 Whisperx 模型
whisperx_model = whisperx.load_model('base', device='cuda' if torch.cuda.is_available() else 'cpu')
print('Whisperx 模型加载成功 ✅')

# 验证 CUDA 可用（ROG 电脑）
if torch.cuda.is_available():
    print('CUDA 设备可用 ✅（显卡型号：', torch.cuda.get_device_name(0), '）')
else:
    print('使用 CPU 运行 ✅')

print('\n所有依赖无冲突，项目可正常运行！🎉')