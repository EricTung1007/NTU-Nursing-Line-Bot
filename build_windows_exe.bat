@echo off
cd /d %~dp0
chcp 65001 >nul
python --version >nul 2>&1 || (echo Python 3.9+ not found. & pause & exit /b 1)
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-gui.txt pyinstaller
REM --noconsole: no command window. The GUI is the only interface.
python -m PyInstaller --clean --noconfirm --noconsole --name NTULineBot ^
  --add-data "nursebot\web\static;nursebot\web\static" app.py
if errorlevel 1 (echo Build failed. & pause & exit /b 1)
echo Build complete: dist\NTULineBot\NTULineBot.exe
echo Next: run package_windows_deploy.ps1
pause
