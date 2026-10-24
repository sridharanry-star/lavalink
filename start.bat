@echo off
title Ryuga Lavalink v4 + ML Search
echo ===================================================
echo     Starting Ryuga Lavalink v4 with ML Search
echo ===================================================

where python >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [INFO] Python detected. Launching Lavalink with ML Search Gateway...
    python lavalink_ml_gateway.py
    goto end
)

echo [INFO] Python not found. Falling back to direct Java Lavalink...
java -Xmx2G -XX:+UseG1GC -jar Lavalink.jar
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Lavalink process terminated with exit code %ERRORLEVEL%.
    echo Please make sure you have Java 17 or Java 21 installed.
)

:end
pause
