# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ParaTracker** (repo is still named `worm-tracker`; the app was renamed from WormTracker in v1.4.0) is a full-stack application for tracking C. elegans and microfilaria in video data. It extracts skeleton-based keypoints to capture body deformation over time for behavioral analysis. Two selectable pipelines: a classical CV approach (thresholding + skeleton extraction) and a YOLOv8-seg deep-learning pipeline.

- **Backend**: Python + FastAPI (`/app`)
- **Frontend**: React + Vite (`/frontend`)

## Deployment Targets

The code is designed for four deployment settings:

| Target | Status | Purpose |
|---|---|---|
| macOS desktop (arm64) | Packaging **implemented** | Primary user platform. Distributed as a signed DMG produced by `make release`. |
| Windows desktop | Packaging **implemented** (onedir exe) | Primary user platform. Dev workflow via `dev.ps1`; `build_windows.ps1` produces `dist\ParaTracker\ParaTracker.exe`. Installer (Inno Setup) + code signing still on the roadmap (see `## Distribution` below). |
| Linux desktop | Dev only | Not a distribution target. The Makefile workflow runs on Linux; there is no packaged `.deb`/`.rpm`/AppImage. |
| Cloud / server | Ad-hoc | No packaged deployment. Run `uvicorn app.main:app` directly, skip `launcher.py`. See `## Cloud deployment` below. |

Primary dev environments: **macOS and Windows**. All code paths should work on both. Linux paths are inherited from macOS (POSIX) but only lightly tested.

## Repository Layout

```
app/                    Backend (FastAPI, tracking pipelines)
  main.py               FastAPI server, endpoints, job queue
  worm_tracker.py       Classical CV pipeline (+ CLI entry point)
  dl_worm_tracker.py    YOLOv8-seg deep-learning pipeline
  aggregation.py        Cross-video rollup (per-worm / per-video tables)
  config.py             Platform-specific config file handling
frontend/               React + Vite frontend
launcher.py             PyInstaller entry point for the packaged app
worm_tracker.spec       PyInstaller spec, macOS (.app bundle, hidden imports)
worm_tracker_windows.spec  PyInstaller spec, Windows (onedir exe; keep in sync with the macOS spec)
scripts/                Packaging helpers (macOS-specific for now)
  sign_app.sh           Ad-hoc codesign the .app
  make_dmg.sh           Build the DMG via hdiutil
  READ ME FIRST.txt     First-launch instructions bundled in the DMG
Makefile                macOS/Linux dev + macOS distribution
dev.ps1                 Windows dev workflow
build_windows.ps1       Windows distribution: build the onedir ParaTracker.exe
build.sh                bash builder invoked by `make dist`
requirements.txt        Python deps
weights/                YOLO model (downloaded by `make weights`, git-ignored)
```

## Architecture

### Backend (`/app`)

**`main.py`** is the FastAPI server. Key endpoints:

- `POST /upload`: accepts video + parameters, queues job, returns `job_id`
- `GET /jobs`: list jobs with status, progress, download paths (`limit`/`offset`)
- `DELETE /jobs/{job_id}`: delete job record and output files
- `GET /download/{job_id}/{filename}`: file download
- `GET /jobs/{job_id}/keypoints`: head/tail positions per worm (for the head/tail correction UI)
- `POST /jobs/{job_id}/flip/{worm_id}`: flip head↔tail for a worm; recomputes stats and rebuilds ZIPs in background
- `POST /jobs/{job_id}/rerun`: re-queue a completed job with updated parameters (copies `*_original.*` from output folder back to uploads)
- `POST /cancel/{job_id}`: cancel a pending or processing job
- `GET /api/settings`, `POST /api/settings`: read/write `outputs_dir` (change requires app restart)
- `POST /api/heartbeat`: browser presence ping (packaged app only)
- `GET /api/health`: health check

Jobs are processed by a background queue worker thread, one at a time. Job state is persisted in `{outputs_dir}/jobs.db` (SQLite, WAL mode).

In packaged mode (`sys.frozen=True`), a heartbeat watchdog shuts down the process if no browser ping is received for 20 s (60 s startup grace period). The watchdog defers shutdown while any job is `processing`. The frontend pings `POST /api/heartbeat` every 5 s (only when running same-origin, so dev mode is unaffected).

Running the app twice against the same outputs folder is handled at two layers:

1. **Launcher pre-check (all OSes, packaged app)**: `launcher.py` reads `{outputs_dir}/paratracker.port` (written by the primary at startup, cleaned up on exit via `atexit`). If the file exists and the port responds to a TCP probe (500 ms timeout), the launcher opens `http://127.0.0.1:<port>` in the browser (bringing the existing tab/window forward on most browsers) and exits without starting uvicorn. If the port file is stale (crash left it behind), the probe fails, the launcher removes the file and proceeds as a normal cold start. Helpers: `_find_running_primary()`, `_write_port_file()`, `_delete_port_file()` in `launcher.py`.

2. **Lifespan flock (POSIX only, defence in depth)**: if two launchers race past the pre-check simultaneously, `_acquire_outputs_lock()` in the lifespan handler raises `RuntimeError` for the loser. Uvicorn reports `lifespan.startup.failed` and exits with a non-zero code. Log line: `Another ParaTracker process is already using {outputs_dir}. Close the other instance first.`

**Windows**: the launcher pre-check works (no OS-specific dependency), but if a race gets past it, `fcntl` is unavailable so both instances continue. Two full instances would then coexist against the same `jobs.db`; SQLite WAL prevents corruption but they race on job pickup. A Windows-native mutex (e.g. `CreateMutex` via `ctypes`) is on the roadmap for full parity.

**`worm_tracker.py`** is the classical CV pipeline:

1. Frame preprocessing (grayscale, blur, adaptive threshold)
2. Worm detection via connected components
3. Skeleton extraction using scikit-image skeletonization
4. Multi-object tracking with the Hungarian algorithm (`scipy.optimize.linear_sum_assignment`)
5. Outputs: annotated MP4, YAML metadata, NPZ keypoints, motion stats JSON, CSV files

Also serves as a standalone CLI (`python -m app.worm_tracker ...`).

**`dl_worm_tracker.py`** is the YOLOv8-seg pipeline. Imported lazily from `main.py` (guarded by pipeline selection), so it must be listed explicitly in `worm_tracker.spec` `hiddenimports` for PyInstaller to include it.

Key tracking parameters (configurable via UI, defaults in code):

- `keypoints_per_worm` (15): skeleton points per worm
- `area_threshold` (50): minimum pixels for a valid worm region
- `max_age` (35): frames to keep tracking a missing worm before dropping
- `persistence` (50): minimum frames tracked to include a worm in output

Partial worms (touching frame edges) are tracked but excluded from final output. They are stored in NPZ under `partial_{id}` keys so the video can still annotate them.

### Frontend (`/frontend/src`)

- **`App.jsx`**: main app. Upload, parameter form, before/after comparison slider, play/pause, download links, head/tail correction, re-run, job history integration.
- **`JobHistory.jsx`**: polls `GET /jobs`, shows live progress, highlights the current job, loads/deletes jobs.
- **`HeadTailCorrector.jsx`**: canvas overlay for flipping head/tail per worm.
- **`MotionCharts.jsx`**: Recharts heatmap + timeline (overall, head, mid-body, tail).
- **`Settings.jsx`**: settings panel (⚙ button). Changes `outputs_dir`; warns that a restart is required.
- **`ErrorBoundary.jsx`**: React error boundary for graceful render failures.
- **`api.js`**: `API` base URL. `""` (same-origin) when `VITE_API_URL` is empty (packaged/production build), `"http://127.0.0.1:8000"` in dev.

### Packaged-app entry point (`launcher.py` + `worm_tracker.spec`)

`launcher.py` binds a socket (keeps it open to avoid a port race), opens the browser after a short delay, then starts uvicorn.

- **POSIX** (macOS, Linux): the socket fd is passed directly to uvicorn (`fd=sock.fileno()`).
- **Windows**: the socket is closed first and uvicorn is given host/port (fd inheritance for sockets is not supported).

`worm_tracker.spec` bundles `frontend/dist/` as `frontend_dist/`, the `app/` package, and `imageio_ffmpeg/` (includes the static FFmpeg binary). FFmpeg is resolved at runtime via `imageio_ffmpeg.get_ffmpeg_exe()`. Hidden imports explicitly list every `app.*` module (including `app.dl_worm_tracker`, which is imported lazily) and `pandas` (required by `app.aggregation` and CSV export; must NOT appear in `excludes`).

## Development

Both platforms need two user-installed prerequisites: **Python 3.11** and **Node.js 18+**. Use Python **3.11 specifically** — `requirements.txt` pins `numpy<2` (NumPy 2.x breaks the scikit-image/opencv stack), and NumPy 1.x has no wheels for Python 3.13+, so `pip install -r requirements.txt` fails on newer Pythons.

**FFmpeg is NOT a user prerequisite.** `requirements.txt` includes `imageio-ffmpeg`, which bundles a static FFmpeg binary; `app/main.py:_resolve_ffmpeg()` uses `imageio_ffmpeg.get_ffmpeg_exe()` and only falls back to a system FFmpeg on `PATH`. Neither the Makefile nor `dev.ps1` checks for system FFmpeg.

### macOS / Linux workflow

Prerequisites (macOS via Homebrew; `make` comes from Xcode Command Line Tools, `xcode-select --install`):
```bash
brew install python@3.11 node
```

One-time setup + run:
```bash
make weights   # download the YOLO model (SHA256-verified)
make run       # start backend (port 8000) + frontend (port 5173)
```

Other Make targets: see `## Make targets` below.

Manual (advanced, two terminals):
```bash
# Terminal 1: backend
source ~/venv/worm-tracker/bin/activate
uvicorn app.main:app --reload --port 8000

# Terminal 2: frontend
cd frontend && npm run dev
```

The venv lives at `~/venv/worm-tracker/` on macOS/Linux.

### Windows workflow

Prerequisites (use PowerShell):
```powershell
winget install Python.Python.3.11
winget install OpenJS.NodeJS
```

PowerShell blocks local scripts by default, so `.\dev.ps1` fails the first time with `running scripts is disabled on this system`. Allow local scripts for the current user once (no admin needed):
```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```
(Or invoke without changing policy: `powershell -ExecutionPolicy Bypass -File .\dev.ps1 <target>`.)

One-time setup + run:
```powershell
.\dev.ps1 weights
.\dev.ps1 run
```

Other `dev.ps1` targets: `venv`, `build`, `clean`, `clean-python`, `clean-python-env`, `clean-frontend`, `clean-weights`.

The venv lives at `.\venv\` (inside the project folder) on Windows.

Windows-specific runtime behavior:
- The outputs-folder flock is skipped (`fcntl` unavailable). A second instance on the same outputs folder is allowed; SQLite WAL still protects the DB from corruption.
- `launcher.py` passes host/port to uvicorn instead of a socket fd (Windows can't inherit socket fds).

### CLI (all OSes, no UI)

There is no unified CLI with a `--pipeline` flag; each pipeline has its own module entry point.

**Classical pipeline** (no model needed):
```bash
python -m app.worm_tracker input.mov output_dir \
    --keypoints 15 --min-area 50 --max-age 35 --persistence 50
```

**YOLO pipeline** (requires a `.pt` weights file):
```bash
python -m app.dl_worm_tracker input.mov output_dir \
    --model weights/worm_yolov8seg-<sha>.pt \
    --keypoints 15 --min-area 50 --max-age 35 --persistence 50 \
    --conf-threshold 0.25
```

Both CLIs write to `output_dir/{timestamp}_{output_name}/` and produce the same output-file layout as the web UI.

## Distribution

### macOS (implemented)

`make release` produces `dist/ParaTracker-<version>-arm64.dmg`. The pipeline:

1. `make dist`: full clean rebuild. Runs `clean` → `venv` → `weights` → `build.sh`. `build.sh` builds the frontend, runs PyInstaller, then calls `scripts/sign_app.sh` to ad-hoc sign the `.app`.
2. `make dmg`: packages the signed `.app`, an `/Applications` symlink, and `scripts/READ ME FIRST.txt` into a DMG using `hdiutil create -srcfolder`.

Design notes:
- **Ad-hoc signed only** (no paid Developer ID). Users must right-click and choose Open on first launch; documented in `scripts/READ ME FIRST.txt` which appears in the mounted DMG.
- **arm64 only.** Covers Apple Silicon Macs (Nov 2020+). Intel Macs not supported.
- **No notarization.** Gatekeeper shows a warning on first launch; the right-click-Open bypasses it. Users only do this once per install.
- **Custom DMG layout is deliberately skipped.** `hdiutil create -srcfolder` bypasses the mount/AppleScript/unmount cycle that `create-dmg` uses (its unmount step fails intermittently on macOS 13+ because Finder holds the RW volume open). Tradeoff: no custom icon positions or background image.

Version is read from `CFBundleShortVersionString` in `worm_tracker.spec`; bump there to change the version everywhere.

**YOLO weights are bundled** (since v1.4.1). `worm_tracker.spec` includes `(str(PROJECT / "weights"), "weights")` in `datas`, and `app/main.py` branches `DEFAULT_WEIGHTS` on `sys.frozen`: `sys._MEIPASS/weights/` when packaged, `APP_DIR.parent/weights/` when running from source. Both classical and YOLO pipelines work out of the box in the DMG. A user can still override the default by setting `model_path` in Settings (⚙) to point at a different `.pt` file.

### Windows (implemented — onedir exe)

`build_windows.ps1` produces `dist\ParaTracker\ParaTracker.exe` (PyInstaller **onedir** — a folder containing the exe plus `_internal\`). Distribute by zipping the `dist\ParaTracker\` folder; the recipient extracts it and double-clicks `ParaTracker.exe` (no Python, Node, or FFmpeg needed on the target machine — FFmpeg is bundled).

The build pipeline (`build_windows.ps1`):

1. Activates the project venv (`.\venv\`, created by `.\dev.ps1 venv`) and ensures `pyinstaller` + `imageio-ffmpeg` are installed.
2. Requires the YOLO weights to be present (`.\dev.ps1 weights` first) — the exe fails to build without them.
3. Builds the frontend with `VITE_API_URL=""` (same-origin). It writes `frontend/.env.production.local` with an empty `VITE_API_URL` because Windows drops env vars assigned `""` (`SetEnvironmentVariable` treats `""` as unset), so `$env:VITE_API_URL = ""` never reaches Vite.
4. Runs `pyinstaller worm_tracker_windows.spec --clean --noconfirm`.

**Uses a dedicated spec, `worm_tracker_windows.spec`** — NOT the cross-platform `worm_tracker.spec`, which ends with a macOS-only `BUNDLE` step and references the `.icns` icon. The Windows spec is a `COLLECT`-only onedir build. Its `datas`, `hiddenimports`, and `excludes` are kept in sync with `worm_tracker.spec`; if you add a hidden import or bundled data file to one, mirror it in the other. It explicitly lists every `app.*` module (including the lazily-imported `app.dl_worm_tracker`) and `pandas`, so both pipelines and the aggregate/compare pages work in the packaged exe.

**No console window (`console=False`).** There is no terminal to Ctrl-C and no window to close, so the browser-heartbeat watchdog (`app/main.py`, active when `sys.frozen`) is the only clean shutdown path: when the browser tab is closed and no job is processing, no `POST /api/heartbeat` arrives for 20 s and the process exits via `os.kill(os.getpid(), signal.SIGTERM)` (maps to `TerminateProcess` on Windows — a hard kill, which reliably terminates). The hard kill skips `atexit`, so `paratracker.port` is left behind, but the launcher's TCP probe treats a stale port file as dead and removes it on the next launch, so it is self-healing.

**`launcher.py:_silence_stdio()`** is required for the windowless build: with `console=False`, `sys.stdout`/`sys.stderr` are `None`, and any write to them — `tqdm`, the `print()` calls in `app/main.py`, uvicorn's log formatter calling `.isatty()` — would raise `AttributeError`. `main()` calls it first thing when `sys.frozen`, redirecting both to `os.devnull`.

**Icon.** The spec uses `paratracker.ico` if it exists next to the spec, otherwise the exe ships with PyInstaller's default icon. No `.ico` is committed yet (only `paratracker.icns` for macOS); add one to brand the exe/taskbar.

Not yet done (roadmap):

- **Installer** (Inno Setup): install to `Program Files`, Start Menu shortcut, uninstaller, "Programs & Features" entry. For now distribution is a zipped onedir folder.
- **Code signing** (`signtool`): no cert planned. SmartScreen shows "Windows protected your PC" on first launch; users click "More info" → "Run anyway".
- **Single-instance mutex**: `fcntl` is unavailable on Windows, so the outputs-folder flock is skipped (see the single-instance notes above). A `CreateMutex`-via-`ctypes` guard is still outstanding.
- **CI/CD** (`.github/workflows/release.yml`) to build macOS + Windows artifacts on native runners.

### Linux

No packaged distribution planned. Devs can run from source via the Makefile.

### Cloud / server deployment

No packaged artifact. To run the backend as a service:

- Skip `launcher.py`. Run `uvicorn app.main:app --host 0.0.0.0 --port 8000` (add `--workers N` only if `active_jobs_lock` and the SQLite job queue are reviewed for cross-process safety; currently they assume a single process per outputs folder).
- Serve the frontend either by letting FastAPI's `StaticFiles` mount at `/` handle `frontend_dist/` (works in packaged mode; the same code path works if you copy the built frontend into `sys._MEIPASS` or adjust `_find_frontend_dist()`), or serve `frontend/dist/` from nginx and reverse-proxy `/api/*` and `/upload` etc. to uvicorn.
- Build the frontend with `VITE_API_URL=""` so the client uses same-origin requests.
- The heartbeat watchdog is inactive outside `sys.frozen`, so cloud deploys will not auto-shutdown.
- App has **no built-in authentication or TLS**. Put it behind a reverse proxy (nginx, Caddy) that handles both.

## Make targets

`make <target>` (macOS/Linux). Prerequisites are checked at runtime; missing tools produce a clear error with install instructions.

**Development:**

| Target | Effect |
|---|---|
| `make run` | Kill port 8000, start backend + frontend. Ctrl+C stops both. Ensures venv, node_modules, weights. |
| `make venv` | Create `~/venv/worm-tracker/`, install `requirements.txt`. Idempotent. |
| `make build` | `npm install` in `frontend/`. Idempotent. |
| `make weights` | Download YOLO model, verify SHA256, save to `weights/`. |

**Distribution (macOS):**

| Target | Effect |
|---|---|
| `make dist` | Full clean rebuild of the `.app`. Ad-hoc signed. Slow (3 to 6 min). |
| `make dmg` | Package existing `dist/ParaTracker.app` into `dist/ParaTracker-<v>-arm64.dmg`. Seconds. |
| `make release` | `dist` + `dmg`. Use for actual releases. |

**Cleanup:**

| Target | Effect |
|---|---|
| `make clean` | Runs `clean-python` + `clean-frontend` + `clean-build`. |
| `make clean-python` | Remove `__pycache__` and `*.pyc/*.pyo/*.pyd`. |
| `make clean-python-env` | Remove `~/venv/worm-tracker/`. Not part of `clean`. |
| `make clean-frontend` | Remove `frontend/dist` and `frontend/node_modules`. |
| `make clean-build` | Remove `build/` and `dist/`. |
| `make clean-weights` | Remove `weights/`. Not part of `clean`. |

Windows equivalent: `dev.ps1` supports `run`, `build`, `venv`, `weights`, and the same `clean-*` targets. Windows distribution is a separate script — run `.\build_windows.ps1` to produce the onedir `dist\ParaTracker\ParaTracker.exe` (see `## Distribution → Windows`). `dev.ps1` itself has no `dist`/`release` target.

## File Locations

Data lives in three distinct places: user data (persists across app upgrades), development artifacts (reproducible from source), and bundle contents (inside the packaged app).

### User data (persists across app upgrades and uninstalls)

**Config file.** Platform-specific; managed by `app/config.py`:

| Platform | Path |
|---|---|
| macOS   | `~/Library/Application Support/ParaTracker/config.json` |
| Windows | `%APPDATA%/ParaTracker/config.json` |
| Linux   | `~/.config/ParaTracker/config.json` |

Contents: `{"outputs_dir": "...", "model_path": "..."}`. The outputs directory is user-configurable via the Settings panel (⚙ in the UI) or by editing the file directly; changes require an app restart. If the stored `outputs_dir` is unwritable at startup (e.g. an external drive is unmounted), `load_config()` falls back to the default (`~/Documents/ParaTracker/`) and logs a warning.

**Legacy path migration (v1.3.0 -> v1.4.0).** The app was renamed from WormTracker to ParaTracker in v1.4.0. On first launch after upgrade, `app/config.py:get_config_dir()` renames `.../WormTracker/` to `.../ParaTracker/` in place if the new dir does not exist, and `_migrate_legacy_outputs_dir()` does the same for `~/Documents/WormTracker/` when the user was still on the default outputs path. Both migrations are one-shot and idempotent. A custom `outputs_dir` (external drive, alt location) is never touched; only the default-path case is auto-renamed.

**Outputs directory** (default `~/Documents/ParaTracker/` on all OSes, configurable). Everything in here is user data. The folder is self-contained and portable, so moving it to another drive or another machine takes the DB, all job outputs, and any in-flight uploads with it.

- `{outputs_dir}/jobs.db`: SQLite job database (WAL mode, one DB per outputs folder). Tracks job status, params, timestamps, output paths.
- `{outputs_dir}/paratracker.lock`: exclusive `flock` held for the lifetime of the running process; guarantees a single instance per outputs folder on POSIX. The kernel releases it on process death (even SIGKILL). Windows skips locking; SQLite WAL still protects the DB.
- `{outputs_dir}/paratracker.port`: TCP port the running primary is listening on. Written by `launcher.py` right after socket bind, removed via `atexit` on clean shutdown. Used by subsequent launches to detect an existing instance and open its URL instead of starting a duplicate. A stale file left over from a crash is auto-cleaned on the next launch when the TCP probe fails.
- `{outputs_dir}/uploads/`: transient upload staging. Files named `{job_id}__{original_filename}`. Persist across restarts to survive a crash mid-upload; usually cleaned up as jobs finish or are cancelled.
- `{outputs_dir}/{job_id}/{timestamp}_{output_name}/`: one directory per job (the `output_subfolder` column in `jobs.db`). Contains all output files documented under "Output Formats" below.

On startup, `migrate_existing_outputs()` scans the outputs folder for job directories not in the DB (anything except `uploads/`, `paratracker.lock`, and `paratracker.port` with a `*_tracked.mp4` inside) and imports them, so a fresh install can pick up jobs dropped in manually or left over from a previous DB.

**Full uninstall** = delete both the config directory AND the outputs directory. Removing only the .app or the installer leaves both intact.

### Development and build artifacts (NOT user data)

Reproducible from source; all git-ignored.

| Platform | Path | Purpose |
|---|---|---|
| macOS / Linux | `~/venv/worm-tracker/` | Python virtualenv |
| Windows | `<project>/venv/` | Python virtualenv |
| all | `<project>/weights/worm_yolov8seg-<sha256>.pt` | YOLO model, SHA256 in filename |
| all | `<project>/frontend/node_modules/` | npm deps |
| all | `<project>/frontend/dist/` | Vite production build |
| all | `<project>/build/` | PyInstaller work directory |
| all | `<project>/dist/` | PyInstaller output (`ParaTracker.app`, folder-mode `ParaTracker/`, `.dmg`) |
| all | `<project>/__pycache__/` (throughout) | Python bytecode |

### Packaged app bundle contents

Data files bundled by PyInstaller are extracted to `sys._MEIPASS` at runtime:

- **macOS folder-mode** (`dist/ParaTracker/_internal/`): visible on disk.
- **macOS `.app` bundle** (`ParaTracker.app/Contents/Frameworks/`): same layout, accessed via `sys._MEIPASS`.
- **Windows folder-mode** (`dist\ParaTracker\_internal\`): same as macOS folder-mode; built via `worm_tracker_windows.spec`.

Bundled subdirectories (`worm_tracker.spec` `datas`):

- `frontend_dist/`: production React build, mounted by `_find_frontend_dist()` in `app/main.py` and served by FastAPI's `StaticFiles` at `/`.
- `app/`: Python source.
- `imageio_ffmpeg/`: includes the static FFmpeg binary; `imageio_ffmpeg.get_ffmpeg_exe()` resolves it at runtime.

## Output Formats

Files inside each `{outputs_dir}/{job_id}/{timestamp}_{output_name}/`:

- **Video**: `*_tracked.mp4` (H.264, annotated with colored skeleton keypoints and worm IDs)
- **Original**: `*_original.*` (copy of the input video, needed for compare slider and re-run)
- **Metadata**: `*_metadata.yaml` (git version, timestamp, parameters, frame count)
- **Keypoints**: `*_keypoints.npz` (per-worm arrays `(num_keypoints, frames, 2)` in `[y, x]` order; partial worms stored under `partial_{id}` keys)
- **Motion Stats**: `*_motion_stats.json` (per-worm motion values for overall, head, mid-body, tail, and aggregate stats)
- **CSV**: `*_summary.csv` (one row per worm with mean motion values), `*_timeseries.csv` (columns `frame, worm_id, head_motion, mid_motion, tail_motion` per downsampled window)
- **ZIPs**: `{output_subfolder}.zip` (package: everything except CSVs), `{output_subfolder}_data.zip` (CSVs)

## No Automated Tests

This project has no test suite. Testing is manual via the web interface. A `validate_csv.py` script exists at the project root for spot-checking CSV output against NPZ/JSON ground truth.
