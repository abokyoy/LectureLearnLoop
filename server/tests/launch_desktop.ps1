# 启动 Electron 桌面端并落盘结果（绕过 bash 包裹层 $ 吞字问题，见掉坑笔记 P037）
$ErrorActionPreference = 'Continue'
$out = 'e:\LLM\LectureLearnLoop\server\logs\launch_desktop.txt'
$log = @()

# 若已有 electron 进程先报告，不 kill（用户可能在用）
$existing = Get-Process electron -ErrorAction SilentlyContinue | Select-Object -First 1
if ($existing) {
    $log += "ALREADY_RUNNING PID=$($existing.Id)"
} else {
    $p = Start-Process -FilePath 'e:\LLM\LectureLearnLoop\desktop\node_modules\.bin\electron.cmd' `
        -ArgumentList '.' -WorkingDirectory 'e:\LLM\LectureLearnLoop\desktop' -WindowStyle Hidden -PassThru
    $log += "STARTED PID=$($p.Id)"
    Start-Sleep -Seconds 6
    $alive = Get-Process electron -ErrorAction SilentlyContinue | Select-Object -First 1
    $log += "ELECTRON_ALIVE=$($null -ne $alive)"
}

# Flask 端口确认
$c = Get-NetTCPConnection -LocalPort 6001 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
$log += "FLASK_6001_PID=$(if ($c) { $c.OwningProcess } else { 'NONE' })"

$log -join "`n" | Set-Content -Path $out -Encoding UTF8
