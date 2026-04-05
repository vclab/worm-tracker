from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from uuid import uuid4
from contextlib import contextmanager
from datetime import datetime, timezone
import logging
import shutil
import subprocess
import zipfile
import json
import threading
import sqlite3
import time

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

import numpy as np
import cv2

from app.worm_tracker import run_tracking, compute_motion_stats, export_csv_files, draw_tracks

app = FastAPI(title="Worm Tracker API (Local)")

# Active processing jobs: job_id -> {"cancel_event": Event}
active_jobs: dict[str, dict] = {}
active_jobs_lock = threading.Lock()

# Per-job locks for NPZ read-modify-write (prevents concurrent flip races)
_npz_locks: dict[str, threading.Lock] = {}
_npz_locks_lock = threading.Lock()


def _get_npz_lock(job_id: str) -> threading.Lock:
    with _npz_locks_lock:
        if job_id not in _npz_locks:
            _npz_locks[job_id] = threading.Lock()
        return _npz_locks[job_id]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

APP_DIR = Path(__file__).resolve().parent
UPLOADS = APP_DIR / "uploads"
OUTPUTS = APP_DIR / "outputs"
UPLOADS.mkdir(exist_ok=True, parents=True)
OUTPUTS.mkdir(exist_ok=True, parents=True)

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

DB_PATH = APP_DIR / "jobs.db"


def init_db():
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                job_id              TEXT PRIMARY KEY,
                status              TEXT NOT NULL DEFAULT 'pending',
                created_at          TEXT NOT NULL,
                started_at          TEXT,
                finished_at         TEXT,
                original_filename   TEXT,
                output_name         TEXT,
                output_subfolder    TEXT,
                params_json         TEXT,
                error_msg           TEXT,
                progress            INTEGER DEFAULT 0,
                progress_stage      TEXT,
                video_path          TEXT,
                original_video_path TEXT,
                package_path        TEXT,
                data_csv_path       TEXT,
                motion_stats_path   TEXT
            )
        """)
        for col, typedef in [
            ("original_video_path", "TEXT"),
            ("started_at", "TEXT"),
            ("progress", "INTEGER DEFAULT 0"),
            ("progress_stage", "TEXT"),
            ("regen_pending", "INTEGER NOT NULL DEFAULT 0"),
        ]:
            try:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {typedef}")
            except sqlite3.OperationalError:
                pass
        conn.commit()


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def migrate_existing_outputs():
    """Import any output directories not yet tracked in the DB (best-effort)."""
    if not OUTPUTS.exists():
        return
    with get_db() as conn:
        existing = {r[0] for r in conn.execute("SELECT job_id FROM jobs").fetchall()}
        for job_dir in OUTPUTS.iterdir():
            if not job_dir.is_dir():
                continue
            job_id = job_dir.name
            if job_id in existing:
                continue
            mp4s = [p for p in job_dir.glob("**/*.mp4") if "_tracked" in p.name]
            if not mp4s:
                mp4s = list(job_dir.glob("**/*.mp4"))
            zips = [z for z in job_dir.glob("**/*.zip") if not z.name.endswith("_data.zip")]
            data_zips = [z for z in job_dir.glob("**/*.zip") if z.name.endswith("_data.zip")]
            jsons = list(job_dir.glob("**/*.json"))
            originals = list(job_dir.glob("**/*_original.*"))
            # Derive output_subfolder from the tracked mp4's parent directory name
            output_subfolder = mp4s[0].parent.name if mp4s else None
            created_at = datetime.fromtimestamp(job_dir.stat().st_mtime, tz=timezone.utc).isoformat()
            conn.execute(
                """INSERT OR IGNORE INTO jobs
                   (job_id, status, created_at, output_subfolder, video_path, original_video_path,
                    package_path, data_csv_path, motion_stats_path)
                   VALUES (?, 'done', ?, ?, ?, ?, ?, ?, ?)""",
                (
                    job_id, created_at, output_subfolder,
                    f"/download/{job_id}/{mp4s[0].name}" if mp4s else None,
                    f"/download/{job_id}/{originals[0].name}" if originals else None,
                    f"/download/{job_id}/{zips[0].name}" if zips else None,
                    f"/download/{job_id}/{data_zips[0].name}" if data_zips else None,
                    f"/download/{job_id}/{jsons[0].name}" if jsons else None,
                ),
            )


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Queue worker
# ---------------------------------------------------------------------------

def _do_post_processing(job_id: str, job_dir: Path, original_filename: str, saved_path: Path):
    """Transcode, copy original, build ZIPs, update DB. Returns result dict or raises."""
    mp4s = list(job_dir.glob("**/*_raw.mp4"))
    yaml_files = list(job_dir.glob("**/*.yaml"))
    npz_files = list(job_dir.glob("**/*.npz"))
    json_files = list(job_dir.glob("**/*.json"))
    csv_files = list(job_dir.glob("**/*.csv"))

    if not mp4s:
        raise RuntimeError("No output video produced")

    src_mp4 = mp4s[0]
    output_subfolder = src_mp4.parent.name

    with get_db() as conn:
        conn.execute(
            "UPDATE jobs SET progress=95, progress_stage='finalizing' WHERE job_id=?", (job_id,)
        )

    # Transcode to H.264
    h264_mp4 = src_mp4.parent / f"{output_subfolder}_tracked.mp4"
    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(src_mp4),
                "-vcodec", "libx264",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                "-preset", "veryfast",
                "-crf", "23",
                str(h264_mp4),
            ],
            check=True,
            timeout=300,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
        src_mp4.unlink()
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        if src_mp4.exists():
            src_mp4.rename(h264_mp4)

    if not h264_mp4.exists():
        raise RuntimeError("Tracked video was not produced — FFmpeg and fallback both failed")

    # Copy original video into output subfolder
    original_ext = Path(original_filename).suffix
    original_in_output = src_mp4.parent / f"{output_subfolder}_original{original_ext}"
    try:
        if saved_path.exists():
            shutil.copy2(saved_path, original_in_output)
    except Exception:
        original_in_output = None

    # Delete upload file
    try:
        if saved_path.exists():
            saved_path.unlink()
    except Exception:
        pass

    # Build main ZIP (atomic: write to .tmp then rename)
    package_zip = src_mp4.parent / f"{output_subfolder}.zip"
    tmp_zip = package_zip.with_suffix(".zip.tmp")
    with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        if original_in_output and original_in_output.exists():
            zf.write(original_in_output, arcname=original_in_output.name)
        if h264_mp4.exists():
            zf.write(h264_mp4, arcname=h264_mp4.name)
        if yaml_files:
            zf.write(yaml_files[0], arcname=yaml_files[0].name)
        if npz_files:
            zf.write(npz_files[0], arcname=npz_files[0].name)
        if json_files:
            zf.write(json_files[0], arcname=json_files[0].name)
    tmp_zip.rename(package_zip)

    # Build CSV data ZIP (atomic)
    data_zip = src_mp4.parent / f"{output_subfolder}_data.zip"
    if csv_files:
        tmp_data_zip = data_zip.with_suffix(".zip.tmp")
        with zipfile.ZipFile(tmp_data_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for csv_file in csv_files:
                zf.write(csv_file, arcname=csv_file.name)
        tmp_data_zip.rename(data_zip)

    motion_stats_file = json_files[0] if json_files else None
    original_video_path = (
        f"/download/{job_id}/{original_in_output.name}"
        if original_in_output and original_in_output.exists()
        else None
    )

    result = {
        "video_path": f"/download/{job_id}/{h264_mp4.name}" if h264_mp4.exists() else None,
        "original_video_path": original_video_path,
        "package_path": f"/download/{job_id}/{package_zip.name}" if package_zip.exists() else None,
        "data_csv_path": f"/download/{job_id}/{data_zip.name}" if data_zip.exists() else None,
        "motion_stats_path": f"/download/{job_id}/{motion_stats_file.name}" if motion_stats_file else None,
        "output_subfolder": output_subfolder,
    }

    with get_db() as conn:
        conn.execute(
            """UPDATE jobs SET
                   status='done', finished_at=?, progress=100, progress_stage='done',
                   output_subfolder=?, video_path=?, original_video_path=?,
                   package_path=?, data_csv_path=?, motion_stats_path=?
               WHERE job_id=?""",
            (
                _now_iso(),
                result["output_subfolder"],
                result["video_path"],
                result["original_video_path"],
                result["package_path"],
                result["data_csv_path"],
                result["motion_stats_path"],
                job_id,
            ),
        )

    return result


def process_job(job_id: str):
    """Process a single job from the queue. Runs in the worker thread."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
    if not row:
        return
    job = dict(row)

    original_filename = job["original_filename"] or ""
    saved_path = UPLOADS / f"{job_id}__{original_filename}"
    job_dir = OUTPUTS / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    cancel_event = threading.Event()
    with active_jobs_lock:
        active_jobs[job_id] = {"cancel_event": cancel_event}

    with get_db() as conn:
        conn.execute(
            "UPDATE jobs SET status='processing', started_at=?, progress=0, progress_stage='processing' WHERE job_id=?",
            (_now_iso(), job_id),
        )

    try:
        params = json.loads(job["params_json"] or "{}")
    except (json.JSONDecodeError, TypeError):
        params = {}
    base_name = job["output_name"] or "tracking01"
    error_holder = [None]

    _last_progress_write = [0.0]

    def progress_callback(stage, current, total):
        if cancel_event.is_set():
            return
        now = time.monotonic()
        # Write at most once per second to avoid hammering the DB at high frame rates
        if now - _last_progress_write[0] < 1.0 and current < total:
            return
        _last_progress_write[0] = now
        pct = int(current / total * 100) if total > 0 else 0
        with get_db() as conn:
            conn.execute(
                "UPDATE jobs SET progress=?, progress_stage=? WHERE job_id=?",
                (pct, stage, job_id),
            )

    try:
        run_tracking(
            video_path=str(saved_path),
            output_dir=str(job_dir),
            keypoints_per_worm=params.get("keypoints_per_worm", 15),
            area_threshold=params.get("area_threshold", 50),
            max_age=params.get("max_age", 35),
            show_video=False,
            output_name=base_name,
            persistence=params.get("persistence", 50),
            progress_callback=progress_callback,
            cancel_check=lambda: cancel_event.is_set(),
        )
    except Exception as e:
        error_holder[0] = e

    with active_jobs_lock:
        active_jobs.pop(job_id, None)

    # Cancelled
    if cancel_event.is_set():
        try:
            if saved_path.exists():
                saved_path.unlink()
        except Exception:
            pass
        with get_db() as conn:
            conn.execute(
                "UPDATE jobs SET status='cancelled', finished_at=? WHERE job_id=? AND status='processing'",
                (_now_iso(), job_id),
            )
        return

    # Error from tracker
    if error_holder[0]:
        try:
            if saved_path.exists():
                saved_path.unlink()
        except Exception:
            pass
        with get_db() as conn:
            conn.execute(
                "UPDATE jobs SET status='error', finished_at=?, error_msg=? WHERE job_id=?",
                (_now_iso(), str(error_holder[0]), job_id),
            )
        return

    # Post-processing
    try:
        _do_post_processing(job_id, job_dir, original_filename, saved_path)
    except Exception as e:
        try:
            if saved_path.exists():
                saved_path.unlink()
        except Exception:
            pass
        with get_db() as conn:
            conn.execute(
                "UPDATE jobs SET status='error', finished_at=?, error_msg=? WHERE job_id=?",
                (_now_iso(), str(e), job_id),
            )


def queue_worker():
    """Daemon thread: picks up pending jobs one at a time."""
    while True:
        try:
            with get_db() as conn:
                row = conn.execute(
                    "SELECT job_id FROM jobs WHERE status='pending' ORDER BY created_at LIMIT 1"
                ).fetchone()
            if row:
                process_job(row["job_id"])
            else:
                time.sleep(2)
        except Exception as exc:
            logger.error("Queue worker error: %s", exc, exc_info=True)
            time.sleep(2)


init_db()
migrate_existing_outputs()

_worker = threading.Thread(target=queue_worker, daemon=True)
_worker.start()

# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


@app.get("/")
def root():
    return {"ok": True, "message": "Worm Tracker API running"}


@app.get("/jobs")
def list_jobs():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


@app.delete("/jobs/{job_id}")
def delete_job(job_id: str):
    """Delete a job record, its output files, and any leftover upload file."""
    # Signal cancellation if the job is actively processing
    with active_jobs_lock:
        job_info = active_jobs.get(job_id)
        if job_info:
            job_info["cancel_event"].set()

    with get_db() as conn:
        row = conn.execute(
            "SELECT original_filename FROM jobs WHERE job_id=?", (job_id,)
        ).fetchone()

    # Clean up upload file if it still exists (e.g. error mid-processing)
    if row and row["original_filename"]:
        saved_path = UPLOADS / f"{job_id}__{row['original_filename']}"
        try:
            if saved_path.exists():
                saved_path.unlink()
        except Exception:
            pass

    job_dir = OUTPUTS / job_id
    try:
        if job_dir.exists():
            shutil.rmtree(job_dir)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    with get_db() as conn:
        conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
    return {"ok": True}


@app.post("/upload")
async def upload_video(
    file: UploadFile = File(...),
    keypoints_per_worm: int = Form(15),
    area_threshold: int = Form(50),
    max_age: int = Form(35),
    persistence: int = Form(50),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    job_id = str(uuid4())
    saved_path = UPLOADS / f"{job_id}__{file.filename}"
    with saved_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    base_name = Path(file.filename).stem  # e.g. "worm_run1" from "worm_run1.mov"
    params_json = json.dumps({
        "keypoints_per_worm": keypoints_per_worm,
        "area_threshold": area_threshold,
        "max_age": max_age,
        "persistence": persistence,
    })

    with get_db() as conn:
        conn.execute(
            """INSERT INTO jobs
               (job_id, status, created_at, original_filename, output_name, params_json)
               VALUES (?, 'pending', ?, ?, ?, ?)""",
            (job_id, _now_iso(), file.filename, base_name, params_json),
        )

    return {"job_id": job_id}


@app.get("/download/{job_id}/{filename}")
def download_file(job_id: str, filename: str):
    safe_filename = Path(filename).name
    if not safe_filename or safe_filename != filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    job_dir = OUTPUTS / job_id
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="Job not found")

    matches = list(job_dir.glob(f"**/{safe_filename}"))
    if not matches:
        raise HTTPException(status_code=404, detail="File not found")

    matched_path = matches[0].resolve()
    if not str(matched_path).startswith(str(job_dir.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")

    return FileResponse(matched_path, filename=safe_filename)


def regenerate_tracked_video(subdir: Path):
    """Re-render the tracked video from stored keypoints without re-running the tracker."""
    subfolder = subdir.name

    original_files = list(subdir.glob("*_original.*"))
    if not original_files:
        raise RuntimeError("Original video not found in output folder")
    original_path = original_files[0]

    npz_files = list(subdir.glob("*_keypoints.npz"))
    if not npz_files:
        raise RuntimeError("Keypoints file not found")

    with np.load(npz_files[0]) as npz:
        all_keys = list(npz.keys())
        retained_ids = [k for k in all_keys if not k.startswith("partial_")]
        partial_ids = [k[len("partial_"):] for k in all_keys if k.startswith("partial_")]
        if not all_keys:
            return
        keypoint_data = {wid: npz[wid].copy() for wid in retained_ids}
        partial_data = {wid: npz[f"partial_{wid}"].copy() for wid in partial_ids}
    all_data = {**keypoint_data, **partial_data}
    num_frames = max(int(arr.shape[1]) for arr in all_data.values())
    num_keypoints = int(next(iter(all_data.values())).shape[0])

    cap = cv2.VideoCapture(str(original_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open original video: {original_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 60
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    raw_mp4 = subdir / f"{subfolder}_raw.mp4"
    out = cv2.VideoWriter(str(raw_mp4), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))

    try:
        frame_idx = 0
        while frame_idx < num_frames:
            ret, frame = cap.read()
            if not ret:
                break
            # Gather all worms' keypoints at this frame
            frame_kps, frame_ids, frame_partial = [], [], []
            for wid in retained_ids:
                arr = keypoint_data[wid]  # (num_keypoints, num_frames, 2)
                if frame_idx < arr.shape[1]:
                    frame_kps.append(arr[:, frame_idx, :])  # (num_keypoints, 2) [y, x]
                    frame_ids.append(wid)
                    frame_partial.append(False)
            for wid in partial_ids:
                arr = partial_data[wid]
                if frame_idx < arr.shape[1]:
                    frame_kps.append(arr[:, frame_idx, :])
                    frame_ids.append(wid)
                    frame_partial.append(True)
            annotated = draw_tracks(frame.copy(), frame_kps, frame_ids, num_keypoints, frame_partial)
            out.write(annotated)
            frame_idx += 1
    finally:
        cap.release()
        out.release()

    # Transcode to H.264, replacing existing file
    h264_mp4 = subdir / f"{subfolder}_tracked.mp4"
    if h264_mp4.exists():
        h264_mp4.unlink()

    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(raw_mp4),
                "-vcodec", "libx264",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                "-preset", "veryfast",
                "-crf", "23",
                str(h264_mp4),
            ],
            check=True,
            timeout=300,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
        raw_mp4.unlink()
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        if raw_mp4.exists():
            raw_mp4.rename(h264_mp4)


def _rebuild_zips(subdir: Path):
    """Rebuild package and data ZIPs from current contents of subdir (atomic)."""
    subfolder = subdir.name
    h264_mp4 = next(subdir.glob("*_tracked.mp4"), None)
    original = next(subdir.glob("*_original.*"), None)
    yaml_file = next(subdir.glob("*.yaml"), None)
    npz_file = next(subdir.glob("*_keypoints.npz"), None)
    json_file = next(subdir.glob("*_motion_stats.json"), None)
    csv_files = list(subdir.glob("*.csv"))

    package_zip = subdir / f"{subfolder}.zip"
    tmp = subdir / f"{subfolder}.zip.tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in [original, h264_mp4, yaml_file, npz_file, json_file]:
            if f and f.exists():
                zf.write(f, arcname=f.name)
    tmp.rename(package_zip)

    if csv_files:
        data_zip = subdir / f"{subfolder}_data.zip"
        tmp_data = subdir / f"{subfolder}_data.zip.tmp"
        with zipfile.ZipFile(tmp_data, "w", zipfile.ZIP_DEFLATED) as zf:
            for csv_file in csv_files:
                zf.write(csv_file, arcname=csv_file.name)
        tmp_data.rename(data_zip)


@app.get("/jobs/{job_id}/keypoints")
def get_keypoints(job_id: str):
    """Return head and tail positions per worm for all frames."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT output_subfolder FROM jobs WHERE job_id=?", (job_id,)
        ).fetchone()
    if not row or not row["output_subfolder"]:
        raise HTTPException(status_code=404, detail="Job not found or not completed")

    subdir = OUTPUTS / job_id / row["output_subfolder"]
    npz_files = list(subdir.glob("*_keypoints.npz"))
    if not npz_files:
        raise HTTPException(status_code=404, detail="Keypoints file not found")

    with np.load(npz_files[0]) as npz:
        # Only expose retained worm IDs — partial worms (key prefix "partial_") are not flippable
        worm_ids = [k for k in npz.keys() if not k.startswith("partial_")]
        if not worm_ids:
            return {"worm_ids": [], "num_frames": 0, "head_positions": {}, "tail_positions": {}}
        num_frames = max(int(npz[wid].shape[1]) for wid in worm_ids)
        head_positions = {wid: npz[wid][0].tolist() for wid in worm_ids}
        tail_positions = {wid: npz[wid][-1].tolist() for wid in worm_ids}

    return {
        "worm_ids": worm_ids,
        "num_frames": num_frames,
        "head_positions": head_positions,
        "tail_positions": tail_positions,
    }


def _regen_and_rebuild(subdir: Path, job_id: str):
    """Background task: regenerate tracked video and rebuild ZIPs, then clear regen_pending."""
    try:
        regenerate_tracked_video(subdir)
    except Exception as exc:
        logger.error("Video regeneration failed for %s: %s", subdir, exc)
    try:
        _rebuild_zips(subdir)
    except Exception as exc:
        logger.error("ZIP rebuild failed for %s: %s", subdir, exc)
    try:
        with get_db() as conn:
            conn.execute("UPDATE jobs SET regen_pending=0 WHERE job_id=?", (job_id,))
    except Exception as exc:
        logger.error("Failed to clear regen_pending for %s: %s", job_id, exc)


@app.post("/jobs/{job_id}/flip/{worm_id}")
def flip_worm(job_id: str, worm_id: str, background_tasks: BackgroundTasks):
    """Flip head/tail for a worm (reverse keypoint axis 0) and recompute stats."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT output_subfolder FROM jobs WHERE job_id=?", (job_id,)
        ).fetchone()
    if not row or not row["output_subfolder"]:
        raise HTTPException(status_code=404, detail="Job not found or not completed")

    subdir = OUTPUTS / job_id / row["output_subfolder"]
    npz_files = list(subdir.glob("*_keypoints.npz"))
    if not npz_files:
        raise HTTPException(status_code=404, detail="Keypoints file not found")

    npz_path = npz_files[0]
    npz_lock = _get_npz_lock(job_id)
    with npz_lock:
        with np.load(npz_path) as npz:
            data = {k: npz[k].copy() for k in npz.keys()}

        if worm_id not in data:
            raise HTTPException(status_code=404, detail=f"Worm {worm_id} not found in keypoints")

        # Flip keypoint axis 0 (head ↔ tail)
        data[worm_id] = data[worm_id][::-1, :, :]

        # Save atomically — validate new file before overwriting original
        tmp_npz = npz_path.with_suffix(".tmp.npz")
        np.savez_compressed(tmp_npz, **data)
        try:
            with np.load(tmp_npz) as check:
                if set(check.keys()) != set(data.keys()):
                    raise RuntimeError("NPZ key mismatch after save")
        except Exception as exc:
            tmp_npz.unlink(missing_ok=True)
            raise HTTPException(status_code=500, detail=f"NPZ validation failed: {exc}")
        tmp_npz.rename(npz_path)

    # Recompute motion stats — convert arrays to list-of-lists format expected by compute_motion_stats
    # NPZ arrays: (num_keypoints, num_frames, 2); compute_motion_stats expects {wid: [[y,x], ...] per keypoint}
    # Exclude partial worm keys (prefix "partial_") — they are not included in motion analysis.
    tracks_for_stats = {
        wid: [arr[i].tolist() for i in range(arr.shape[0])]
        for wid, arr in data.items()
        if not wid.startswith("partial_")
    }
    motion_stats = compute_motion_stats(tracks_for_stats)

    # Save updated motion stats JSON
    json_files = list(subdir.glob("*_motion_stats.json"))
    if motion_stats and json_files:
        with open(json_files[0], "w") as f:
            json.dump(motion_stats, f, indent=2)

    # Regenerate CSVs
    for csv_file in subdir.glob("*.csv"):
        csv_file.unlink()
    if motion_stats:
        export_csv_files(motion_stats, str(subdir), row["output_subfolder"])

    # Mark job as regenerating, then schedule video + ZIP rebuild after response is sent
    with get_db() as conn:
        conn.execute("UPDATE jobs SET regen_pending=1 WHERE job_id=?", (job_id,))
    background_tasks.add_task(_regen_and_rebuild, subdir, job_id)

    return {"ok": True, "motion_stats": motion_stats}


@app.post("/cancel/{job_id}")
def cancel_job(job_id: str):
    """Cancel a pending or processing job."""
    # Signal processing thread if active
    with active_jobs_lock:
        job_info = active_jobs.get(job_id)
        if job_info:
            job_info["cancel_event"].set()

    # Mark DB (only if not already terminal)
    with get_db() as conn:
        conn.execute(
            "UPDATE jobs SET status='cancelled', finished_at=? WHERE job_id=? AND status IN ('pending', 'processing')",
            (_now_iso(), job_id),
        )
        row = conn.execute(
            "SELECT original_filename FROM jobs WHERE job_id=?", (job_id,)
        ).fetchone()

    # Clean up files for pending jobs (processing jobs clean up themselves on cancel detection)
    if not job_info and row:
        saved_path = UPLOADS / f"{job_id}__{row['original_filename']}"
        job_dir = OUTPUTS / job_id
        try:
            if saved_path.exists():
                saved_path.unlink()
        except Exception:
            pass
        try:
            if job_dir.exists():
                shutil.rmtree(job_dir)
        except Exception:
            pass

    return {"ok": True, "message": "Job cancelled"}
