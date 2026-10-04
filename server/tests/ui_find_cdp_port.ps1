$conns = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue
$ports = @()
foreach ($c in $conns) {
  $p = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
  if ($p -and $p.ProcessName -match 'chrome') { $ports += $c.LocalPort }
}
$ports | Sort-Object -Unique | Set-Content -Path 'e:\LLM\LectureLearnLoop\server\logs\chrome_ports.txt'
