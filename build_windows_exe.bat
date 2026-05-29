@echo off
cd /d %~dp0
chcp 65001 >nul

python --version >nul 2>&1
if errorlevel 1 (
    echo Python was not found. Install Python 3.11 or newer first.
    pause
    exit /b 1
)

python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller

python -m PyInstaller --clean --noconfirm NTULineBot.spec

if errorlevel 1 (
    echo Build failed.
    pause
    exit /b 1
)

echo.
echo Build complete: dist\NTULineBot\NTULineBot.exe
echo Copy the whole dist\NTULineBot folder to the deployment computer.
pause
