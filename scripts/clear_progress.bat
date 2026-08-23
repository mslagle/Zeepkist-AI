@echo off
setlocal

set SCRIPTS_DIR=%~dp0
set PYTHON_DIR=%SCRIPTS_DIR%python\
set MODEL_FILE=%SCRIPTS_DIR%zeepkist_ai_model.zip
set MODEL_FILE2=%PYTHON_DIR%zeepkist_ai_model.zip
set STATS_FILE=%SCRIPTS_DIR%zeepkist_vec_normalize.pkl
set STATS_FILE2=%PYTHON_DIR%zeepkist_vec_normalize.pkl
set LOG_DIR=%SCRIPTS_DIR%zeepkist_logs
set CHECKPOINT_DIR=%SCRIPTS_DIR%checkpoints
set TIME_FILE=%SCRIPTS_DIR%zeepkist_total_time.txt
set TIME_FILE2=%PYTHON_DIR%zeepkist_total_time.txt
set TRAIN_LOG=%SCRIPTS_DIR%zeepkist_training.log

echo === Zeepkist AI Progress Reset ===
echo SCRIPTS_DIR: %SCRIPTS_DIR%
echo This will delete ALL current training progress.
set /p confirm="Are you sure? (y/n): "
if /i "%confirm%" neq "y" goto :cancel

echo.
echo Attempting to clear files...

if exist "%MODEL_FILE%" (
    echo Deleting: %MODEL_FILE%
    del /f /q /a "%MODEL_FILE%"
    if exist "%MODEL_FILE%" (
        echo [ERROR] Failed to delete model file.
    ) else (
        echo [SUCCESS] Model file deleted.
    )
) else (
    echo [SKIP] Model file not found.
)

if exist "%MODEL_FILE2%" (
    echo Deleting: %MODEL_FILE2%
    del /f /q /a "%MODEL_FILE2%"
)

if exist "%STATS_FILE%" (
    echo Deleting: %STATS_FILE%
    del /f /q /a "%STATS_FILE%"
    if exist "%STATS_FILE%" (
        echo [ERROR] Failed to delete normalization stats.
    ) else (
        echo [SUCCESS] Normalization stats deleted.
    )
) else (
    echo [SKIP] Normalization stats not found.
)

if exist "%LOG_DIR%" (
    echo Clearing log directory: %LOG_DIR%
    rd /s /q "%LOG_DIR%"
    if exist "%LOG_DIR%" (
        echo [ERROR] Failed to clear log directory.
    ) else (
        mkdir "%LOG_DIR%"
        echo [SUCCESS] Log directory cleared.
    )
)

if exist "%CHECKPOINT_DIR%" (
    echo Clearing checkpoint directory: %CHECKPOINT_DIR%
    rd /s /q "%CHECKPOINT_DIR%"
    if exist "%CHECKPOINT_DIR%" (
        echo [ERROR] Failed to clear checkpoint directory.
    ) else (
        mkdir "%CHECKPOINT_DIR%"
        echo [SUCCESS] Checkpoint directory cleared.
    )
) else (
    echo [SKIP] Checkpoint directory not found.
)

if exist "%TIME_FILE%" (
    echo Deleting: %TIME_FILE%
    del /f /q /a "%TIME_FILE%"
    if exist "%TIME_FILE%" (
        echo [ERROR] Failed to delete training time file.
    ) else (
        echo [SUCCESS] Training time file deleted.
    )
) else (
    echo [SKIP] Training time file not found.
)

if exist "%TRAIN_LOG%" (
    echo Deleting: %TRAIN_LOG%
    del /f /q /a "%TRAIN_LOG%"
    if exist "%TRAIN_LOG%" (
        echo [ERROR] Failed to delete training log.
    ) else (
        echo [SUCCESS] Training log deleted.
    )
) else (
    echo [SKIP] Training log not found.
)

echo.
echo Progress cleared. You can now start fresh.
pause
exit /b 0

:cancel
echo Reset cancelled.
pause
