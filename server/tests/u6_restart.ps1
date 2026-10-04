# u6 评审修复后重启 :6001（端口检测+模板特征双重确认）
$ErrorActionPreference = 'Continue'
$out = 'e:\LLM\LectureLearnLoop\server\logs\u6_restart_result.txt'
$log = @()

# 1. kill 占用 6001 的进程
$conn = Get-NetTCPConnection -LocalPort 6001 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($conn) {
    $pid6001 = $conn.OwningProcess
    Stop-Process -Id $pid6001 -Force -ErrorAction SilentlyContinue
    $log += "KILLED PID=$pid6001"
    Start-Sleep -Seconds 2
} else {
    $log += "NO LISTENER ON 6001"
}

# 2. 启动新进程（工作目录 server，日志 s3）
$psi = Start-Process -FilePath 'python' -ArgumentList 'app.py' -WorkingDirectory 'e:\LLM\LectureLearnLoop\server' -WindowStyle Hidden -RedirectStandardOutput 'e:\LLM\LectureLearnLoop\server\logs\s3_stdout.log' -RedirectStandardError 'e:\LLM\LectureLearnLoop\server\logs\s3_stderr.log' -PassThru
$log += "STARTED PID=$($psi.Id)"

# 3. 轮询端口直到就绪（最多 60s）
$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    $c = Get-NetTCPConnection -LocalPort 6001 -State Listen -ErrorAction SilentlyContinue
    if ($c) { $ready = $true; break }
}
$log += "PORT_READY=$ready after ${i}s"

# 4. 进程存活确认
$alive = Get-Process -Id $psi.Id -ErrorAction SilentlyContinue
$log += "PROCESS_ALIVE=$($null -ne $alive)"

$log -join "`n" | Set-Content -Path $out -Encoding UTF8
