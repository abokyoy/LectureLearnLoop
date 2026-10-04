# 批1 一键重部署：构建前端产物 + 重启主后端（Flask 非 debug 模式模板有缓存，改模板必须重启）
$ErrorActionPreference = 'Continue'
Set-Location e:\LLM\LectureLearnLoop\frontend
& npm.cmd run build *> e:\LLM\LectureLearnLoop\server\logs\fe_build.txt
"BUILD_EXIT=$LASTEXITCODE" | Add-Content e:\LLM\LectureLearnLoop\server\logs\fe_build.txt
& powershell -ExecutionPolicy Bypass -File e:\LLM\LectureLearnLoop\server\tests\fe_restart_6001.ps1
