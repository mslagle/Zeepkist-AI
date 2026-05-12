@echo off
setlocal

set ROOT_DIR=%~dp0..
set MODEL_FILE=%ROOT_DIR%\zeepkist_ai_model.zip
set STATS_FILE=%ROOT_DIR%\zeepkist_vec_normalize.pkl
set LOG_DIR=%ROOT_DIR%\zeepkist_logs
set CHECKPOINT_DIR=%ROOT_DIR%\zeepkist_checkpoints
set TIME_FILE=%ROOT_DIR%\zeepkist_total_time.txt
set TRAIN_LOG=%ROOT_DIR%\zeepkist_training.log

echo === Zeepkist AI Progress Reset ===
echo This will delete ALL current training progress.
set /p confirm="Are you sure? (y/n): "
if /i "%confirm%" neq "y" goto :cancel

echo.
if exist "%MODEL_FILE%" (
    echo Deleting model...
    del "%MODEL_FILE%"
)
if exist "%STATS_FILE%" (
    echo Deleting normalization stats...
    del "%STATS_FILE%"
)
if exist "%LOG_DIR%" (
    echo Clearing logs...
    rd /s /q "%LOG_DIR%"
    mkdir "%LOG_DIR%"
)
if exist "%CHECKPOINT_DIR%" (
    echo Clearing checkpoints...
    rd /s /q "%CHECKPOINT_DIR%"
    mkdir "%CHECKPOINT_DIR%"
)
if exist "%TIME_FILE%" (
    echo Clearing training time...
    del "%TIME_FILE%"
)
if exist "%TRAIN_LOG%" (
    echo Clearing training log...
    del "%TRAIN_LOG%"
)

echo.
echo Progress cleared. You can now start fresh.
pause
exit /b 0

:cancel
echo Reset cancelled.
pause
