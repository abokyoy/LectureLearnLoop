# 环境健康检查：端口 6001（server）/ 9222（Electron CDP）
$ErrorActionPreference = 'SilentlyContinue'
$out = @()
foreach ($port in 6001, 9222, 5000) {
  $up = Test-NetConnection -ComputerName 127.0.0.1 -Port $port -InformationLevel Quiet
  $out += "port_${port}=$up"
}
$procs = Get-Process | Where-Object { $_.ProcessName -match 'python|electron' } | Select-Object -First 10 Id, ProcessName
foreach ($p in $procs) { $out += "proc: $($p.ProcessName)#$($p.Id)" }
$out | Set-Content -Path 'e:\LLM\LectureLearnLoop\server\logs\ui_health_check.txt' -Encoding UTF8
