Set-Location e:\LLM\LectureLearnLoop\server
Write-Output ("Alarm01 exists: " + (Test-Path C:\Windows\Media\Alarm01.wav))
(Get-ChildItem C:\Windows\Media\*.wav | Select-Object -First 8 | ForEach-Object { Write-Output ("{0} {1}KB dur" -f $_.Name, [int]($_.Length/1KB)) })
python -c "import winsound; winsound.PlaySound(r'C:\Windows\Media\Alarm01.wav', winsound.SND_FILENAME); print('played sync ok')"
