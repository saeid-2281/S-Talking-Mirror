@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  powershell -NoProfile -Command "Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show('The Python virtual environment was not found. Install dependencies first, then launch S Talking again.','S Talking')"
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m app.gui.main
if errorlevel 1 pause
