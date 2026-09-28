$m = Select-String -Path 'e:\LLM\LectureLearnLoop\server\templates\pages\*.html','e:\LLM\LectureLearnLoop\server\templates\*.html','e:\LLM\LectureLearnLoop\server\templates\components\*.html' -Pattern '(?:pybridge|bridge)\.([A-Za-z_][A-Za-z0-9_]*)' -AllMatches -ErrorAction SilentlyContinue
$names = $m.Matches | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique
$names | ForEach-Object { Write-Output $_ }
Write-Output "=== pages dir ==="
Get-ChildItem 'e:\LLM\LectureLearnLoop\server\templates\pages','e:\LLM\LectureLearnLoop\server\templates\components' -ErrorAction SilentlyContinue | ForEach-Object { Write-Output $_.Name }
