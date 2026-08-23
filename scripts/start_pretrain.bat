@echo off
setlocal

:: Get the directory where this script is located
set SCRIPT_DIR=%~dp0
set ROOT_DIR=%SCRIPT_DIR%..
set VENV_DIR=%ROOT_DIR%\.venv

echo =======================================================
echo  Zeepkist AI - Behavioral Cloning Pretrainer Starter
echo  Learns from 50%% Median Ghost in ~30-60 Seconds
echo =======================================================

:: 1. Check if virtual environment exists, if not create it
if not exist "%VENV_DIR%" (
    echo Creating virtual environment in %VENV_DIR%...
    python -m venv "%VENV_DIR%"
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b %errorlevel%
    )
)

:: 2. Activate the virtual environment
echo Activating virtual environment...
call "%VENV_DIR%\Scripts\activate"

:: 3. Install/Update requirements
echo Installing/Updating requirements...
pip install --upgrade "setuptools<70" pip grpcio tensorboard-data-server
pip install -r "%SCRIPT_DIR%python\requirements.txt"
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install requirements.
    pause
    exit /b %errorlevel%
)

:: 4. Prompt for Fine-Tune vs Fresh Start if interactive
echo.
set PRETRAIN_ARGS=%*
if "%PRETRAIN_ARGS%"=="" (
    if exist "%SCRIPT_DIR%python\zeepkist_ai_model.zip" (
        echo [INFO] Existing model found: scripts\python\zeepkist_ai_model.zip
        echo.
        echo   1. Fine-tune / Add this track knowledge [Continual Learning - Default]
        echo   2. Start fresh from scratch
        echo.
        set /p USER_CHOICE="Select mode [1 or 2, default 1]: "
        if "%USER_CHOICE%"=="2" (
            set PRETRAIN_ARGS=--fresh
        )
    )
)

echo.
echo Starting Behavioral Cloning Pretraining...
echo (Ensure Zeepkist is running with a track loaded)
echo.
python "%SCRIPT_DIR%python\pretrain_bc.py" %PRETRAIN_ARGS%

:: 5. Keep window open if script exits
echo.
echo Pretraining process finished.
pause
