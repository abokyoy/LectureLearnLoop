$shell = New-Object -ComObject WScript.Shell
for ($i = 0; $i -lt 30; $i++) { $shell.SendKeys([char]175); Start-Sleep -Milliseconds 60 }
Write-Output "volume up x30 sent"
Set-Location e:\LLM\LectureLearnLoop\server
python tests\p4_diag_audio.py
