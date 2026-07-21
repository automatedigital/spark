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

Write-Host "==> Smoke-testing frozen Python backend"
$SmokeHome = Join-Path ([System.IO.Path]::GetTempPath()) ("spark-desktop-smoke-" + [guid]::NewGuid())
$SmokeOut = Join-Path $SmokeHome "spark-server.out.log"
$SmokeErr = Join-Path $SmokeHome "spark-server.err.log"
$PortProbe = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
$PortProbe.Start()
$SmokePort = $PortProbe.LocalEndpoint.Port
$PortProbe.Stop()
$PreviousSparkHome = $env:SPARK_HOME
$SmokeProcess = $null
New-Item $SmokeHome -ItemType Directory -Force | Out-Null
try {
    $env:SPARK_HOME = $SmokeHome
    $SmokeProcess = Start-Process `
        -FilePath (Join-Path $RepoRoot "dist/spark-server/spark-server.exe") `
        -ArgumentList $SmokePort `
        -PassThru `
        -WindowStyle Hidden `
        -RedirectStandardOutput $SmokeOut `
        -RedirectStandardError $SmokeErr

    $SmokePassed = $false
    for ($Attempt = 0; $Attempt -lt 60; $Attempt++) {
        if ($SmokeProcess.HasExited) {
            break
        }
        try {
            $Response = Invoke-WebRequest "http://127.0.0.1:$SmokePort/" -UseBasicParsing -TimeoutSec 2
            if ($Response.StatusCode -eq 200) {
                $SmokePassed = $true
                break
            }
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    }

    if (-not $SmokePassed) {
        Write-Host "Frozen backend stdout:"
        if (Test-Path $SmokeOut) { Get-Content $SmokeOut }
        Write-Host "Frozen backend stderr:"
        if (Test-Path $SmokeErr) { Get-Content $SmokeErr }
        throw "Frozen Windows backend failed its startup smoke test"
    }
    Write-Host "Frozen Windows backend started successfully on port $SmokePort"
}
finally {
    if ($SmokeProcess -and -not $SmokeProcess.HasExited) {
        Stop-Process -Id $SmokeProcess.Id -Force
        $SmokeProcess.WaitForExit()
    }
    $env:SPARK_HOME = $PreviousSparkHome
    Remove-Item $SmokeHome -Recurse -Force -ErrorAction SilentlyContinue
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
