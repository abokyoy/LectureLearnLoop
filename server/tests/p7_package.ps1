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
          (Join-Path $root 'desktop\asr_proxy.js'),     (Join-Path $root 'desktop\package.json'),
          (Join-Path $root 'desktop\xz_socket.js'),     (Join-Path $root 'desktop\xz_dsp.js'),
          (Join-Path $root 'desktop\xz_voice.js'),      (Join-Path $root 'desktop\xz_speech.js'),
          (Join-Path $root 'desktop\xz_mic_probe.js'),  (Join-Path $root 'desktop\xiaozhi_voice.html') $app
# 运行时依赖：ws（语音协议）+ libopus-wasm（主进程 Opus 编解码，无额外运行时依赖）
New-Item -ItemType Directory -Path (Join-Path $app 'node_modules') | Out-Null
foreach ($m in @('ws', 'libopus-wasm')) {
  Copy-Item -Recurse (Join-Path $root ('desktop\node_modules\' + $m)) (Join-Path $app ('node_modules\' + $m))
}
# 客户版默认服务器地址（main.js 按文件存在性读取；改地址无需重新打包，直接改此 txt）
if ($ServerUrl) { Set-Content -Path (Join-Path $app 'server_url.txt') -Value $ServerUrl -NoNewline -Encoding ascii }
Write-Output ("SERVER_URL: " + $(if ($ServerUrl) { $ServerUrl } else { '(none, local default)' }))

# 3) 主程序改名（仅改 electron.exe，其它 dll 不动）
Rename-Item (Join-Path $dst 'electron.exe') 'LectureLearnLoop.exe'

# 4) 打包闸门：注入件相对 require 闭包自检（新增模块忘拷=客户机启动即报 Cannot find module，必须打包时拦下）
foreach ($f in (Get-ChildItem $app -Filter '*.js')) {
  foreach ($mm in [regex]::Matches((Get-Content $f.FullName -Raw), "require\('(\./[\w\-]+)'\)")) {
    $dep = Join-Path $app (($mm.Groups[1].Value -replace '^\./', '') + '.js')
    if (-not (Test-Path $dep)) { throw ("REQUIRE_GATE MISSING: " + $f.Name + ' -> ' + $mm.Groups[1].Value) }
  }
}
Write-Output 'REQUIRE_GATE: OK'
# 同闸门扩展到 HTML 本地 <script src>（页面引了却忘拷 = 客户机功能静默瘫痪，同样必须拦下）
# 只锚定 script 标签，双/单引号与 ./ 前缀都认，远程 src 跳过（评审：裸 src= 正则会误报 data-src/漏报带路径）
foreach ($h in (Get-ChildItem $app -Filter '*.html')) {
  foreach ($ms in [regex]::Matches((Get-Content $h.FullName -Raw), '(?is)<script[^>]*\bsrc\s*=\s*["'']([^"'']+\.js)["'']')) {
    $rel = ($ms.Groups[1].Value -replace '^\./', '') -replace '/', '\'
    if ($rel -match '^(https?:|//)') { continue }
    if (-not (Test-Path (Join-Path $app $rel))) { throw ("HTML_SCRIPT_GATE MISSING: " + $h.Name + ' -> ' + $ms.Groups[1].Value) }
  }
}
Write-Output 'HTML_SCRIPT_GATE: OK'
# 运行时裸模块依赖：只查 app 根 js 里 require('x')/import('x') 真实引用的（包内故意只注入运行时子集，不能用 package.json 全量声明；相对 require 已由 REQUIRE_GATE 覆盖）
$builtin = '^(assert|buffer|child_process|crypto|dgram|dns|events|fs/|fs$|http$|http2|https|inspector|net|os|path|process|punycode|querystring|readline|stream|string_decoder|timers|tls|url|util|v8|vm|worker_threads|zlib|electron|original-fs)'
$mods = @{}
foreach ($f in (Get-ChildItem $app -Filter '*.js')) {
  foreach ($mm in [regex]::Matches((Get-Content $f.FullName -Raw), '(?:require|import)\(\s*["'']([A-Za-z@][A-Za-z0-9@._/-]*)["'']\s*\)')) {
    $n = $mm.Groups[1].Value
    if ($n -match $builtin) { continue }
    $mods[$n] = 1
  }
}
foreach ($n in $mods.Keys) {
  if (-not (Test-Path (Join-Path $app ('node_modules\' + ($n -replace '/', '\'))))) { throw ('DEPS_GATE MISSING: ' + $n) }
}
Write-Output ('DEPS_GATE: OK (' + ($mods.Keys -join ', ') + ')')

Write-Output ("OK size(MB): " + [math]::Round((Get-ChildItem $dst -Recurse | Measure-Object Length -Sum).Sum / 1MB, 1))
Write-Output ("EXE: " + (Get-Item (Join-Path $dst 'LectureLearnLoop.exe')).FullName)
