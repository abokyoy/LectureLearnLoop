$ErrorActionPreference = 'Stop'
$root = 'e:\LLM\LectureLearnLoop'
$up = Test-NetConnection -ComputerName 127.0.0.1 -Port 6001 -InformationLevel Quiet -WarningAction SilentlyContinue
if (-not $up) {
  Start-Process -FilePath 'python' -ArgumentList (Join-Path $root 'server\app.py') -WorkingDirectory (Join-Path $root 'server') -WindowStyle Hidden
  for ($i = 0; $i -lt 25; $i++) {
    Start-Sleep -Seconds 1
    if (Test-NetConnection -ComputerName 127.0.0.1 -Port 6001 -InformationLevel Quiet -WarningAction SilentlyContinue) { $up = $true; break }
  }
}
"main6001_up=$up" | Set-Content -Path (Join-Path $root 'server\logs\main_server_up.txt')
