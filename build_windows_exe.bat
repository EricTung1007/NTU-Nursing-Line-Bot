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

copy /Y ".env.example" "dist\NTULineBot\.env.example" >nul
copy /Y "RUN_NTULineBot.bat" "dist\NTULineBot\RUN_NTULineBot.bat" >nul
copy /Y "RUN_DEPLOYMENT_DIAGNOSTICS.bat" "dist\NTULineBot\RUN_DEPLOYMENT_DIAGNOSTICS.bat" >nul
copy /Y "EDIT_BOT_CONFIG.bat" "dist\NTULineBot\EDIT_BOT_CONFIG.bat" >nul
copy /Y "TEST_LM_STUDIO.bat" "dist\NTULineBot\TEST_LM_STUDIO.bat" >nul
copy /Y "DEPLOY_WINDOWS_README.txt" "dist\NTULineBot\DEPLOY_WINDOWS_README.txt" >nul
if exist "cloudflared-windows-amd64.exe" (
    copy /Y "cloudflared-windows-amd64.exe" "dist\NTULineBot\cloudflared-windows-amd64.exe" >nul
    copy /Y "cloudflared-windows-amd64.exe" "dist\NTULineBot\cloudflared.exe" >nul
) else (
    echo WARNING: cloudflared-windows-amd64.exe was not found. LINE webhook mode will not work until cloudflared.exe is copied beside NTULineBot.exe.
)

echo.
echo Build complete: dist\NTULineBot\NTULineBot.exe
echo Copy the whole dist\NTULineBot folder, or run package_windows_deploy.ps1 and copy the deploy zip.
pause
