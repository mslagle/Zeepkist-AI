@echo off
setlocal

:: Get the directory where this script is located
set SCRIPT_DIR=%~dp0
set ROOT_DIR=%SCRIPT_DIR%..
set VENV_DIR=%ROOT_DIR%\.venv

echo === Zeepkist AI Training Starter ===

:: 1. Check if virtual environment exists, if not create it
if not exist "%VENV_DIR%" (
    echo Creating virtual environment in %VENV_DIR%...
    python -m venv "%VENV_DIR%"
    if %errorlevel% neq 0 (
        echo Error: Failed to create virtual environment.
        pause
        exit /b %errorlevel%
    )
)

:: 2. Activate the virtual environment
echo Activating virtual environment...
call "%VENV_DIR%\Scripts\activate"

:: 3. Install/Update requirements
echo Installing/Updating requirements...
:: Force older setuptools (<70) for TensorBoard's pkg_resources compatibility
pip install --upgrade "setuptools<70" pip grpcio tensorboard-data-server
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo Error: Failed to install requirements.
    pause
    exit /b %errorlevel%
)

:: 4. Run the training script
echo Starting training...
python train.py

:: 5. Keep window open if script exits
echo.
echo Training process ended.
pause
