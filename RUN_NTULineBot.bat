@echo off
cd /d "%~dp0"
chcp 65001 >nul
title NTU Nursing LINE Bot

if not exist memory_data mkdir memory_data

if not exist .env (
    if exist .env.example (
        copy .env.example .env >nul
        echo Created .env from .env.example.
        echo Please edit .env before using LINE webhook mode.
        echo.
    )
)

if exist "cloudflared.exe" (
    set "PATH=%CD%;%PATH%"
)

set "LMS_PATH=%USERPROFILE%\.lmstudio\bin\lms.exe"
if exist "%LMS_PATH%" (
    netstat -aon | findstr ":1234" | findstr "LISTENING" >nul
    if errorlevel 1 (
        echo Starting LM Studio API server...
        start "LM Studio API" /min "%LMS_PATH%" server start
        timeout /t 8 >nul
    )
) else (
    echo LM Studio CLI was not found at:
    echo %LMS_PATH%
    echo Start the LM Studio local server manually before using the bot.
    echo.
)

echo Choose a mode in the bot window:
echo 1 = CLI test
echo 2 = LINE webhook with Cloudflare tunnel
echo 3 = Both
echo 4 = Rebuild knowledge database from PDFs in database folder
echo 5 = Deployment diagnostics
echo.
NTULineBot.exe
pause
