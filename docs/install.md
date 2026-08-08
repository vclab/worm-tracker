# Installation & Development

ParaTracker runs as a **backend** (FastAPI, port 8000) plus a **frontend dev server** (Vite, port 5173). Helper scripts install dependencies, download the tracking model, free the ports, and start both together: a `Makefile` on macOS/Linux and an equivalent `dev.ps1` on Windows.

**What you'll need on any OS:**

- **Python 3.11**: use this exact version. `requirements.txt` pins `numpy<2` (NumPy 2.x breaks the scikit-image/OpenCV stack), and NumPy 1.x has **no wheels for Python 3.13+**, so installation fails on newer Pythons.
- **Node.js 18+** (includes `npm`).
- **FFmpeg is *not* a prerequisite**: the `imageio-ffmpeg` package (installed into the virtual environment automatically) bundles a static FFmpeg binary the app uses for H.264 transcoding. A system FFmpeg on your `PATH` is used only as a fallback.

You only do the setup once. Pick your platform:

## Windows

**1. Install prerequisites (PowerShell):**

```powershell
winget install Python.Python.3.11
winget install OpenJS.NodeJS
```

**2. Allow the helper script to run (one time, no admin needed).** PowerShell blocks local scripts by default, so `.\dev.ps1` fails the first time with `running scripts is disabled on this system`. Fix it once:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Answer `Y` when prompted. (Prefer not to change any policy? Prefix each command instead: `powershell -ExecutionPolicy Bypass -File .\dev.ps1 <target>`.)

**3. Get the code:**

```powershell
git clone https://github.com/vclab/worm-tracker.git
cd worm-tracker
```

**4. Download the tracking model** (required once; SHA256-verified):

```powershell
.\dev.ps1 weights
```

**5. Start the app:**

```powershell
.\dev.ps1 run
```

This creates the virtual environment (`.\venv`), installs dependencies, and starts both servers. Open **<http://127.0.0.1:5173>**. Press **Ctrl+C** to stop both.

## macOS

**1. Install prerequisites** (via [Homebrew](https://brew.sh); `make` comes from Apple's Command Line Tools):

```bash
xcode-select --install        # provides `make`, if you don't already have it
brew install python@3.11 node
```

**2. Get the code:**

```bash
git clone https://github.com/vclab/worm-tracker.git
cd worm-tracker
```

**3. Download the tracking model** (required once; SHA256-verified):

```bash
make weights
```

**4. Start the app:**

```bash
make run
```

This creates the virtual environment (`~/venv/worm-tracker`), installs dependencies, and starts both servers. Open **<http://127.0.0.1:5173>**. Press **Ctrl+C** to stop both. (If you skip step 3, `make run` will download the model for you.)

## Linux

**1. Install prerequisites** (Debian/Ubuntu shown; `python3.11` may need the deadsnakes PPA):

```bash
sudo apt install python3.11 python3.11-venv nodejs npm make
```

**2. Get the code:**

```bash
git clone https://github.com/vclab/worm-tracker.git
cd worm-tracker
```

**3. Download the tracking model** and **4. start the app:**

```bash
make weights
make run
```

Open **<http://127.0.0.1:5173>**. Press **Ctrl+C** to stop both. Linux is a development target only; there is no packaged `.deb`/`.rpm`/AppImage.

## Command reference

**macOS / Linux (`make <target>`):**

| Target | What it does |
| --- | --- |
| `make run` | Start backend + frontend (ensures venv, deps, weights) |
| `make weights` | Download and verify the YOLO model |
| `make venv` | Create the Python environment (`~/venv/worm-tracker`) and install requirements |
| `make build` | Install frontend dependencies |
| `make dist` / `make dmg` / `make release` | Build the macOS app / DMG (see [Building for Distribution](build.md)) |
| `make clean` | Remove caches, frontend build, and `build/`+`dist/` |
| `make clean-python` / `make clean-python-env` / `make clean-frontend` / `make clean-weights` | Targeted cleanup |

**Windows (`.\dev.ps1 <target>`):**

| Target | What it does |
| --- | --- |
| `.\dev.ps1 run` | Start backend + frontend |
| `.\dev.ps1 weights` | Download and verify the YOLO model |
| `.\dev.ps1 venv` | Create the Python environment (`.\venv`) and install requirements |
| `.\dev.ps1 build` | Install frontend dependencies |
| `.\dev.ps1 clean` / `.\dev.ps1 clean-python` / `.\dev.ps1 clean-python-env` / `.\dev.ps1 clean-frontend` / `.\dev.ps1 clean-weights` | Cleanup |
| `.\build_windows.ps1` | Build the `.exe` + installer for distribution (separate script; see [Building for Distribution](build.md)) |

> The venv location differs per OS: `~/venv/worm-tracker` on macOS/Linux, `.\venv` inside the project folder on Windows.

> **NumPy note:** NumPy must stay below 2 (2.x breaks the image-processing stack). It is pinned to `numpy<2` in `requirements.txt`; don't manually upgrade it.

## Manual run (advanced)

To start the servers yourself instead of using the scripts (skips the automatic port-cleanup and clean shutdown; download the model first):

```bash
# Terminal 1: backend
source ~/venv/worm-tracker/bin/activate      # macOS/Linux
# .\venv\Scripts\activate                    # Windows (PowerShell)
uvicorn app.main:app --reload --port 8000

# Terminal 2: frontend
cd frontend
npm run dev
```
