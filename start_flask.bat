@echo off
chcp 65001 >nul
echo ========================================
echo   LectureLearnLoop Flask Web版启动
echo ========================================
echo.

REM 检查虚拟环境
if not exist "venv\Scripts\activate.bat" (
    echo [错误] 未找到虚拟环境，请先创建虚拟环境
    echo 运行: python -m venv venv
    pause
    exit /b 1
)

REM 激活虚拟环境
echo [1/4] 激活虚拟环境...
call venv\Scripts\activate.bat

REM 检查Flask是否安装
echo [2/4] 检查依赖...
python -c "import flask" 2>nul
if errorlevel 1 (
    echo [提示] Flask未安装，正在安装依赖...
    pip install Flask Flask-CORS Flask-Session
)

REM 创建必要的目录
echo [3/4] 创建必要目录...
if not exist "logs" mkdir logs
if not exist "flask_session" mkdir flask_session
if not exist "static" mkdir static
if not exist "static\js" mkdir static\js
if not exist "static\css" mkdir static\css
if not exist "static\images" mkdir static\images

REM 检查关键文件
echo [4/5] 检查关键文件...
if not exist "app_flask.py" (
    echo [错误] 未找到 app_flask.py
    pause
    exit /b 1
)

if not exist "static\js\api.js" (
    echo [警告] 未找到 static\js\api.js，部分功能可能不可用
)

REM 启动Flask应用
echo [5/5] 启动Flask应用...
echo.
echo ========================================
echo   应用已启动！
echo   访问地址: http://localhost:5000
echo   按 Ctrl+C 停止服务器
echo ========================================
echo.

python app_flask.py

if errorlevel 1 (
    echo.
    echo ========================================
    echo   应用启动失败！
    echo   请检查上面的错误信息
    echo ========================================
    echo.
)

pause
