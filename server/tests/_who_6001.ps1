$conns = Get-NetTCPConnection -LocalPort 6001 -State Listen -ErrorAction SilentlyContinue
$pids = $conns | Select-Object -Expand OwningProcess -Unique
foreach ($procId in $pids) {
    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$procId"
    Write-Output ("PID=" + $p.ProcessId)
    Write-Output ("CMD=" + $p.CommandLine)
    # working dir via handle not available; print executable path
    Write-Output ("EXE=" + $p.ExecutablePath)
}
