$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$distRoot = Join-Path $root "dist"
$builtApp = Join-Path $distRoot "NTULineBot"
$deploy = Join-Path $distRoot "NTULineBot-windows-deploy"
$zip = Join-Path $distRoot "NTULineBot-windows-deploy.zip"

if (-not (Test-Path (Join-Path $builtApp "NTULineBot.exe"))) {
    throw "Missing dist\NTULineBot\NTULineBot.exe. Build it first with build_windows_exe.bat on a Windows machine with Python."
}

if (Test-Path $deploy) {
    Remove-Item -LiteralPath $deploy -Recurse -Force
}
New-Item -ItemType Directory -Path $deploy | Out-Null

Copy-Item -LiteralPath (Join-Path $builtApp "NTULineBot.exe") -Destination $deploy
Copy-Item -LiteralPath (Join-Path $builtApp "_internal") -Destination $deploy -Recurse
Copy-Item -LiteralPath (Join-Path $root "database") -Destination $deploy -Recurse
Copy-Item -LiteralPath (Join-Path $root ".env.example") -Destination $deploy
Copy-Item -LiteralPath (Join-Path $root "EDIT_BOT_CONFIG.bat") -Destination $deploy
Copy-Item -LiteralPath (Join-Path $root "RUN_NTULineBot.bat") -Destination $deploy
Copy-Item -LiteralPath (Join-Path $root "RUN_DEPLOYMENT_DIAGNOSTICS.bat") -Destination $deploy
Copy-Item -LiteralPath (Join-Path $root "TEST_LM_STUDIO.bat") -Destination $deploy
Copy-Item -LiteralPath (Join-Path $root "DEPLOY_WINDOWS_README.txt") -Destination $deploy
Copy-Item -LiteralPath (Join-Path $root "build_windows_exe.bat") -Destination $deploy
Copy-Item -LiteralPath (Join-Path $root "NTULineBot.spec") -Destination $deploy
Copy-Item -LiteralPath (Join-Path $root "requirements.txt") -Destination $deploy

New-Item -ItemType Directory -Path (Join-Path $deploy "memory_data") | Out-Null

$cloudflared = Join-Path $root "cloudflared-windows-amd64.exe"
if (-not (Test-Path $cloudflared)) {
    throw "Missing cloudflared-windows-amd64.exe. Download/copy it into the repo root before packaging, otherwise LINE webhook mode cannot work."
}
Copy-Item -LiteralPath $cloudflared -Destination (Join-Path $deploy "cloudflared-windows-amd64.exe")
Copy-Item -LiteralPath $cloudflared -Destination (Join-Path $deploy "cloudflared.exe")

Get-ChildItem -LiteralPath $deploy -Recurse -Force |
    Where-Object { $_.Name -like "._*" -or $_.Name -eq "__pycache__" } |
    Remove-Item -Recurse -Force

if (Test-Path $zip) {
    Remove-Item -LiteralPath $zip -Force
}
Compress-Archive -LiteralPath $deploy -DestinationPath $zip -Force

Write-Host "Packaged: $zip"
