# build_windows.ps1 - Build ParaTracker.exe (Windows onedir PyInstaller package)
#                     and, if Inno Setup is available, the ParaTracker-<v>-Setup.exe installer.
# Usage: .\build_windows.ps1 [-SkipInstaller]
param(
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"

$ProjectDir  = $PSScriptRoot
$VenvDir     = "$ProjectDir\venv"
$WeightsSha  = "f7712cb708c94a788f36fe8cbf9c1f479e399286ab3c9afbbb318e4c6d9f80fe"
$WeightsFile = "$ProjectDir\weights\worm_yolov8seg-$WeightsSha.pt"

Write-Host "==> Activating Python virtual environment"
if (-not (Test-Path "$VenvDir\Scripts\Activate.ps1")) {
    Write-Error "ERROR: venv not found at $VenvDir. Run '.\dev.ps1 venv' first."
    exit 1
}
& "$VenvDir\Scripts\Activate.ps1"

Write-Host "==> Ensuring build deps are installed"
& "$VenvDir\Scripts\pip.exe" install pyinstaller imageio-ffmpeg -q

Write-Host "==> Checking for YOLO weights"
if (-not (Test-Path $WeightsFile)) {
    Write-Error "ERROR: weights not found at $WeightsFile. Run '.\dev.ps1 weights' first."
    exit 1
}

Write-Host "==> Building React frontend (production, relative URLs)"
Push-Location "$ProjectDir\frontend"
npm install
# Windows deletes env vars assigned "" (SetEnvironmentVariable treats "" as unset),
# so $env:VITE_API_URL = "" never actually reaches Vite -- use a temp env file instead.
$envFile = ".env.production.local"
"VITE_API_URL=" | Out-File -FilePath $envFile -Encoding utf8 -NoNewline
npm run build
Remove-Item $envFile -ErrorAction SilentlyContinue
Pop-Location

Write-Host "==> Running PyInstaller"
& "$VenvDir\Scripts\pyinstaller.exe" worm_tracker_windows.spec --clean --noconfirm

Write-Host ""
Write-Host "Onedir build complete!"
Write-Host "  App folder : dist\ParaTracker\"
Write-Host "  Launch     : dist\ParaTracker\ParaTracker.exe"
Write-Host ""

# ---------------------------------------------------------------------------
# Installer (Inno Setup) - optional. Skips gracefully if ISCC.exe isn't found.
# ---------------------------------------------------------------------------
if ($SkipInstaller) {
    Write-Host "==> Skipping installer (-SkipInstaller)"
    exit 0
}

Write-Host "==> Building Windows installer (Inno Setup)"

# Version is the single source of truth in worm_tracker.spec's Info.plist.
$specText = Get-Content "$ProjectDir\worm_tracker.spec" -Raw
$verMatch = [regex]::Match($specText, '"CFBundleShortVersionString"\s*:\s*"([^"]+)"')
if (-not $verMatch.Success) {
    Write-Error "ERROR: could not read CFBundleShortVersionString from worm_tracker.spec"
    exit 1
}
$AppVersion = $verMatch.Groups[1].Value
Write-Host "    Version: $AppVersion"

# Locate ISCC.exe: PATH first, then the standard Inno Setup 6 install dirs.
$iscc = (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source
if (-not $iscc) {
    foreach ($candidate in @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        # winget installs Inno Setup per-user here by default
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    )) {
        if (Test-Path $candidate) { $iscc = $candidate; break }
    }
}

if (-not $iscc) {
    Write-Host ""
    Write-Warning "Inno Setup (ISCC.exe) not found - skipping installer."
    Write-Host "  The onedir build in dist\ParaTracker\ is ready; you can still zip and distribute it."
    Write-Host "  To build the installer, install Inno Setup and re-run this script:"
    Write-Host "      winget install JRSoftware.InnoSetup"
    Write-Host "  Or build it by hand once dist\ParaTracker\ exists:"
    Write-Host "      & `"`${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe`" /DMyAppVersion=$AppVersion installer\paratracker.iss"
    Write-Host ""
    exit 0
}

& $iscc "/DMyAppVersion=$AppVersion" "$ProjectDir\installer\paratracker.iss"
if ($LASTEXITCODE -ne 0) {
    Write-Error "ERROR: Inno Setup compilation failed (exit code $LASTEXITCODE)."
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Installer build complete!"
Write-Host "  Installer  : dist\ParaTracker-$AppVersion-Setup.exe"
Write-Host ""
