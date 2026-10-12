# LectureLearnLoop one-click launcher (portable delivery entry)
# Usage: powershell -ExecutionPolicy Bypass -File .\start_app.ps1 [-Dev]
#   default: start server(:9992) + portable client dist\win-unpacked\LectureLearnLoop.exe
#   -Dev   : run Electron from source (desktop/) with CDP :9222 for automation
param([switch]$Dev)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

# 1) server: start only if port not listening (hidden background process)
$up = Test-NetConnection -ComputerName 127.0.0.1 -Port 9992 -InformationLevel Quiet -WarningAction SilentlyContinue
if (-not $up) {
    Write-Output 'starting server on :9992 ...'
    Start-Process -FilePath 'python' -ArgumentList (Join-Path $root 'server\app.py') `
        -WorkingDirectory (Join-Path $root 'server') -WindowStyle Hidden
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 1
        if (Test-NetConnection -ComputerName 127.0.0.1 -Port 9992 -InformationLevel Quiet -WarningAction SilentlyContinue) { $up = $true; break }
    }
    if (-not $up) { Write-Error 'server not up in 20s. Check: pip install -r server\requirements.txt and server\.env'; exit 1 }
}
Write-Output 'server OK (http://127.0.0.1:9992)'

# 2) client
if ($Dev) {
    Start-Process -FilePath (Join-Path $root 'desktop\node_modules\electron\dist\electron.exe') `
        -ArgumentList '.', '--remote-debugging-port=9222' -WorkingDirectory (Join-Path $root 'desktop')
    Write-Output 'Electron(dev) started, CDP on :9222'
} else {
    $exe = Join-Path $root 'dist\win-unpacked\LectureLearnLoop.exe'
    if (-not (Test-Path $exe)) { Write-Error 'portable build missing. Run server\tests\p7_package.ps1 first, or use -Dev'; exit 1 }
    Start-Process -FilePath $exe
    Write-Output 'LectureLearnLoop (portable) started'
}
