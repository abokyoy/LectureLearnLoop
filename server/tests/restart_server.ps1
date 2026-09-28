# 杀掉所有 app.py python 进程并重启服务端（P2 部署脚本）
$procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'app\.py' }
foreach ($p in $procs) {
    Stop-Process -Id $p.ProcessId -Force
    Write-Output ("killed " + $p.ProcessId)
}
Start-Sleep -Milliseconds 800
Set-Location "e:\LLM\LectureLearnLoop\server"
Start-Process -FilePath "python" -ArgumentList "app.py" -WorkingDirectory "e:\LLM\LectureLearnLoop\server" -WindowStyle Hidden -RedirectStandardOutput "logs\server_stdout.log" -RedirectStandardError "logs\server_stderr.log"
Start-Sleep -Seconds 3
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:6001/api/health" -UseBasicParsing -TimeoutSec 5
    Write-Output ("health " + $r.StatusCode + " " + $r.Content)
} catch {
    Write-Output ("health FAILED: " + $_.Exception.Message)
    Get-Content "logs\server_stderr.log" -Tail 20
}
foreach ($path in @("/api/vault/tree-nested", "/api/vault/note", "/api/conversations", "/api/practice/history", "/api/knowledge/similar")) {
    try {
        $r2 = Invoke-WebRequest -Uri ("http://127.0.0.1:6001" + $path) -UseBasicParsing -TimeoutSec 5
        Write-Output ($path + " -> " + $r2.StatusCode)
    } catch {
        $code = $_.Exception.Response.StatusCode.value__
        Write-Output ($path + " -> " + $code)
    }
}
