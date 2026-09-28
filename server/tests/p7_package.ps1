# P7 便携版打包：win-unpacked（离线方式，不依赖打包器下载）
# 原理：复制 Electron 官方 dist → 将应用源码注入 resources/app（Electron 原生查找路径）
$ErrorActionPreference = 'Stop'
$root = 'E:\LLM\LectureLearnLoop'
$dst  = Join-Path $root 'dist\win-unpacked'

if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }

# 1) Electron 运行时
Copy-Item -Recurse (Join-Path $root 'desktop\node_modules\electron\dist') $dst

# 2) 应用源码注入 resources/app
$app = Join-Path $dst 'resources\app'
New-Item -ItemType Directory -Path $app | Out-Null
Copy-Item (Join-Path $root 'desktop\main.js'),          (Join-Path $root 'desktop\preload.js'),
          (Join-Path $root 'desktop\asr_proxy.js'),     (Join-Path $root 'desktop\package.json') $app
# 运行时依赖 ws
Copy-Item -Recurse (Join-Path $root 'desktop\node_modules\ws') (Join-Path $app 'node_modules_ws_tmp')
New-Item -ItemType Directory -Path (Join-Path $app 'node_modules') | Out-Null
Move-Item (Join-Path $app 'node_modules_ws_tmp') (Join-Path $app 'node_modules\ws')

# 3) 主程序改名（仅改 electron.exe，其它 dll 不动）
Rename-Item (Join-Path $dst 'electron.exe') 'LectureLearnLoop.exe'

Write-Output ("OK size(MB): " + [math]::Round((Get-ChildItem $dst -Recurse | Measure-Object Length -Sum).Sum / 1MB, 1))
Write-Output ("EXE: " + (Get-Item (Join-Path $dst 'LectureLearnLoop.exe')).FullName)
