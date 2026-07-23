@echo off
setlocal
cd /d "%~dp0"
:menu
cls
echo S Talking Developer Launcher
echo.
echo 1. Run S Talking
echo 2. Run all checks
echo 3. Export diagnostics
echo 4. Open latest report
echo 5. Open logs
echo 6. Open repository in VS Code
echo 7. Exit
echo.
choice /c 1234567 /n /m "Choose: "
set "CHOICE=%errorlevel%"
if "%CHOICE%"=="7" exit /b 0
if "%CHOICE%"=="6" code .
if "%CHOICE%"=="5" start "" "logs"
if "%CHOICE%"=="4" start "" "reports"
if "%CHOICE%"=="3" call S-Talking-Diagnostics.cmd
if "%CHOICE%"=="2" powershell -ExecutionPolicy Bypass -File ".\scripts\dev-check.ps1"
if "%CHOICE%"=="1" call S-Talking.cmd
pause
goto menu
