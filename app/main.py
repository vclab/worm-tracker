# Thesis/app/main.py
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from uuid import uuid4
from contextlib import contextmanager
from datetime import datetime, timezone
import shutil
import subprocess
import zipfile
import json
import threading
import sqlite3
import time

from app.worm_tracker import run_tracking

app = FastAPI(title="Worm Tracker API (Local)")

# Active processing jobs: job_id -> {"cancel_event": Event}
active_jobs: dict[str, dict] = {}
active_jobs_lock = threading.Lock()

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
    with sqlite3.connect(DB_PATH) as conn:
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
        ]:
            try:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {typedef}")
            except sqlite3.OperationalError:
                pass
        conn.commit()


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
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
            created_at = datetime.fromtimestamp(job_dir.stat().st_mtime, tz=timezone.utc).isoformat()
            conn.execute(
                """INSERT OR IGNORE INTO jobs
                   (job_id, status, created_at, video_path, original_video_path,
                    package_path, data_csv_path, motion_stats_path)
                   VALUES (?, 'done', ?, ?, ?, ?, ?, ?)""",
                (
                    job_id, created_at,
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
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
        src_mp4.unlink()
    except (subprocess.CalledProcessError, FileNotFoundError):
        src_mp4.rename(h264_mp4)

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

    # Build main ZIP
    package_zip = src_mp4.parent / f"{output_subfolder}.zip"
    with zipfile.ZipFile(package_zip, "w", zipfile.ZIP_DEFLATED) as zf:
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

    # Build CSV data ZIP
    data_zip = src_mp4.parent / f"{output_subfolder}_data.zip"
    if csv_files:
        with zipfile.ZipFile(data_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for csv_file in csv_files:
                zf.write(csv_file, arcname=csv_file.name)

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

    params = json.loads(job["params_json"] or "{}")
    base_name = job["output_name"] or "tracking01"
    error_holder = [None]

    def progress_callback(stage, current, total):
        if cancel_event.is_set():
            return
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
        except Exception:
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

    return JSONResponse({"ok": True, "message": "Job cancelled"})
