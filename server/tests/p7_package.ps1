# P7 便携版打包：win-unpacked（离线方式，不依赖打包器下载）
# 原理：复制 Electron 官方 dist → 将应用源码注入 resources/app（Electron 原生查找路径）
# 2026-10-15 客户测试版：默认注入公网入口（贝锐穿透 9992），写 resources/app/server_url.txt；本地开发包可传 -ServerUrl ''
param([string]$ServerUrl = 'http://289f32s031.oicp.vip:9992')
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
# 客户版默认服务器地址（main.js 按文件存在性读取；改地址无需重新打包，直接改此 txt）
if ($ServerUrl) { Set-Content -Path (Join-Path $app 'server_url.txt') -Value $ServerUrl -NoNewline -Encoding ascii }
Write-Output ("SERVER_URL: " + $(if ($ServerUrl) { $ServerUrl } else { '(none, local default)' }))

# 3) 主程序改名（仅改 electron.exe，其它 dll 不动）
Rename-Item (Join-Path $dst 'electron.exe') 'LectureLearnLoop.exe'

Write-Output ("OK size(MB): " + [math]::Round((Get-ChildItem $dst -Recurse | Measure-Object Length -Sum).Sum / 1MB, 1))
Write-Output ("EXE: " + (Get-Item (Join-Path $dst 'LectureLearnLoop.exe')).FullName)
