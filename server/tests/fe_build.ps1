# 批1 前端构建：Tailwind 预编译 + Lucide sprite
$ErrorActionPreference = 'Continue'
Set-Location e:\LLM\LectureLearnLoop\frontend
& npm.cmd run build *> e:\LLM\LectureLearnLoop\server\logs\fe_build.txt
"EXIT=$LASTEXITCODE" | Add-Content e:\LLM\LectureLearnLoop\server\logs\fe_build.txt
