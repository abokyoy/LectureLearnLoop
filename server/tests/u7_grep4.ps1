$f = 'e:\LLM\LectureLearnLoop\server\templates\base.html'
$out = 'e:\LLM\LectureLearnLoop\server\logs\u7_grep4.txt'
$pat = 'function switchTab|function toggleMaximizeChat|practiceContainer =|aiPracticeMessages =|id=.practiceContainer|welcomeScreen|practiceWelcomeScreen|function showPracticeMessages|function showWelcomeScreen'
Select-String -Path $f -Pattern $pat -Encoding UTF8 | ForEach-Object {
    "{0}: {1}" -f $_.LineNumber, $_.Line.Trim().Substring(0, [Math]::Min(120, $_.Line.Trim().Length))
} | Set-Content -Path $out -Encoding UTF8
Write-Host "COUNT:" (Get-Content $out).Count
