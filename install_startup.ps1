# Start the scheduler and the plan screen automatically when you sign in to Windows.
# Usage (in this folder):  powershell -ExecutionPolicy Bypass -File .\install_startup.ps1
# It puts a shortcut "practice-room-booking" in your Startup folder (shell:startup) that runs start.ps1 -Minimized.
# To undo:                 powershell -ExecutionPolicy Bypass -File .\uninstall_startup.ps1
# (ASCII only: Windows PowerShell 5.1 reads .ps1 files without a BOM as the system code page.)

$startScript = Join-Path $PSScriptRoot "start.ps1"
$startup = [Environment]::GetFolderPath("Startup")
$link = Join-Path $startup "practice-room-booking.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($link)
$shortcut.TargetPath = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$startScript`" -Minimized"
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.WindowStyle = 7  # minimized
$shortcut.Description = "Start practice-room-booking (scheduler and plan screen)"
$shortcut.Save()

Write-Host "Created: $link"
Write-Host "From the next sign-in, the scheduler and the plan screen start automatically (minimized)."
