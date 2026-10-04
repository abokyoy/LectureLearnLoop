$ErrorActionPreference = 'Continue'
$root = 'e:\LLM\LectureLearnLoop'
# 1) 结束 6001 端口上的 Flask 进程
$conns = Get-NetTCPConnection -LocalPort 6001 -State Listen -ErrorAction SilentlyContinue
foreach ($c in $conns) {
  Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
  "killed pid=$($c.OwningProcess)" | Add-Content (Join-Path $root 'server\logs\restart_6001.txt')
}
Start-Sleep -Seconds 2
# 2) 重新启动主后端
Start-Process -FilePath 'python' -ArgumentList (Join-Path $root 'server\app.py') -WorkingDirectory (Join-Path $root 'server') -WindowStyle Hidden
$up = $false
for ($i = 0; $i -lt 30; $i++) {
  Start-Sleep -Seconds 1
  if (Test-NetConnection -ComputerName 127.0.0.1 -Port 6001 -InformationLevel Quiet -WarningAction SilentlyContinue) { $up = $true; break }
}
"main6001_up=$up" | Add-Content (Join-Path $root 'server\logs\restart_6001.txt')
