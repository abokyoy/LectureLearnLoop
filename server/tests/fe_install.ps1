# 批1 前端构建环境安装（npm 走 V2RAYN 代理）
$ErrorActionPreference = 'Continue'
$env:HTTP_PROXY = 'http://127.0.0.1:10808'
$env:HTTPS_PROXY = 'http://127.0.0.1:10808'
Set-Location e:\LLM\LectureLearnLoop\frontend
& npm.cmd install --no-audit --no-fund --loglevel=warn *> e:\LLM\LectureLearnLoop\server\logs\fe_npm_install.txt
"EXIT=$LASTEXITCODE" | Add-Content e:\LLM\LectureLearnLoop\server\logs\fe_npm_install.txt
