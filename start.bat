@echo off
title Lavalink v4 Server
echo ===================================================
echo           Starting Ryuga Lavalink v4 Server
echo ===================================================
java -Xmx2G -XX:+UseG1GC -jar Lavalink.jar
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Lavalink process terminated with exit code %ERRORLEVEL%.
    echo Please make sure you have Java 17 or Java 21 installed.
)
pause
