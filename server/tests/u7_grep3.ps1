$f = 'e:\LLM\LectureLearnLoop\server\templates\base.html'
$out = 'e:\LLM\LectureLearnLoop\server\logs\u7_grep3.txt'
$pat = 'function generateNewPractice|location\.href|location\.assign|window\.location|history\.pushState|loadPracticeFromHistory|resumePractice|loadContent\(|startPracticeFromHistory|function viewPractice'
Select-String -Path $f -Pattern $pat -Encoding UTF8 | ForEach-Object {
    "{0}: {1}" -f $_.LineNumber, $_.Line.Trim().Substring(0, [Math]::Min(130, $_.Line.Trim().Length))
} | Set-Content -Path $out -Encoding UTF8
Write-Host "COUNT:" (Get-Content $out).Count
