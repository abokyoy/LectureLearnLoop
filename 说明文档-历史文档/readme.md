# LectureLearnLoop 项目环境配置指南
本文档用于描述多设备（台式机/笔记本、有显卡/无显卡设备）的开发环境，确保代码可正常运行，重点解决依赖安装、Python 版本适配、显卡差异化配置等问题。


## 一、核心环境要求
### 1. 基础依赖
| 依赖项       | 版本要求                  | 说明                                  |
|--------------|---------------------------|---------------------------------------|
| Python       | 3.10.x（推荐 3.10.6）     | 统一使用一致的版本，避免兼容性问题（3.8~3.11 均可，3.10.6 已验证可用） |
| 虚拟环境     | venv（Python 自带）       | 隔离项目依赖，避免污染全局 Python 环境 |
| 依赖管理     | pip >= 22.0               | 确保能正常安装 requirements.txt 中的包 |


### 2. 设备差异化配置（显卡适配）
项目中 Whisper 语音转文字、PyTorch 相关功能需根据设备是否有 NVIDIA 显卡调整配置：
| 设备         | 硬件特点                | 关键配置差异                          |
|--------------|-------------------------|---------------------------------------|
| 有显卡电脑     | 有 NVIDIA 独立显卡      | 安装带 CUDA 的 PyTorch，启用 GPU 加速 |
| 无限卡电脑     | 无 NVIDIA 显卡（仅 CPU） | 安装 CPU 版 PyTorch，无需 CUDA        |


## 二、环境搭建步骤（通用流程）
以下步骤适用于所有设备，**差异化配置会在步骤 3 中单独标注**。


### 1. 安装 Python 3.10.6
1. 下载地址：[Python 3.10.6 官方安装包](https://www.python.org/downloads/release/python-3106/)  
   - Windows 选择 `Windows Installer (64-bit)`，Mac 选择 `macOS 64-bit universal2 installer`。
2. 安装时务必勾选：  
   - `Add Python 3.10 to PATH`（自动添加环境变量，避免后续命令找不到 Python）  
   - （可选）`Install for all users`（全局安装，多账号可用）。
3. 验证安装：  
   打开终端，执行以下命令，输出 `Python 3.10.6` 即成功：
   ```bash
   python --version
   pip --version
   ```


### 2. 克隆仓库并创建虚拟环境
1. 克隆远程仓库（已克隆可跳过）：
   ```bash
   # 进入存放项目的目录（示例：F:\LLM 或 E:\LLM）
   cd F:\LLM
   # 克隆仓库（SSH 方式，避免 HTTPS 代理问题）
   git clone git@github.com:abokyoy/LectureLearnLoop.git
   # 进入项目目录
   cd LectureLearnLoop
   ```

2. 创建并激活虚拟环境：
   ```bash
   # 创建虚拟环境（命名为 venv，默认存放在项目根目录）
   python -m venv venv

   # 激活虚拟环境（Windows 系统）
   # CMD 终端：
   venv\Scripts\activate
   # PowerShell 终端（若提示权限问题，先以管理员身份执行 Set-ExecutionPolicy RemoteSigned 并输入 Y）：
   .\venv\Scripts\Activate.ps1

   # 激活成功后，终端提示符前会显示 (venv)
   ```


### 3. 安装项目依赖（差异化配置）
根据设备是否有 NVIDIA 显卡，选择对应的依赖安装方式：

#### 场景 A：有显卡电脑（有 NVIDIA 显卡）
直接安装 `requirements.txt` 中的依赖（包含带 CUDA 的 PyTorch）：
```bash
# 安装依赖（确保已激活虚拟环境）
pip install -r requirements.txt

# 验证 GPU 配置是否生效：
python -c "import torch; print('GPU 可用：', torch.cuda.is_available())"
# 输出 "GPU 可用：True" 即成功，说明可调用 NVIDIA 显卡加速
```

#### 场景 B：无显卡电脑（无 NVIDIA 显卡）
需先修改 `requirements.txt` 中的 PyTorch 版本为 CPU 版，再安装：
1. 编辑 `requirements.txt`，找到以下 3 行并修改：
   ```txt
   # 原 GPU 版（删除或注释）
   # torch==2.1.0+cu118
   # torchaudio==2.1.0+cu118
   # torchvision==0.16.0+cu118

   # 替换为 CPU 版
   torch==2.1.0+cpu
   torchaudio==2.1.0+cpu
   torchvision==0.16.0+cpu
   ```

2. 安装依赖：
   ```bash
   # 安装修改后的依赖
   pip install -r requirements.txt

   # 验证 CPU 配置是否生效：
   python -c "import torch; print('使用 CPU 运行：', torch.device('cpu'))"
   # 输出 "使用 CPU 运行： cpu" 即成功，说明 PyTorch 已切换为 CPU 模式
   ```


### 4. 验证环境是否正常
安装完成后，通过运行项目核心功能（如 Whisper 语音转文字）验证环境：
```bash
# 1. 安装测试音频文件（若项目中无测试文件，可自行放一个 test.wav 到项目根目录）
# 2. 运行 Whisper 测试代码：
python -c "
import whisper
# 加载基础模型（CPU 版会自动用 CPU，GPU 版会自动用 GPU）
model = whisper.load_model('base')
# 处理测试音频（替换为你的音频文件名）
result = model.transcribe('test.wav')
# 输出转录结果
print('音频转录结果：', result['text'])
"
```
- 若能正常输出音频文字内容，说明环境配置成功；
- 若报错，优先检查 Python 版本（是否为 3.10.x）和 PyTorch 版本（是否与设备匹配）。


## 三、常见问题解决
### 1. 依赖安装失败（如 whisperx、mem0ai）
若遇到 `git clone` 失败（代理问题），手动克隆 GitHub 仓库并本地安装：
```bash
# 进入项目外临时目录
cd F:\LLM\temp_packages
# 克隆目标仓库（以 whisperx 为例）
git clone git@github.com:m-bain/whisperx.git
cd whisperx
# 切换到 requirements.txt 中指定的版本（d700b56）
git checkout d700b56c9c402058265ecce1d2dd4563e6dcdca6
# 本地安装
pip install .
# 回到项目目录继续安装其他依赖
cd F:\LLM\LectureLearnLoop
pip install -r requirements.txt
```

### 2. Python 版本不匹配（如 3.12 报错）
卸载当前 Python，重新安装 3.10.6，步骤：
1. 控制面板 → 卸载程序 → 找到 Python 3.12 → 卸载；
2. 按步骤 1 重新安装 Python 3.10.6，确保勾选 `Add to PATH`；
3. 删除原虚拟环境（`rmdir /s /q venv`），按步骤 2 重新创建虚拟环境。


