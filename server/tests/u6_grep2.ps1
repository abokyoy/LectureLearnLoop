$f = 'e:\LLM\LectureLearnLoop\server\templates\pages\online_course_notes.html'
$out = 'e:\LLM\LectureLearnLoop\server\logs\u6_grep_dep.txt'
$pat = 'openAIChatWindow|addAIPracticeMessage|showAIPracticePanel|function generatePracticeQuestionsForAI|aiPracticePanel|ai-chat-window|openAIChat'
Select-String -Path $f -Pattern $pat -Encoding UTF8 | ForEach-Object {
    "{0}: {1}" -f $_.LineNumber, $_.Line.Trim().Substring(0, [Math]::Min(110, $_.Line.Trim().Length))
} | Set-Content -Path $out -Encoding UTF8
Write-Host "COUNT:" (Get-Content $out).Count
