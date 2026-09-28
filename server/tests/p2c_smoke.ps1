Set-Location e:\LLM\LectureLearnLoop\server
python -m py_compile routes_pages.py app.py
if ($LASTEXITCODE -ne 0) { Write-Output "PY_COMPILE FAILED"; exit 1 }
Write-Output "py_compile OK"
powershell -NoProfile -File .\tests\restart_server.ps1
Start-Sleep -Seconds 3
python -c "import urllib.request as u; print(u.urlopen('http://127.0.0.1:6001/api/health', timeout=5).read().decode('utf-8')[:120])"
