$src = 'e:\LLM\LectureLearnLoop\server\logs\u7_grep_nav.txt'
$out = 'e:\LLM\LectureLearnLoop\server\logs\u7_grep_nav2.txt'
Get-Content $src -Encoding UTF8 | Where-Object {
    $_ -match 'base\.html' -or $_ -match 'location|href|loadContent|onclick.*[Pp]ractice|window\.open'
} | Set-Content -Path $out -Encoding UTF8
Write-Host "COUNT:" (Get-Content $out).Count
