@echo off
echo 正在启动应用程序...
echo 切换到目标目录...
cd /d "E:\LLM\summary"

if %errorlevel% neq 0 (
    echo 错误：无法切换到目录 E:\LLM\summary
    pause
    exit /b 1
)

echo 激活虚拟环境...
call env\Scripts\activate

if %errorlevel% neq 0 (
    echo 错误：无法激活虚拟环境
    pause
    exit /b 1
)

echo 启动应用程序...
python app.py

