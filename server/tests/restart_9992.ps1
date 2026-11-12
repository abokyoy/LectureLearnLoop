# 9992 Flask 重启（P045/P051/P059 纪律：端口+Path 双条件定性，只杀本项目实例）
# 用法：powershell -NoProfile -File restart_9992.ps1
$ErrorActionPreference = 'Continue'
$root = 'E:\LLM\LectureLearnLoop'

# 1) 定性：谁在监听 9992，是否本项目的 app.py（命令行含 app.py 且工作目录/路径属本项目）
$old = @()
$conn = Get-NetTCPConnection -LocalPort 9992 -State Listen -ErrorAction SilentlyContinue
foreach ($c in $conn) {
    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$($c.OwningProcess)" -ErrorAction SilentlyContinue
    if ($p -and $p.CommandLine -match 'app\.py' -and $p.ExecutablePath -match 'python') {
        $old += $p
        Write-Output ("CANDIDATE PID=" + $p.ProcessId + " CMD=" + $p.CommandLine)
    } else {
        Write-Output ("SKIP foreign listener PID=" + $c.OwningProcess)
    }
}
# 1b) 兜底：命令行含本项目 server 路径 + app.py 但没在监听（孤儿进程）
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object {
    $_.CommandLine -match 'app\.py' -and $_.CommandLine -match 'LectureLearnLoop'
} | ForEach-Object { $old += $_; Write-Output ("ORPHAN PID=" + $_.ProcessId) }
# 1c) 僵尸兜底（v0.2.8 八期出件轮）：裸 `python app.py`（命令行无项目路径）不在监听也不匹配 1b，
# 却自启动一条小智桥分流工具调用。特征：系统 Python312 + 命令行以 app.py 结尾（venv 项目的
# ExecutablePath 在各自 venv 目录下，天然被此条件排除，AIFinFlowX 等别家项目不受影响）
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object {
    $_.CommandLine -match 'app\.py\s*$' -and $_.ExecutablePath -like '*\Programs\Python\Python312\*'
} | ForEach-Object { $old += $_; Write-Output ("ZOMBIE_PID=" + $_.ProcessId) }

$old | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Write-Output ("KILLED " + $_.ProcessId) }
Start-Sleep -Seconds 2

# 1d) 清残留小智桥锁（2026-11-10「小智桥未连接」事故）：Stop-Process 硬杀不走退出流程，
# data/xz_mcp_bridge.lock 原封留在盘上且心跳还是新鲜的，新实例启动时误判「另一实例持有桥」
# 拒起桥且不再重试 → 云端老师调不到本地工具（只说「不知道指派了什么课程要求」）。
# 服务代码侧已加持有者 pid 查活做双保险，脚本这边仍旧把残留清干净。
$blk = Join-Path $root 'server\data\xz_mcp_bridge.lock'
if (Test-Path $blk) { Remove-Item $blk -Force -ErrorAction SilentlyContinue; Write-Output 'BRIDGE_LOCK_CLEARED' }
Get-ChildItem (Join-Path $root 'server\data') -Filter 'xz_mcp_bridge.*.tmp' -ErrorAction SilentlyContinue |
    ForEach-Object { Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue }

# 2) 启动新实例（DETACHED，隐藏窗，日志留证）
#    先记下统一调试日志当前字节偏移：第 5 步只看本轮新进程追加的事件，不拿旧进程的桥事件交差
$trace = Join-Path $root 'server\logs\debug_trace.jsonl'
$off = if (Test-Path $trace) { (Get-Item $trace).Length } else { 0 }
Start-Process -FilePath 'python' -ArgumentList 'app.py' -WorkingDirectory (Join-Path $root 'server') -WindowStyle Hidden `
  -RedirectStandardOutput (Join-Path $root 'server\logs\p9992_stdout.log') `
  -RedirectStandardError (Join-Path $root 'server\logs\p9992_stderr.log')

# 3) 轮询监听者，复核 StartTime 与命令行（必须是新进程、本项目 app.py）
$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    $c2 = Get-NetTCPConnection -LocalPort 9992 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c2) {
        $p2 = Get-CimInstance Win32_Process -Filter "ProcessId=$($c2.OwningProcess)" -ErrorAction SilentlyContinue
        if ($p2 -and $p2.CommandLine -match 'app\.py') {
            Write-Output ("LISTENER PID=" + $p2.ProcessId + " StartTime=" + $p2.CreationDate + " CMD=" + $p2.CommandLine)
            $ready = $true; break
        }
    }
}
Write-Output ("PORT_READY=" + $ready + " after " + $i + "s")

# 4) 指纹复核：health + 本轮四期新路由（重启前 404/405，重启后必须不再是 404）
try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:9992/api/health' -UseBasicParsing -TimeoutSec 5
    Write-Output ("health " + $r.StatusCode)
} catch { Write-Output ("health FAILED: " + $_.Exception.Message) }
foreach ($path in @('/api/board/speech', '/api/board/slide_image', '/api/board/archive',
                    '/api/board/lesson', '/api/board/export', '/api/board/prep', '/api/board/adopt',
                    '/api/board/assign')) {
    try {
        $r2 = Invoke-WebRequest -Uri ('http://127.0.0.1:9992' + $path) -Method Get -UseBasicParsing -TimeoutSec 5
        Write-Output ($path + ' -> ' + $r2.StatusCode)
    } catch {
        $code = try { $_.Exception.Response.StatusCode.value__ } catch { 'ERR' }
        # GET 打 POST 路由得 405 = 路由已注册；404 = 未注册（重启失败）
        Write-Output ($path + ' -> ' + $code)
    }
}

# 5) 小智桥自证（2026-11-10 加）：重启后桥必须真连上，否则云端老师拿不到本地工具。
#    只读 $off 之后新追加的 xz_mcp 事件（共享日志旧行不算本轮），轮询 20s；
#    bridge_refused = 重启失败（双实例真活着），connected 缺席且无拒绝 = 接入点未配置/解析失败。
$verdict = 'BRIDGE_EVENT_NONE'
for ($j = 0; $j -lt 20; $j++) {
    Start-Sleep -Seconds 1
    if (-not (Test-Path $trace)) { $verdict = 'BRIDGE_TRACE_MISSING'; break }
    try {
        $fs = [System.IO.File]::Open($trace, 'Open', 'Read', 'ReadWrite')
        [void]$fs.Seek($off, 'Begin')
        $sr = New-Object System.IO.StreamReader($fs, [System.Text.Encoding]::UTF8)
        $fresh = $sr.ReadToEnd(); $sr.Close(); $fs.Close()
    } catch { $fresh = '' }
    if ($fresh -match 'bridge_refused') {
        $verdict = 'BRIDGE_REFUSED'
    } elseif ($fresh -match '"action":\s*"connected"') {
        $verdict = 'BRIDGE_CONNECTED'
    } elseif ($fresh -match 'bridge_lock_stale') {
        $verdict = 'BRIDGE_TOOKOVER_RESIDUAL_LOCK'
    } elseif ($fresh -match '"action":\s*"uid_unresolved"') {
        $verdict = 'BRIDGE_UID_UNRESOLVED'
    } else { continue }
    ($fresh -split "`n" | Where-Object { $_ -match '"xz_mcp"' } | Select-Object -Last 5) |
        ForEach-Object { Write-Output ('BRIDGE_EVENT ' + $_.Substring(0, [Math]::Min(240, $_.Length)).Trim()) }
    break
}
Write-Output ('BRIDGE_VERDICT=' + $verdict)
