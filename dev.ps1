# dev.ps1 - Windows dev helper (equivalent of the Makefile)
# Usage: .\dev.ps1 [target]
#
# Targets:
#   run              Start backend (port 8000) + frontend dev server (port 5173)
#   build            Install frontend node_modules
#   venv             Create Python venv and install requirements.txt
#   weights          Download YOLO weights from Google Drive (verified by SHA256)
#   clean            Run clean-python + clean-frontend
#   clean-python     Remove __pycache__ and .pyc/.pyo/.pyd files
#   clean-python-env Remove the Python virtual environment
#   clean-frontend   Remove frontend/dist and frontend/node_modules
#   clean-weights    Remove the weights/ directory

param([string]$Target = "run")

$ErrorActionPreference = "Stop"

$ProjectDir  = $PSScriptRoot
$VenvDir     = "$ProjectDir\venv"
$StampFile   = "$VenvDir\.requirements-stamp"
$WeightsSha  = "f7712cb708c94a788f36fe8cbf9c1f479e399286ab3c9afbbb318e4c6d9f80fe"
$WeightsDir  = "$ProjectDir\weights"
$WeightsFile = "$WeightsDir\worm_yolov8seg-$WeightsSha.pt"
$GDriveId    = "1s9IiJdX9vUkwJ9MOFV1rZDEWsKyk_ofk"

# ---------------------------------------------------------------------------

function Check-Npm {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        Write-Error @"
ERROR: npm is not installed or not on PATH.
Please install Node.js (which includes npm):
  - Download from https://nodejs.org/
  - Or via winget: winget install OpenJS.NodeJS
"@
        exit 1
    }
}

function Invoke-Venv {
    if (-not (Test-Path "$VenvDir\Scripts\Activate.ps1")) {
        $created = $false

        # Prefer Python 3.11 via the Windows Python Launcher
        if (Get-Command py -ErrorAction SilentlyContinue) {
            $ver = py -3.11 --version 2>$null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "==> Creating venv with Python 3.11 (py -3.11) ..."
                py -3.11 -m venv $VenvDir
                $created = $true
            }
        }

        if (-not $created) {
            if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
                Write-Error "ERROR: Python is not installed or not on PATH. Please install Python from https://python.org/"
                exit 1
            }
            $fallbackVer = python --version 2>&1
            Write-Host "==> Python 3.11 not found - falling back to $fallbackVer ..."
            python -m venv $VenvDir
        }
    }

    $reqFile = "$ProjectDir\requirements.txt"
    if (-not (Test-Path $StampFile) -or
        ((Get-Item $reqFile).LastWriteTime -gt (Get-Item $StampFile).LastWriteTime)) {
        Write-Host "==> Installing Python requirements ..."
        & "$VenvDir\Scripts\pip.exe" install -r $reqFile
        New-Item -ItemType File -Path $StampFile -Force | Out-Null
    } else {
        Write-Host "==> Python requirements already up to date."
    }
}

function Invoke-Build {
    Check-Npm
    $installStamp = "$ProjectDir\frontend\node_modules\.install-stamp"
    $pkgJson      = "$ProjectDir\frontend\package.json"
    if (-not (Test-Path $installStamp) -or
        ((Get-Item $pkgJson).LastWriteTime -gt (Get-Item $installStamp).LastWriteTime)) {
        Write-Host "==> Installing frontend dependencies ..."
        Push-Location "$ProjectDir\frontend"
        npm install
        Pop-Location
        New-Item -ItemType File -Path $installStamp -Force | Out-Null
    } else {
        Write-Host "==> Frontend dependencies already up to date."
    }
}

function Invoke-Weights {
    if (Test-Path $WeightsFile) {
        Write-Host "==> Weights already present at $WeightsFile"
        return
    }
    Invoke-Venv
    New-Item -ItemType Directory -Path $WeightsDir -Force | Out-Null
    Write-Host "==> Downloading YOLO weights from Google Drive (id=$GDriveId) ..."
    $tmp = [System.IO.Path]::GetTempFileName()
    try {
        & "$VenvDir\Scripts\python.exe" -m gdown $GDriveId -O $tmp
        $actual = (Get-FileHash -Path $tmp -Algorithm SHA256).Hash.ToLower()
        if ($actual -ne $WeightsSha) {
            Write-Error @"
ERROR: SHA256 mismatch for downloaded weights.
  expected: $WeightsSha
  actual:   $actual
"@
            exit 1
        }
        Move-Item $tmp $WeightsFile
        Write-Host "==> Weights verified and saved to $WeightsFile"
    } catch {
        Remove-Item $tmp -ErrorAction SilentlyContinue
        throw
    }
}

function Invoke-Run {
    Invoke-Venv
    Invoke-Build

    $conn = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
    if ($conn) {
        Write-Host "==> Killing existing process on port 8000 (PID $($conn.OwningProcess)) ..."
        Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
    }

    Write-Host "==> Starting backend (port 8000) and frontend (port 5173) ..."
    Write-Host "    Press Ctrl+C to stop both.`n"

    $backend = Start-Process `
        -FilePath "$VenvDir\Scripts\uvicorn.exe" `
        -ArgumentList "app.main:app", "--reload", "--port", "8000" `
        -WorkingDirectory $ProjectDir `
        -PassThru -NoNewWindow

    try {
        Push-Location "$ProjectDir\frontend"
        npm run dev
    } finally {
        Pop-Location
        if (-not $backend.HasExited) {
            Write-Host "`n==> Stopping backend ..."
            $backend | Stop-Process -Force
        }
    }
}

function Invoke-CleanPython {
    Write-Host "==> Removing __pycache__ and compiled Python files ..."
    Get-ChildItem -Path $ProjectDir -Recurse -Filter "__pycache__" -Directory |
        Where-Object { $_.FullName -notmatch '\\(venv|node_modules)\\' } |
        Remove-Item -Recurse -Force
    Get-ChildItem -Path $ProjectDir -Recurse -Include "*.pyc","*.pyo","*.pyd" |
        Where-Object { $_.FullName -notmatch '\\(venv|node_modules)\\' } |
        Remove-Item -Force
}

function Invoke-CleanPythonEnv {
    if (Test-Path $VenvDir) {
        Write-Host "==> Removing Python virtual environment at $VenvDir ..."
        Remove-Item $VenvDir -Recurse -Force
    } else {
        Write-Host "==> No virtual environment at $VenvDir - nothing to remove."
    }
}

function Invoke-CleanFrontend {
    Write-Host "==> Removing frontend/dist and frontend/node_modules ..."
    Remove-Item "$ProjectDir\frontend\dist"         -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item "$ProjectDir\frontend\node_modules" -Recurse -Force -ErrorAction SilentlyContinue
}

function Invoke-CleanWeights {
    Write-Host "==> Removing weights/ ..."
    Remove-Item $WeightsDir -Recurse -Force -ErrorAction SilentlyContinue
}

function Invoke-Clean {
    Invoke-CleanPython
    Invoke-CleanFrontend
    Write-Host "Done."
}

# ---------------------------------------------------------------------------

switch ($Target) {
    "run"              { Invoke-Run }
    "build"            { Check-Npm; Invoke-Build }
    "venv"             { Invoke-Venv;          Write-Host "Done." }
    "weights"          { Invoke-Weights;        Write-Host "Done." }
    "clean"            { Invoke-Clean }
    "clean-python"     { Invoke-CleanPython;    Write-Host "Done." }
    "clean-python-env" { Invoke-CleanPythonEnv; Write-Host "Done." }
    "clean-frontend"   { Invoke-CleanFrontend;  Write-Host "Done." }
    "clean-weights"    { Invoke-CleanWeights;   Write-Host "Done." }
    default {
        Write-Host @"
Usage: .\dev.ps1 [target]

Targets:
  run              Start backend (port 8000) + frontend dev server (port 5173)
  build            Install frontend node_modules
  venv             Create Python venv and install requirements.txt
  weights          Download YOLO weights from Google Drive (verified by SHA256)
  clean            Run clean-python + clean-frontend
  clean-python     Remove __pycache__ and .pyc/.pyo/.pyd files
  clean-python-env Remove the Python virtual environment
  clean-frontend   Remove frontend/dist and frontend/node_modules
  clean-weights    Remove the weights/ directory
"@
    }
}
