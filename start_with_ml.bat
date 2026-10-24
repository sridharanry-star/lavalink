@echo off
title Lavalink v4 + ML Search Gateway
echo ===================================================
echo     Starting Ryuga Lavalink v4 + ML Search Gateway
echo ===================================================

REM Check Python installation
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python 3 is not installed or not in system PATH.
    echo Please install Python 3.10+ from https://www.python.org/
    pause
    exit /b 1
)

python lavalink_ml_gateway.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Lavalink ML Gateway terminated with exit code %ERRORLEVEL%.
)
pause
