$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# Build an unsigned Windows x64 beta: frontend + frozen Python sidecar + NSIS.
$RepoRoot = Split-Path -Parent $PSScriptRoot
$WebDir = Join-Path $RepoRoot "src/spark_cli/web"
$TauriDir = Join-Path $WebDir "src-tauri"
$ResourcesDir = Join-Path $TauriDir "resources"

Push-Location $WebDir
try {
    Write-Host "==> Installing web frontend dependencies"
    npm ci
    Write-Host "==> Building web frontend"
    npm run build
}
finally {
    Pop-Location
}

Push-Location $RepoRoot
try {
    Write-Host "==> Freezing Python backend with PyInstaller"
    python -m PyInstaller spark-server.spec --noconfirm
}
finally {
    Pop-Location
}

Write-Host "==> Staging Windows resources"
Remove-Item (Join-Path $ResourcesDir "spark-server") -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $ResourcesDir "skills") -Recurse -Force -ErrorAction SilentlyContinue
New-Item $ResourcesDir -ItemType Directory -Force | Out-Null
Copy-Item (Join-Path $RepoRoot "dist/spark-server") (Join-Path $ResourcesDir "spark-server") -Recurse
Copy-Item (Join-Path $RepoRoot "skills") (Join-Path $ResourcesDir "skills") -Recurse

Push-Location $WebDir
try {
    Write-Host "==> Building unsigned Tauri NSIS installer"
    npm run tauri -- build --config src-tauri/tauri.windows.conf.json
}
finally {
    Pop-Location
}

$NsisDir = Join-Path $TauriDir "target/release/bundle/nsis"
$Installer = Get-ChildItem $NsisDir -Filter "*.exe" | Select-Object -First 1
if (-not $Installer) {
    throw "Tauri completed but no NSIS installer was found in $NsisDir"
}

Write-Host ""
Write-Host "Windows beta installer: $($Installer.FullName)"
