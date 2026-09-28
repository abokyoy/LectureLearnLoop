Set-Location e:\LLM\LectureLearnLoop\desktop
Get-Process electron -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 1
$exe = ".\node_modules\electron\dist\electron.exe"
Start-Process -FilePath $exe -ArgumentList @('.', '--remote-debugging-port=9222') -WorkingDirectory (Get-Location)
Start-Sleep -Seconds 6
python e:\LLM\LectureLearnLoop\server\tests\p2d_cdp_check.py
$code = $LASTEXITCODE
Write-Output ("CDP_CHECK_EXIT=" + $code)
exit $code
