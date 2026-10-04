$dir = 'e:\LLM\LectureLearnLoop\server\templates'
$out = 'e:\LLM\LectureLearnLoop\server\logs\u7_grep_nav.txt'
$pat = '开始新练习|练习历史|开始练习|newPractice|startNewPractice|practiceHistory'
Get-ChildItem -Path $dir -Recurse -Filter *.html | ForEach-Object {
    $file = $_.FullName
    Select-String -Path $file -Pattern $pat -Encoding UTF8 | ForEach-Object {
        "{0} {1}: {2}" -f (Split-Path $file -Leaf), $_.LineNumber, $_.Line.Trim().Substring(0, [Math]::Min(130, $_.Line.Trim().Length))
    }
} | Set-Content -Path $out -Encoding UTF8
Write-Host "COUNT:" (Get-Content $out -ErrorAction SilentlyContinue).Count
