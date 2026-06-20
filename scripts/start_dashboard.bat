@echo off
setlocal

:: Get the directory where this script is located
set SCRIPT_DIR=%~dp0
set ROOT_DIR=%SCRIPT_DIR%..
set VENV_DIR=%ROOT_DIR%\.venv

echo === Zeepkist AI Telemetry Dashboard Starter ===

:: 1. Activate the virtual environment if it exists
if exist "%VENV_DIR%" (
    echo Activating virtual environment...
    call "%VENV_DIR%\Scripts\activate"
) else (
    echo [Info] No virtual environment found at %VENV_DIR%. Running with global python.
)

:: 2. Run the stats server script
echo Starting Telemetry Dashboard Server...
python "%SCRIPT_DIR%stats_server.py"

:: 3. Keep window open if script exits
echo.
echo Dashboard server ended.
pause
