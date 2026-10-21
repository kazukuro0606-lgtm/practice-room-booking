# Start the scheduler (scheduler.py) and the plan screen (app.py) in two new PowerShell windows.
# Usage (in this folder):  powershell -ExecutionPolicy Bypass -File .\start.ps1
# Keep both windows open. To stop, press Ctrl + C in each window.
# (ASCII only: Windows PowerShell 5.1 reads .ps1 files without a BOM as the system code page.)

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "Not found: $python  (run the first-time setup in README.md)"
    exit 1
}

Start-Process powershell -WorkingDirectory $PSScriptRoot -ArgumentList @("-NoExit", "-Command", "& '$python' scheduler.py")
Start-Process powershell -WorkingDirectory $PSScriptRoot -ArgumentList @("-NoExit", "-Command", "& '$python' -m streamlit run app.py")
Write-Host "Started: scheduler.py and app.py (http://localhost:8501)"
