@echo off
cd /d "%~dp0"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop.ps1"
if errorlevel 1 (
    echo.
    echo Stop failed. Check the error message above.
    pause
    exit /b 1
)
pause
