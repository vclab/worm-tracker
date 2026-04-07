# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Worm Tracker is a full-stack application for tracking C. elegans (microscopic worms) in video data. It extracts skeleton-based keypoints to capture body deformation over time for behavioral analysis.

- **Backend**: Python + FastAPI (`/app`)
- **Frontend**: React + Vite (`/frontend`)

## Workflow

- Always activate the Python virtual environment before running anything: `source ~/venv/worm-tracker/bin/activate`
- Development requires two terminals: one for the backend, one for the frontend dev server
- The packaged app is built with `./build.sh` (PyInstaller + pre-built React dist)

## Common Commands

### Backend (from project root)
```bash
source ~/venv/worm-tracker/bin/activate
pip install -r requirements.txt

# Run development server (auto-reload)
uvicorn app.main:app --reload --port 8000
```

### Frontend (from `/frontend`)
```bash
npm install
npm run dev      # Dev server at http://127.0.0.1:5173
npm run build    # Production build to frontend/dist/
npm run lint     # ESLint
```

### Build standalone macOS app
```bash
./build.sh       # Produces dist/WormTracker.app
```

### CLI Usage (standalone tracker, no web UI)
```bash
python -m app.worm_tracker input.mov output_dir --keypoints 15 --min-area 50 --max-age 35 --persistence 50
```

## Architecture

### Backend (`/app`)

**`main.py`** — FastAPI server. Key endpoints:
- `POST /upload` — accepts video + parameters, queues job, returns `job_id`
- `GET /jobs` — list all jobs with status, progress, and download paths (supports `limit`/`offset`)
- `DELETE /jobs/{job_id}` — delete job record and output files
- `GET /download/{job_id}/{filename}` — file download
- `GET /jobs/{job_id}/keypoints` — returns head/tail positions per worm for head/tail correction UI
- `POST /jobs/{job_id}/flip/{worm_id}` — flip head↔tail for a worm, recomputes stats + rebuilds ZIPs in background
- `POST /jobs/{job_id}/rerun` — re-queue a completed job with updated parameters (copies `*_original.*` from output folder to uploads)
- `POST /cancel/{job_id}` — cancel a pending or processing job
- `GET /api/settings` — get current settings (outputs_dir)
- `POST /api/settings` — update settings (outputs_dir); requires app restart to take effect
- `POST /api/heartbeat` — browser presence ping (packaged app only)
- `GET /api/health` — health check

Jobs are processed by a background queue worker thread (one at a time). Job state is persisted in `{outputs_dir}/jobs.db` (SQLite, WAL mode).

In packaged mode (`sys.frozen=True`), a heartbeat watchdog shuts down the process if no browser ping is received for 20s (with a 60s startup grace period).

**`worm_tracker.py`** — Core computer vision pipeline:
1. Frame preprocessing (grayscale, blur, adaptive threshold)
2. Worm detection via connected components
3. Skeleton extraction using scikit-image skeletonization
4. Multi-object tracking with Hungarian algorithm (`scipy.optimize.linear_sum_assignment`)
5. Output: annotated MP4 (raw), YAML metadata, NPZ keypoints, motion stats JSON, CSV files

Key tracking parameters (configurable via UI):
- `keypoints_per_worm` (default: 15) — skeleton points per worm
- `area_threshold` (default: 50) — minimum pixels for a valid worm region
- `max_age` (default: 35) — frames to keep tracking a missing worm before dropping
- `persistence` (default: 50) — minimum frames tracked to include a worm in output

Partial worms (touching frame edges) are tracked but excluded from final output; they are stored in NPZ with a `partial_` key prefix so the video can still annotate them.

### Frontend (`/frontend/src`)

**`App.jsx`** — Main app. File upload, parameter form, before/after comparison slider, play/pause controls, download links, head/tail correction toggle, re-run with new parameters, job history integration.

**`JobHistory.jsx`** — Polls `GET /jobs`, shows live progress for running/pending jobs, highlights the currently-viewed job, lets user load completed jobs or delete them (delete resets the view if the current job is deleted).

**`HeadTailCorrector.jsx`** — Fetches keypoint data, draws head/tail overlay on a canvas over the video, lets user flip individual worms.

**`MotionCharts.jsx`** — Recharts heatmap + timeline chart for per-worm motion stats (overall, head, mid-body, tail).

**`Settings.jsx`** — Settings panel (⚙ button in header). Lets user change the outputs directory; shows current path and warns that a restart is required.

**`ErrorBoundary.jsx`** — React error boundary that catches render errors and shows a fallback UI instead of a blank screen.

**`api.js`** — Exports `API` base URL: `""` (same-origin) when `VITE_API_URL` is empty (packaged build), `"http://127.0.0.1:8000"` in dev.

### Packaged app (`launcher.py` + `worm_tracker.spec`)

`launcher.py` is the PyInstaller entry point. It binds a socket (keeping it open to avoid port-race), opens the browser after a short delay, then starts uvicorn. On POSIX, the socket fd is passed directly to uvicorn; on Windows, the socket is closed and uvicorn is given host/port instead (fd= is not supported on Windows).

`worm_tracker.spec` bundles: `frontend/dist/` → `frontend_dist/`, `app/` package, `imageio_ffmpeg/` (includes static arm64 ffmpeg binary). FFmpeg is resolved via `imageio_ffmpeg.get_ffmpeg_exe()` at runtime.

## File Locations

- Config: `~/Library/Application Support/WormTracker/config.json` (macOS) — stores `outputs_dir`
- Uploads: `{outputs_dir}/uploads/` — temp, deleted after processing (co-located with outputs)
- Outputs: `{outputs_dir}/{job_id}/{timestamp}_{output_name}/` — default `~/Documents/WormTracker/`
- Job database: `{outputs_dir}/jobs.db` — one DB per outputs folder, lives alongside the outputs

The outputs directory is user-configurable via the Settings panel (⚙ in the UI) or by editing the config file directly. Changes require an app restart.

## Output Formats

- **Video**: `*_tracked.mp4` — H.264, annotated with colored skeleton keypoints and worm IDs
- **Original**: `*_original.*` — copy of input video stored alongside outputs
- **Metadata**: `*_metadata.yaml` — git version, timestamp, parameters, frame count
- **Keypoints**: `*_keypoints.npz` — per-worm arrays `(num_keypoints, frames, 2)` in `[y, x]` order; partial worms stored under `partial_{id}` key
- **Motion Stats**: `*_motion_stats.json` — per-worm motion values (overall, head, mid-body, tail) and aggregate stats
- **CSV**: `*_summary.csv` — one row per worm with mean overall/head/mid/tail motion; `*_timeseries.csv` — columns `frame, worm_id, head_motion, mid_motion, tail_motion` per downsampled window

## No Automated Tests

This project has no test suite. Testing is manual via the web interface. A `validate_csv.py` script exists for spot-checking CSV output against NPZ/JSON ground truth.
