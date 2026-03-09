@echo off
setlocal

:: Get the directory where this script is located
set SCRIPT_DIR=%~dp0
set ROOT_DIR=%SCRIPT_DIR%..
set VENV_DIR=%ROOT_DIR%\.venv
set LOG_DIR=%ROOT_DIR%\zeepkist_logs

echo === Zeepkist AI Training Progress Viewer ===

:: 1. Check if virtual environment exists
if not exist "%VENV_DIR%" (
    echo Error: Virtual environment not found in %VENV_DIR%
    echo Please run start_training.bat first.
    pause
    exit /b 1
)

:: 2. Activate the virtual environment
echo Activating virtual environment...
call "%VENV_DIR%\Scripts\activate"

:: 3. Check if log directory exists
if not exist "%LOG_DIR%" (
    echo.
    echo [Warning] Log directory '%LOG_DIR%' not found yet. 
    echo Training must start before logs are generated.
)

:: 4. Start TensorBoard
echo Starting TensorBoard...
echo Once started, visit http://localhost:6006 in your browser.
echo.

:: Start browser after a small delay
start "" http://localhost:6006

:: Run TensorBoard using python -m to be more reliable
python -m tensorboard.main --logdir "%LOG_DIR%" --port 6006

:: If tensorboard exits
if %errorlevel% neq 0 (
    echo.
    echo TensorBoard failed to start.
)
pause
