@echo off
echo ================================
echo 🧼 正在清理 Windsurf 配置与缓存...
echo ================================

:: 1. 关闭相关进程
echo 🔪 正在关闭 Windsurf 和 MCP 相关进程...
taskkill /F /IM windsurf.exe >nul 2>&1
taskkill /F /IM uvx.exe >nul 2>&1
taskkill /F /IM python.exe >nul 2>&1
taskkill /F /IM node.exe >nul 2>&1

:: 2. 删除配置目录
echo 🗑️ 删除配置文件夹...
rd /S /Q "%APPDATA%\Windsurf"
rd /S /Q "%USERPROFILE%\.windsurf"
rd /S /Q "%LOCALAPPDATA%\Windsurf"
rd /S /Q "%LOCALAPPDATA%\Temp\windsurf"

:: 3. 清除 uvx 缓存
echo 🧹 清除 uvx 缓存...
rd /S /Q "%USERPROFILE%\AppData\Local\uv\cache"

:: 4. 清理注册表（可选）
echo 🧼 清理注册表项（如果存在）...
reg delete "HKCU\Software\Windsurf" /f >nul 2>&1
reg delete "HKLM\Software\Windsurf" /f >nul 2>&1

echo ✅ 清理完成！请重新启动 Windsurf。
pause
