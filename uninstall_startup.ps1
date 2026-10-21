# Stop starting the scheduler and the plan screen automatically at sign-in (undo install_startup.ps1).
# Usage (in this folder):  powershell -ExecutionPolicy Bypass -File .\uninstall_startup.ps1
# (ASCII only: Windows PowerShell 5.1 reads .ps1 files without a BOM as the system code page.)

$link = Join-Path ([Environment]::GetFolderPath("Startup")) "practice-room-booking.lnk"
if (Test-Path $link) {
    Remove-Item $link
    Write-Host "Removed: $link"
} else {
    Write-Host "Not found (nothing to remove): $link"
}
