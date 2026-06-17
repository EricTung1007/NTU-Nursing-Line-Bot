@echo off
cd /d "%~dp0"
chcp 65001 >nul
title NTU Nursing LINE Bot - Deployment Diagnostics

if not exist .env (
    if exist .env.example (
        copy .env.example .env >nul
        echo Created .env from .env.example.
        echo Please edit .env and fill LINE/model settings before webhook mode.
        echo.
    ) else (
        call EDIT_BOT_CONFIG.bat
    )
)

NTULineBot.exe 5
pause
