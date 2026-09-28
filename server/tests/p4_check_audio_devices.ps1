Write-Output "== Win32_SoundDevice =="
Get-CimInstance -ClassName Win32_SoundDevice | ForEach-Object { Write-Output ("{0} | status={1}" -f $_.Name, $_.Status) }
Write-Output "== Audiosrv service =="
Get-Service Audiosrv | ForEach-Object { Write-Output ("Audiosrv: " + $($_.Status)) }
Write-Output "== Render endpoints (registry) =="
$base = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render'
if (Test-Path $base) { (Get-ChildItem $base).Count } else { Write-Output "NO_RENDER_KEY" }
Write-Output "== default audio endpoint via .NET =="
python -c "import subprocess" 2>$null
Add-Type -AssemblyName System.Windows.Forms
Write-Output "== SoundPlayer+endpoint quick check done =="
