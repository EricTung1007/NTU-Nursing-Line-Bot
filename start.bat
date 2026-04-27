@echo off
cd /d %~dp0
cls
chcp 65001 >nul

title NTU Nursing Line Bot (Resilient LM Studio Headless)

REM ✅ 指定 lms.exe 路徑（LM Studio CLI）
set "LMS_PATH=C:\Users\erict\.lmstudio\bin\lms.exe"

REM ✅ 檢查 lms.exe 是否存在
if not exist "%LMS_PATH%" (
    echo ❌ 找不到 lms.exe：%LMS_PATH%
    pause
    exit /b
)

REM ✅ 檢查是否已經有 lms server 在跑
netstat -aon | findstr ":1234" | findstr "LISTENING" >nul
if errorlevel 1 (
    echo 🔁 LM Studio API server 不在執行，啟動中...
    start "LM Studio API" cmd /min /c "%LMS_PATH% server start"
    timeout /t 5 >nul
) else (
    echo ✅ LM Studio API server 已在執行
)

REM ✅ 啟動 Flask Bot
set PYTHONIOENCODING=utf-8
python.exe -X utf8 LB.py

pause
