# build_windows.ps1 - Build ParaTracker.exe (Windows onedir PyInstaller package)
# Usage: .\build_windows.ps1

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
Write-Host "Build complete!"
Write-Host "  App folder : dist\ParaTracker\"
Write-Host "  Launch     : dist\ParaTracker\ParaTracker.exe"
Write-Host ""
