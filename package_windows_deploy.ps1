$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$built = Join-Path $root "dist\NTULineBot"
$deploy = Join-Path $root "dist\NTULineBot-deploy"
if (-not (Test-Path (Join-Path $built "NTULineBot.exe"))) { throw "Build first with build_windows_exe.bat" }
if (Test-Path $deploy) { Remove-Item -LiteralPath $deploy -Recurse -Force }
New-Item -ItemType Directory -Path $deploy | Out-Null
Copy-Item "$built\*" $deploy -Recurse
Copy-Item (Join-Path $root "database") $deploy -Recurse   # knowledge base (PDFs + index)
foreach ($d in "bin", "models") { New-Item -ItemType Directory -Path (Join-Path $deploy $d) -Force | Out-Null }
# Put these in before zipping (not in git): bin\llama-server.exe (+ its DLLs), bin\cloudflared.exe, models\*.gguf
foreach ($f in "bin\llama-server.exe", "bin\cloudflared.exe") {
  if (Test-Path (Join-Path $root $f)) { Copy-Item (Join-Path $root $f) (Join-Path $deploy $f) } else { Write-Warning "Missing $f" }
}
Get-ChildItem (Join-Path $root "bin") -Filter *.dll -ErrorAction SilentlyContinue | Copy-Item -Destination (Join-Path $deploy "bin")
Get-ChildItem (Join-Path $root "models") -Filter *.gguf -ErrorAction SilentlyContinue | Copy-Item -Destination (Join-Path $deploy "models")
Compress-Archive -LiteralPath $deploy -DestinationPath "$deploy.zip" -Force
Write-Host "Packaged: $deploy.zip  (unzip anywhere, double-click NTULineBot.exe)"
