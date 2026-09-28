$files = Get-ChildItem e:\LLM\LectureLearnLoop\server\templates\pages\*.html
foreach ($f in $files) {
    $head = (Get-Content $f.FullName -TotalCount 2) -join ' | '
    Write-Output ("{0} :: {1}" -f $f.Name, $head.Substring(0, [Math]::Min(120, $head.Length)))
}
Write-Output "=== root templates ==="
Get-ChildItem e:\LLM\LectureLearnLoop\server\templates\*.html | ForEach-Object { Write-Output $_.Name }
Write-Output "=== spa_layout check ==="
if (Test-Path e:\LLM\LectureLearnLoop\server\templates\spa_layout.html) {
    Select-String -Path e:\LLM\LectureLearnLoop\server\templates\spa_layout.html -Pattern 'block|include|updateContentArea|fragments' | Select-Object -First 20 | ForEach-Object { Write-Output ("L{0}: {1}" -f $_.LineNumber, $_.Line.Trim()) }
} else {
    Write-Output "NO spa_layout.html"
}
