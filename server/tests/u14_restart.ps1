# u14 评审修复后重启 :6001（结果落盘，终端回显不可信）
$ErrorActionPreference = 'Continue'
$out = 'e:\LLM\LectureLearnLoop\server\logs\u14_restart_result.txt'
$log = @()

# 1. 确保 6001 无监听（kill 所有占用者）
$conns = Get-NetTCPConnection -LocalPort 6001 -State Listen -ErrorAction SilentlyContinue
if ($conns) {
    foreach ($c in $conns) {
        Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
        $log += "KILLED PID=$($c.OwningProcess)"
    }
    Start-Sleep -Seconds 3
} else {
    $log += "NO LISTENER"
}

# 2. 启动新进程
$psi = Start-Process -FilePath 'python' -ArgumentList 'app.py' -WorkingDirectory 'e:\LLM\LectureLearnLoop\server' -WindowStyle Hidden -RedirectStandardOutput 'e:\LLM\LectureLearnLoop\server\logs\s3_stdout.log' -RedirectStandardError 'e:\LLM\LectureLearnLoop\server\logs\s3_stderr.log' -PassThru
$log += "STARTED PID=$($psi.Id)"

# 3. 轮询 HTTP 就绪（用真实请求判活，不依赖 Get-NetTCPConnection）
$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    try {
        $r = Invoke-WebRequest -Uri 'http://127.0.0.1:6001/login' -UseBasicParsing -TimeoutSec 3
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
}
$log += "HTTP_READY=$ready after ${i}s"
$log -join "`n" | Set-Content -Path $out -Encoding UTF8
