$dir = 'e:\LLM\LectureLearnLoop\server\templates'
$out = 'e:\LLM\LectureLearnLoop\server\logs\u6_grep_chat.txt'
$pat = 'function openAIChatWindow|openAIChatWindow =|function showAIPracticePanel|showAIPracticePanel =|AI练习助手|aiPracticePanel|AI 练习'
Get-ChildItem -Path $dir -Recurse -Filter *.html | ForEach-Object {
    $file = $_.FullName
    Select-String -Path $file -Pattern $pat -Encoding UTF8 | ForEach-Object {
        "{0} {1}: {2}" -f (Split-Path $file -Leaf), $_.LineNumber, $_.Line.Trim().Substring(0, [Math]::Min(100, $_.Line.Trim().Length))
    }
} | Set-Content -Path $out -Encoding UTF8
Write-Host "COUNT:" (Get-Content $out -ErrorAction SilentlyContinue).Count
