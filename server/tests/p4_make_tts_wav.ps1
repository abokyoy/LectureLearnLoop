$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
# 找英文 voice
$voice = $synth.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -like 'en*' } | Select-Object -First 1
if ($voice) { $synth.SelectVoice($voice.VoiceInfo.Name) }
Write-Output ("voice: " + $synth.Voice.Name)
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$synth.SetOutputToWaveFile('e:\LLM\LectureLearnLoop\server\tests\fixtures\lecture_sample.wav', $fmt)
$text = @'
Welcome to today's lecture on linear algebra, specifically the topic of eigenvalues and eigenvectors.
Let us consider a square matrix A. A nonzero vector v is called an eigenvector of A if multiplying A by v only scales v, without changing its direction.
The scaling factor is called the eigenvalue, usually denoted by the Greek letter lambda. So the defining equation is A times v equals lambda times v.
To find eigenvalues, we rewrite the equation as A minus lambda times I, times v equals zero. For a nonzero solution v to exist, the determinant of A minus lambda I must be zero.
This equation is called the characteristic polynomial. Its roots are the eigenvalues of the matrix.
Geometrically, an eigenvector points along a direction that the linear transformation only stretches or flips, never rotates.
Eigen decomposition allows us to rewrite a matrix as P times D times P inverse, where D is a diagonal matrix of eigenvalues.
This is extremely useful for computing matrix powers, solving differential equations, and principal component analysis in machine learning.
Remember: only square matrices can have eigenvalues, and a matrix with distinct eigenvalues is guaranteed to be diagonalizable.
'@
$synth.Speak($text)
$synth.Dispose()
Get-Item 'e:\LLM\LectureLearnLoop\server\tests\fixtures\lecture_sample.wav' | ForEach-Object { Write-Output ("wav size KB: " + [int]($_.Length/1KB)) }
