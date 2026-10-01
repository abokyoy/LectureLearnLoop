$ErrorActionPreference = 'Continue'
$res = 'e:\LLM\LectureLearnLoop\_pip_res.txt'
@() | Out-File $res -Encoding utf8

# 1) 停掉占用 site-packages 的 6021 服务进程
$conn = Get-NetTCPConnection -LocalPort 6021 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($conn) {
    Stop-Process -Id $conn.OwningProcess -Force
    "killed pid $($conn.OwningProcess)" | Out-File $res -Append -Encoding utf8
    Start-Sleep -Seconds 2
} else {
    "no listener on 6021" | Out-File $res -Append -Encoding utf8
}

# 2) 装依赖（走代理）
$env:HTTP_PROXY='http://127.0.0.1:10808'
$env:HTTPS_PROXY='http://127.0.0.1:10808'
$env:NO_PROXY='localhost,127.0.0.1'
python -m pip install trafilatura markdownify mammoth --quiet 2>> $res
"pip exit: $LASTEXITCODE" | Out-File $res -Append -Encoding utf8
python -c "import trafilatura, markdownify, mammoth; print('IMPORT-OK', trafilatura.__version__, mammoth.__version__)" 2>> $res
"import exit: $LASTEXITCODE" | Out-File $res -Append -Encoding utf8

# 3) 重启 6021 服务
if ($LASTEXITCODE -eq 0) {
    Start-Process python -ArgumentList "app.py" -WorkingDirectory "E:\LLM\LectureLearnLoop-integ\server" -WindowStyle Hidden
    for ($i = 0; $i -lt 25; $i++) {
        Start-Sleep -Seconds 2
        try {
            $h = (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:6021/api/health -TimeoutSec 3).StatusCode
            if ($h -eq 200) { "server back up: $h" | Out-File $res -Append -Encoding utf8; break }
        } catch {}
    }
}
Write-Output 'PIP-ROUND-DONE'
