$ErrorActionPreference = 'Continue'
$res = 'e:\LLM\LectureLearnLoop\_pip_res.txt'
@() | Out-File $res -Encoding utf8
$env:HTTP_PROXY='http://127.0.0.1:10808'
$env:HTTPS_PROXY='http://127.0.0.1:10808'
$env:NO_PROXY='localhost,127.0.0.1'
python -m pip install lxml_html_clean --quiet 2>> $res
"pip2 exit: $LASTEXITCODE" | Out-File $res -Append -Encoding utf8
python -c "import trafilatura, markdownify, mammoth; print('IMPORT-OK', trafilatura.__version__, mammoth.__version__)" 2>> $res
"import exit: $LASTEXITCODE" | Out-File $res -Append -Encoding utf8
if ($LASTEXITCODE -eq 0) {
    Remove-Item Env:HTTP_PROXY, Env:HTTPS_PROXY -ErrorAction SilentlyContinue   # 服务进程不继承代理，保持与既往运行一致
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
Write-Output 'ROUND2-DONE'
