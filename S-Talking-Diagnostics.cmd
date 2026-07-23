@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  powershell -NoProfile -Command "Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show('The Python virtual environment was not found. Diagnostics cannot run.','S Talking Diagnostics')"
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m app.cli export-diagnostics
start "" "artifacts\diagnostics"
pause
