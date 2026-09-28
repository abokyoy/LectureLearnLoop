$calls = Select-String -Path 'e:\LLM\LectureLearnLoop\server\templates\pages\*.html','e:\LLM\LectureLearnLoop\server\templates\*.html','e:\LLM\LectureLearnLoop\server\templates\components\*.html' -Pattern '(?:pybridge|bridge)\.([A-Za-z_][A-Za-z0-9_]*)' -AllMatches |
    ForEach-Object { $_.Matches } | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique
$impls = Select-String -Path 'e:\LLM\LectureLearnLoop\server\static\js\api.js' -Pattern 'bridge\.([A-Za-z_][A-Za-z0-9_]*)\s*=' -AllMatches |
    ForEach-Object { $_.Matches } | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique
Write-Output "=== called but NOT implemented ==="
$calls | Where-Object { $impls -notcontains $_ } | ForEach-Object { Write-Output $_ }
Write-Output "=== implemented count: $($impls.Count) ==="
