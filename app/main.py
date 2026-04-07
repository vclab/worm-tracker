from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone
import logging
import pydantic
import shutil
import subprocess
import sys
import traceback
import zipfile
import json
import threading
import sqlite3
import os
import re
import time

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

import numpy as np
import cv2

from app.worm_tracker import run_tracking, compute_motion_stats, export_csv_files, draw_tracks
from app.config import load_config, save_config, get_config_dir

@asynccontextmanager
async def _lifespan(application: FastAPI):
    # Startup is handled at module level (lock + DB init + worker thread).
    yield
    # Shutdown: explicitly release the outputs-directory lock so the lock file
    # is not left stale on platforms where the kernel might not release it
    # immediately (e.g. NFS mounts).
    global _lock_fh
    if _lock_fh is not None:
        try:
            _lock_fh.close()
        except Exception:
            pass
        _lock_fh = None


app = FastAPI(title="Worm Tracker API (Local)", lifespan=_lifespan)

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
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173",
                   "http://127.0.0.1:8000", "http://localhost:8000"],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

APP_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Paths — outputs and DB are user-configurable; uploads live alongside outputs
# ---------------------------------------------------------------------------

_config = load_config()
OUTPUTS = Path(_config["outputs_dir"])
UPLOADS = OUTPUTS / "uploads"   # temp files, co-located with outputs so they follow the same drive
try:
    OUTPUTS.mkdir(exist_ok=True, parents=True)
except Exception as _exc:
    logger.warning("Could not create outputs directory %s: %s", OUTPUTS, _exc)
try:
    UPLOADS.mkdir(exist_ok=True, parents=True)
except Exception as _exc:
    logger.warning("Could not create uploads directory %s: %s", UPLOADS, _exc)

# Set to True when the user saves new settings; blocks new uploads until restart.
_restart_pending = False

# ---------------------------------------------------------------------------
# FFmpeg — prefer bundled static binary (imageio_ffmpeg), fall back to PATH
# ---------------------------------------------------------------------------

def _resolve_ffmpeg() -> str:
    """Return path to the ffmpeg executable to use."""
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if Path(exe).is_file() and os.access(exe, os.X_OK):
            logger.info("Using bundled ffmpeg: %s", exe)
            return exe
        logger.warning("imageio_ffmpeg returned non-executable path: %s — trying system PATH", exe)
    except Exception:
        pass
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        logger.info("Using system ffmpeg from PATH: %s", system_ffmpeg)
        return system_ffmpeg
    logger.warning("No ffmpeg executable found — transcoding will fail")
    return "ffmpeg"

FFMPEG_BIN = _resolve_ffmpeg()

# ---------------------------------------------------------------------------
# Outputs-directory lock — one process per outputs folder
# ---------------------------------------------------------------------------
# We hold an exclusive flock on wormtracker.lock for the lifetime of the
# process.  The kernel releases the lock automatically on process death
# (even SIGKILL), so orphaned instances can never block a fresh start.

_LOCK_PATH = OUTPUTS / "wormtracker.lock"
_lock_fh = None   # kept open to hold the lock


def _acquire_outputs_lock() -> None:
    """Acquire an exclusive advisory lock on the outputs directory.

    Raises RuntimeError if another WormTracker process already owns it.
    No-op on Windows (fcntl unavailable; SQLite WAL still prevents DB
    corruption, just without single-instance enforcement).
    """
    global _lock_fh
    if sys.platform == "win32":
        return
    import fcntl
    fh = open(_LOCK_PATH, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        raise RuntimeError(
            f"Another WormTracker process is already using {OUTPUTS}. "
            "Close the other instance first."
        )
    fh.write(str(os.getpid()))
    fh.flush()
    _lock_fh = fh   # keep fd open — lock released when process exits


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

# One DB per outputs folder — makes each folder self-contained and portable.
DB_PATH = OUTPUTS / "jobs.db"


def init_db():
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        # WAL: readers don't block writers; safe for concurrent web requests.
        # NORMAL synchronous: skips fsync except at checkpoints — fast for local use.
        # WAL guarantees atomicity even on crash; at worst the last un-checkpointed
        # transaction is lost, which is acceptable for a local research tool.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                job_id              TEXT PRIMARY KEY,
                status              TEXT NOT NULL DEFAULT 'pending',
                created_at          TEXT NOT NULL,
                created_at_unix     INTEGER,
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
                motion_stats_path   TEXT,
                regen_pending       INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_created_at_unix ON jobs (created_at_unix DESC)"
        )
        # Migration: add columns introduced after initial schema (for existing DBs).
        # Columns already in CREATE TABLE above are intentionally absent from this list.
        for stmt in [
            "ALTER TABLE jobs ADD COLUMN regen_pending INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE jobs ADD COLUMN created_at_unix INTEGER",
        ]:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass  # column already exists
        # Recover jobs stuck in 'processing' from a previous crashed server — they
        # will never be re-picked by the worker (which only selects 'pending').
        conn.execute(
            "UPDATE jobs SET status='error', finished_at=?, error_msg=? "
            "WHERE status='processing'",
            (_now_iso(), "Server restarted while job was processing"),
        )
        conn.commit()


@contextmanager
def get_db(readonly: bool = False):
    """Yield a SQLite connection.  Commits on exit unless *readonly* is True."""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        if not readonly:
            conn.commit()
    finally:
        conn.close()


def migrate_existing_outputs():
    """Import any output directories not yet tracked in the DB (best-effort)."""
    if not OUTPUTS.exists():
        return
    with get_db(readonly=True) as conn:
        existing = {r[0] for r in conn.execute("SELECT job_id FROM jobs").fetchall()}
        # Directories that live inside OUTPUTS but are not job output folders.
        _NON_JOB_DIRS = {"uploads", "wormtracker.lock"}
        for job_dir in OUTPUTS.iterdir():
            if not job_dir.is_dir():
                continue
            if job_dir.name in _NON_JOB_DIRS:
                continue
            job_id = job_dir.name
            if job_id in existing:
                continue
            mp4s = [p for p in job_dir.glob("**/*.mp4") if "_tracked" in p.name]
            if not mp4s:
                # No tracked video — skip incomplete/failed output dirs rather than
                # accidentally picking up a raw or original MP4 as the tracked video.
                continue
            zips = [z for z in job_dir.glob("**/*.zip") if not z.name.endswith("_data.zip")]
            data_zips = [z for z in job_dir.glob("**/*.zip") if z.name.endswith("_data.zip")]
            jsons = list(job_dir.glob("**/*.json"))
            originals = list(job_dir.glob("**/*_original.*"))
            # Derive output_subfolder from the tracked mp4's parent directory name
            output_subfolder = mp4s[0].parent.name if mp4s else None
            _st = job_dir.stat()
            # Prefer birthtime (macOS/BSD) as creation time; fall back to ctime
            # (inode change time on Linux, creation time on Windows).  Avoid
            # mtime which changes whenever any file inside the directory is written.
            _ts = getattr(_st, "st_birthtime", None) or _st.st_ctime
            created_at = datetime.fromtimestamp(_ts, tz=timezone.utc).isoformat()
            created_at_unix = int(_ts)
            conn.execute(
                """INSERT OR IGNORE INTO jobs
                   (job_id, status, created_at, created_at_unix, output_subfolder, video_path, original_video_path,
                    package_path, data_csv_path, motion_stats_path)
                   VALUES (?, 'done', ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    job_id, created_at, created_at_unix, output_subfolder,
                    f"/download/{job_id}/{mp4s[0].name}" if mp4s else None,
                    f"/download/{job_id}/{originals[0].name}" if originals else None,
                    f"/download/{job_id}/{zips[0].name}" if zips else None,
                    f"/download/{job_id}/{data_zips[0].name}" if data_zips else None,
                    f"/download/{job_id}/{jsons[0].name}" if jsons else None,
                ),
            )


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _now_unix() -> int:
    """Current UTC time as integer Unix epoch seconds — used for reliable DB ordering."""
    return int(datetime.now(tz=timezone.utc).timestamp())


# ---------------------------------------------------------------------------
# Queue worker
# ---------------------------------------------------------------------------

def _transcode_to_h264(src: Path, dst: Path, job_id: str = ""):
    """Transcode *src* to H.264 at *dst*, deleting *src* on success.

    Falls back to renaming *src* → *dst* if FFmpeg is unavailable or fails,
    logging the error either way.
    """
    tag = f" for job {job_id}" if job_id else ""
    try:
        result = subprocess.run(
            [
                FFMPEG_BIN, "-y",
                "-i", str(src),
                "-vcodec", "libx264",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                "-preset", "veryfast",
                "-crf", "23",
                str(dst),
            ],
            check=True,
            timeout=300,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        src.unlink()
    except FileNotFoundError:
        logger.error("FFmpeg binary not found (%s)%s — falling back to raw video", FFMPEG_BIN, tag)
        if src.exists():
            src.rename(dst)
    except subprocess.TimeoutExpired:
        logger.error("FFmpeg transcoding timed out%s — falling back to raw video", tag)
        if src.exists():
            src.rename(dst)
    except subprocess.CalledProcessError as exc:
        stderr_out = exc.stderr.decode(errors="replace").strip() if exc.stderr else ""
        logger.error(
            "FFmpeg transcoding failed (rc=%d)%s — falling back to raw video\n%s",
            exc.returncode, tag, stderr_out,
        )
        if src.exists():
            src.rename(dst)


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
    _transcode_to_h264(src_mp4, h264_mp4, job_id)

    if not h264_mp4.exists():
        raise RuntimeError("Tracked video was not produced — FFmpeg and fallback both failed")

    # Copy original video into output subfolder
    original_ext = Path(original_filename).suffix
    original_in_output = src_mp4.parent / f"{output_subfolder}_original{original_ext}"
    try:
        if saved_path.exists():
            shutil.copy2(saved_path, original_in_output)
    except Exception as exc:
        logger.debug("Could not copy original video to output folder: %s", exc)
        original_in_output = None

    # Delete upload file
    try:
        if saved_path.exists():
            saved_path.unlink()
    except Exception as exc:
        logger.debug("Could not delete upload file %s: %s", saved_path, exc)

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
    tmp_zip.replace(package_zip)

    # Build CSV data ZIP (atomic)
    data_zip = src_mp4.parent / f"{output_subfolder}_data.zip"
    if csv_files:
        tmp_data_zip = data_zip.with_suffix(".zip.tmp")
        with zipfile.ZipFile(tmp_data_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for csv_file in csv_files:
                zf.write(csv_file, arcname=csv_file.name)
        tmp_data_zip.replace(data_zip)

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
    with get_db(readonly=True) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
    if not row:
        return
    job = dict(row)

    original_filename = job["original_filename"] or ""
    saved_path = UPLOADS / f"{job_id}__{original_filename}"
    job_dir = OUTPUTS / job_id

    logger.info("Starting job %s | file: %s | upload exists: %s", job_id, saved_path, saved_path.exists())
    job_dir.mkdir(parents=True, exist_ok=True)

    cancel_event = threading.Event()
    done_event   = threading.Event()
    with active_jobs_lock:
        active_jobs[job_id] = {"cancel_event": cancel_event, "done_event": done_event}

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

    _last_progress_write = 0.0

    def progress_callback(stage, current, total):
        nonlocal _last_progress_write
        if cancel_event.is_set():
            return
        now = time.monotonic()
        # Write at most once per second to avoid hammering the DB at high frame rates
        if now - _last_progress_write < 1.0 and current < total:
            return
        _last_progress_write = now
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
    done_event.set()  # unblock any delete_job waiting for us to finish

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
        tb = "".join(traceback.format_exception(type(error_holder[0]), error_holder[0], error_holder[0].__traceback__))
        print(f"[WORMTRACKER] Job {job_id} FAILED during tracking:\n{tb}", flush=True)
        logger.error("Job %s failed during tracking:\n%s", job_id, tb)
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
        print(f"[WORMTRACKER] Job {job_id} FAILED during post-processing:\n{traceback.format_exc()}", flush=True)
        logger.error("Job %s failed during post-processing:\n%s", job_id, traceback.format_exc())
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
    backoff = 2
    while True:
        try:
            with get_db(readonly=True) as conn:
                row = conn.execute(
                    "SELECT job_id FROM jobs WHERE status='pending' ORDER BY created_at_unix LIMIT 1"
                ).fetchone()
            if row:
                backoff = 2  # reset on successful DB access
                process_job(row["job_id"])
            else:
                time.sleep(2)
        except Exception as exc:
            logger.error("Queue worker error: %s", exc, exc_info=True)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)


try:
    _acquire_outputs_lock()
    init_db()
    migrate_existing_outputs()
except Exception as _db_exc:
    logger.critical(
        "Failed to initialize database at %s: %s — queue worker will not start",
        DB_PATH, _db_exc,
    )
else:
    _worker = threading.Thread(target=queue_worker, daemon=True)
    _worker.start()

# ---------------------------------------------------------------------------
# Browser-presence watchdog (packaged app only)
# Shuts the server down when the browser tab has been closed for > 20 s.
# A 30 s startup grace period prevents shutdown before the page has loaded.
# ---------------------------------------------------------------------------

_HEARTBEAT_TIMEOUT   = 20   # seconds of silence → shutdown
_HEARTBEAT_GRACE     = 60   # seconds after startup before watchdog activates
_last_heartbeat      = time.monotonic()
_watchdog_active     = False   # set to True only when running as a bundle


def _heartbeat_watchdog() -> None:
    time.sleep(_HEARTBEAT_GRACE)
    while True:
        time.sleep(5)
        if time.monotonic() - _last_heartbeat > _HEARTBEAT_TIMEOUT:
            # Defer shutdown while a job is actively processing (in-memory check).
            with active_jobs_lock:
                if active_jobs:
                    continue
            # Also query DB in case active_jobs is empty but a job is still
            # marked processing (e.g. after an edge-case restart).
            try:
                with get_db(readonly=True) as conn:
                    processing = conn.execute(
                        "SELECT 1 FROM jobs WHERE status='processing' LIMIT 1"
                    ).fetchone()
                if processing:
                    continue
            except Exception:
                pass  # if DB is unreachable, proceed with shutdown
            logger.info("No browser heartbeat for %ds — shutting down.", _HEARTBEAT_TIMEOUT)
            import signal
            os.kill(os.getpid(), signal.SIGTERM)
            return


if getattr(sys, "frozen", False):
    _watchdog_active = True
    _wdog = threading.Thread(target=_heartbeat_watchdog, daemon=True)
    _wdog.start()

# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


@app.get("/api/health")
def root():
    return {"ok": True, "message": "Worm Tracker API running"}


@app.get("/api/settings")
def get_settings():
    cfg = load_config()
    return {
        "outputs_dir": cfg["outputs_dir"],
        "config_dir": str(get_config_dir()),
        "restart_pending": _restart_pending,
    }


class _SettingsIn(pydantic.BaseModel):
    outputs_dir: str


@app.post("/api/settings")
def update_settings(body: _SettingsIn):
    global _restart_pending
    new_path = Path(body.outputs_dir).expanduser().resolve()
    # Validate that the path is writable before saving
    try:
        new_path.mkdir(parents=True, exist_ok=True)
        _test = new_path / ".write_test"
        _test.touch()
        _test.unlink()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Outputs folder is not writable: {exc}")
    cfg = load_config()
    cfg["outputs_dir"] = str(new_path)
    save_config(cfg)
    _restart_pending = True
    return {"ok": True, "outputs_dir": str(new_path), "restart_required": True}


@app.post("/api/heartbeat")
def heartbeat():
    global _last_heartbeat
    _last_heartbeat = time.monotonic()
    return {"ok": True}


@app.get("/jobs")
def list_jobs(limit: int = 100, offset: int = 0):
    limit = min(max(1, limit), 1000)  # cap: never return more than 1000 rows
    offset = max(0, offset)
    with get_db(readonly=True) as conn:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY created_at_unix DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    return [dict(r) for r in rows]


@app.delete("/jobs/{job_id}")
def delete_job(job_id: str):
    """Delete a job record, its output files, and any leftover upload file."""
    # Signal cancellation if the job is actively processing, then wait for
    # the worker to finish before touching the filesystem (avoids deleting
    # files that the worker is still writing).
    with active_jobs_lock:
        job_info = active_jobs.get(job_id)
    if job_info:
        job_info["cancel_event"].set()
        job_info["done_event"].wait(timeout=30)  # up to 30 s for cooperative cancel

    with get_db(readonly=True) as conn:
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

    # Delete DB record first — if file deletion fails, the record is already
    # gone so the UI won't show a broken entry pointing at missing files.
    with get_db() as conn:
        conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))

    job_dir = OUTPUTS / job_id
    try:
        if job_dir.exists():
            shutil.rmtree(job_dir)
    except Exception as e:
        logger.warning("Could not delete output directory for job %s: %s", job_id, e)

    # Release the per-job NPZ lock so it doesn't leak memory indefinitely
    with _npz_locks_lock:
        _npz_locks.pop(job_id, None)

    return {"ok": True}


_ALLOWED_VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".wmv", ".flv", ".mpeg", ".mpg"
}


@app.post("/upload")
async def upload_video(
    file: UploadFile = File(...),
    keypoints_per_worm: int = Form(15),
    area_threshold: int = Form(50),
    max_age: int = Form(35),
    persistence: int = Form(50),
):
    if _restart_pending:
        raise HTTPException(
            status_code=503,
            detail="Settings changed — restart the app to apply before submitting new jobs",
        )
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")
    # Validate tracking parameter ranges to prevent extreme values
    if not (1 <= keypoints_per_worm <= 200):
        raise HTTPException(status_code=400, detail="keypoints_per_worm must be 1–200")
    if not (0 <= area_threshold <= 100_000):
        raise HTTPException(status_code=400, detail="area_threshold must be 0–100000")
    if not (0 <= max_age <= 10_000):
        raise HTTPException(status_code=400, detail="max_age must be 0–10000")
    if not (0 <= persistence <= 10_000):
        raise HTTPException(status_code=400, detail="persistence must be 0–10000")
    # Reject filenames that contain path separators (e.g. "../secret")
    safe_name = Path(file.filename).name
    if not safe_name or safe_name != file.filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    ext = Path(file.filename).suffix.lower()
    if ext not in _ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext or '(none)'}")

    _MAX_UPLOAD_BYTES = 10 * 1024 ** 3  # 10 GB hard cap
    job_id = str(uuid4())
    saved_path = UPLOADS / f"{job_id}__{file.filename}"
    try:
        total = 0
        with saved_path.open("wb") as buffer:
            chunk_size = 1024 * 1024  # 1 MB chunks
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds maximum allowed size of {_MAX_UPLOAD_BYTES // 1024**3} GB",
                    )
                buffer.write(chunk)
    except HTTPException:
        saved_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        saved_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Failed to save upload: {exc}")

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
               (job_id, status, created_at, created_at_unix, original_filename, output_name, params_json)
               VALUES (?, 'pending', ?, ?, ?, ?, ?)""",
            (job_id, _now_iso(), _now_unix(), file.filename, base_name, params_json),
        )

    return {"job_id": job_id}


_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


@app.get("/download/{job_id}/{filename}")
def download_file(job_id: str, filename: str):
    if not _UUID_RE.match(job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID")
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
    try:
        matched_path.relative_to(job_dir.resolve())
    except ValueError:
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

    _REGEN_TIMEOUT = 3600  # 1 hour max for video regeneration
    _regen_start = time.monotonic()

    try:
        frame_idx = 0
        while frame_idx < num_frames:
            if time.monotonic() - _regen_start > _REGEN_TIMEOUT:
                raise RuntimeError(f"Video regeneration timed out after {_REGEN_TIMEOUT}s")
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

    # Validate VideoWriter produced a non-empty file before transcoding
    if not raw_mp4.exists() or raw_mp4.stat().st_size == 0:
        raise RuntimeError("VideoWriter produced an empty or missing output file")

    # Transcode to H.264, replacing existing file
    h264_mp4 = subdir / f"{subfolder}_tracked.mp4"
    if h264_mp4.exists():
        h264_mp4.unlink()

    _transcode_to_h264(raw_mp4, h264_mp4)


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
    tmp.replace(package_zip)

    if csv_files:
        data_zip = subdir / f"{subfolder}_data.zip"
        tmp_data = subdir / f"{subfolder}_data.zip.tmp"
        with zipfile.ZipFile(tmp_data, "w", zipfile.ZIP_DEFLATED) as zf:
            for csv_file in csv_files:
                zf.write(csv_file, arcname=csv_file.name)
        tmp_data.replace(data_zip)


@app.get("/jobs/{job_id}/keypoints")
def get_keypoints(job_id: str):
    """Return head and tail positions per worm for all frames."""
    with get_db(readonly=True) as conn:
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


def _regen_and_rebuild(subdir: Path, job_id: str, motion_stats: dict | None = None):
    """Background task: regenerate CSVs + tracked video + ZIPs, then clear regen_pending."""
    regen_ok = True

    # Regenerate CSVs atomically (delete old, write new) before touching the video.
    if motion_stats:
        try:
            for csv_file in subdir.glob("*.csv"):
                csv_file.unlink()
            export_csv_files(motion_stats, str(subdir), subdir.name)
        except Exception as exc:
            logger.error("CSV regeneration failed for %s: %s", subdir, exc)
            regen_ok = False

    if regen_ok:
        try:
            regenerate_tracked_video(subdir)
        except Exception as exc:
            logger.error("Video regeneration failed for %s: %s", subdir, exc)
            regen_ok = False

    if regen_ok:
        try:
            _rebuild_zips(subdir)
        except Exception as exc:
            logger.error("ZIP rebuild failed for %s: %s", subdir, exc)
            regen_ok = False

    try:
        with get_db() as conn:
            if regen_ok:
                # Refresh download paths — file names are stable but we update anyway
                # to keep the DB in sync if anything changed during regeneration.
                h264  = next(subdir.glob("*_tracked.mp4"), None)
                pkg   = next(subdir.glob("*.zip"), None)
                data  = next(subdir.glob("*_data.zip"), None)
                conn.execute(
                    """UPDATE jobs SET regen_pending=0,
                           video_path=?, package_path=?, data_csv_path=?
                       WHERE job_id=?""",
                    (
                        f"/download/{job_id}/{h264.name}"  if h264  else None,
                        f"/download/{job_id}/{pkg.name}"   if pkg   else None,
                        f"/download/{job_id}/{data.name}"  if data  else None,
                        job_id,
                    ),
                )
            else:
                conn.execute(
                    "UPDATE jobs SET regen_pending=0, error_msg=? WHERE job_id=?",
                    ("Regeneration failed — see server logs for details", job_id),
                )
    except Exception as exc:
        logger.error("Failed to update regen status for %s: %s", job_id, exc)


@app.post("/jobs/{job_id}/flip/{worm_id}")
def flip_worm(job_id: str, worm_id: str, background_tasks: BackgroundTasks):
    """Flip head/tail for a worm (reverse keypoint axis 0) and recompute stats."""
    with get_db(readonly=True) as conn:
        row = conn.execute(
            "SELECT output_subfolder, regen_pending FROM jobs WHERE job_id=?", (job_id,)
        ).fetchone()
    if not row or not row["output_subfolder"]:
        raise HTTPException(status_code=404, detail="Job not found or not completed")
    if row["regen_pending"]:
        raise HTTPException(
            status_code=409, detail="Regeneration in progress — try again after it completes"
        )

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
        tmp_npz.replace(npz_path)

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

    # Mark job as regenerating, then schedule CSV + video + ZIP rebuild after response is sent.
    # All file operations happen atomically in the background task.
    with get_db() as conn:
        conn.execute("UPDATE jobs SET regen_pending=1 WHERE job_id=?", (job_id,))
    background_tasks.add_task(_regen_and_rebuild, subdir, job_id, motion_stats)

    return {"ok": True, "motion_stats": motion_stats}


class _RerunIn(pydantic.BaseModel):
    keypoints_per_worm: int = 15
    area_threshold: int = 50
    max_age: int = 35
    persistence: int = 50


@app.post("/jobs/{job_id}/rerun")
def rerun_job(job_id: str, body: _RerunIn):
    """Queue a new job using the original video from an existing completed job."""
    if _restart_pending:
        raise HTTPException(
            status_code=503,
            detail="Settings changed — restart the app to apply before submitting new jobs",
        )
    # Validate parameters
    if not (1 <= body.keypoints_per_worm <= 200):
        raise HTTPException(status_code=400, detail="keypoints_per_worm must be 1–200")
    if not (0 <= body.area_threshold <= 100_000):
        raise HTTPException(status_code=400, detail="area_threshold must be 0–100000")
    if not (0 <= body.max_age <= 10_000):
        raise HTTPException(status_code=400, detail="max_age must be 0–10000")
    if not (0 <= body.persistence <= 10_000):
        raise HTTPException(status_code=400, detail="persistence must be 0–10000")

    with get_db(readonly=True) as conn:
        row = conn.execute(
            "SELECT original_filename, output_subfolder, status FROM jobs WHERE job_id=?", (job_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    if row["status"] != "done":
        raise HTTPException(status_code=400, detail=f"Cannot re-run a job with status '{row['status']}' — only 'done' jobs can be re-run")
    if not row["output_subfolder"]:
        raise HTTPException(status_code=404, detail="Job output not found")

    subdir = OUTPUTS / job_id / row["output_subfolder"]
    original_files = list(subdir.glob("*_original.*"))
    if not original_files:
        raise HTTPException(status_code=404, detail="Original video not found in output folder")

    original_path = original_files[0]
    if row["original_filename"]:
        original_filename = row["original_filename"]
    else:
        # Migrated job — original_filename was never stored. Recover it by stripping
        # the timestamp prefix and "_original" suffix added when the file was stored.
        # Stored format: {YYYYMMDD_HHMMSS_ffffff}_{original_stem}_original{ext}
        stem = original_path.stem   # e.g. "20260406_161355_671420_foo_original"
        ext  = original_path.suffix
        stem = re.sub(r'^\d{8}_\d{6}_\d+_', '', stem)  # strip timestamp
        if stem.endswith('_original'):
            stem = stem[:-len('_original')]
        original_filename = (stem or original_path.stem) + ext

    new_job_id = str(uuid4())
    saved_path = UPLOADS / f"{new_job_id}__{original_filename}"
    try:
        shutil.copy2(original_path, saved_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not copy original video: {exc}")

    params_json = json.dumps({
        "keypoints_per_worm": body.keypoints_per_worm,
        "area_threshold": body.area_threshold,
        "max_age": body.max_age,
        "persistence": body.persistence,
    })

    with get_db() as conn:
        conn.execute(
            """INSERT INTO jobs
               (job_id, status, created_at, created_at_unix, original_filename, output_name, params_json)
               VALUES (?, 'pending', ?, ?, ?, ?, ?)""",
            (new_job_id, _now_iso(), _now_unix(), original_filename, Path(original_filename).stem, params_json),
        )

    return {"job_id": new_job_id}


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


# ---------------------------------------------------------------------------
# Frontend static files — served when the built dist/ folder is present.
# In dev mode the Vite dev server handles the frontend separately.
# In packaged/production mode FastAPI serves everything from one process.
# Must be mounted LAST so API routes take priority.
# ---------------------------------------------------------------------------

def _find_frontend_dist() -> Path | None:
    # PyInstaller bundle: data files land in sys._MEIPASS (_internal/ dir)
    if getattr(sys, "frozen", False):
        candidate = Path(sys._MEIPASS) / "frontend_dist"
        if candidate.exists():
            return candidate
    # Normal run: check for a pre-built dist/ next to the project root
    candidate = APP_DIR.parent / "frontend" / "dist"
    if candidate.exists():
        return candidate
    return None

_frontend_dist = _find_frontend_dist()
if _frontend_dist:
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
