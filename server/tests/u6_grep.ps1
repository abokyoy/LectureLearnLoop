$f = 'e:\LLM\LectureLearnLoop\server\templates\pages\online_course_notes.html'
$out = 'e:\LLM\LectureLearnLoop\server\logs\u6_grep_all.txt'
$pat = 'renameItem|contextmenu|context-menu|重命名|开始练习|练习功能|未选中文字|selectedText|selectionText|handlePractice'
Select-String -Path $f -Pattern $pat -Encoding UTF8 | ForEach-Object {
    "{0}: {1}" -f $_.LineNumber, $_.Line.Trim().Substring(0, [Math]::Min(120, $_.Line.Trim().Length))
} | Set-Content -Path $out -Encoding UTF8
Write-Host "COUNT:" (Get-Content $out).Count
