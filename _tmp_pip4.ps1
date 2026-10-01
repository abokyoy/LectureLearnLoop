$ErrorActionPreference = 'Continue'
$res = 'e:\LLM\LectureLearnLoop\_pip_res.txt'
@() | Out-File $res -Encoding utf8
python -c "import trafilatura, markdownify, mammoth; import importlib.metadata as m; print('IMPORT-OK', m.version('trafilatura'), m.version('mammoth'), m.version('markdownify'))" 2>> $res
"import exit: $LASTEXITCODE" | Out-File $res -Append -Encoding utf8
if ($LASTEXITCODE -eq 0) {
    Start-Process python -ArgumentList "app.py" -WorkingDirectory "E:\LLM\LectureLearnLoop-integ\server" -WindowStyle Hidden
    $up = $false
    for ($i = 0; $i -lt 25; $i++) {
        Start-Sleep -Seconds 2
        try {
            $h = (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:6021/api/health -TimeoutSec 3).StatusCode
            if ($h -eq 200) { $up = $true; break }
        } catch {}
    }
    "server up: $up" | Out-File $res -Append -Encoding utf8
}
Write-Output 'ROUND3-DONE'
