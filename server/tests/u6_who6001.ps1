$ErrorActionPreference = 'Continue'
$out = 'e:\LLM\LectureLearnLoop\server\logs\u6_who6001.txt'
$lines = @()
Get-NetTCPConnection -LocalPort 6001 -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
    $procId = $_.OwningProcess
    $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
    $cmdline = (Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue).CommandLine
    $lines += "PID=$procId NAME=$($p.ProcessName) START=$($p.StartTime) PATH=$($p.Path)"
    $lines += "CMDLINE=$cmdline"
}
$lines -join "`n" | Set-Content -Path $out -Encoding UTF8
