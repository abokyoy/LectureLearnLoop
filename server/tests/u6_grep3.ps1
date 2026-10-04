$f = 'e:\LLM\LectureLearnLoop\server\templates\pages\practice_materials.html'
$out = 'e:\LLM\LectureLearnLoop\server\logs\u6_grep_pm.txt'
$pat = 'generate-questions|generateQuestions|selected_text|startPractice|beginPractice|from_text|自由练习|开始练习|panel-title|<h1|<h2'
Select-String -Path $f -Pattern $pat -Encoding UTF8 | ForEach-Object {
    "{0}: {1}" -f $_.LineNumber, $_.Line.Trim().Substring(0, [Math]::Min(120, $_.Line.Trim().Length))
} | Set-Content -Path $out -Encoding UTF8
Write-Host "COUNT:" (Get-Content $out).Count
