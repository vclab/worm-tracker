# Thesis/app/main.py
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from uuid import uuid4
from contextlib import contextmanager
from datetime import datetime, timezone
import shutil
import subprocess
import zipfile
import json
import queue
import threading
import sqlite3

from app.worm_tracker import run_tracking

app = FastAPI(title="Worm Tracker API (Local)")

# Track active jobs for cancellation (with lock for thread safety)
active_jobs: dict[str, dict] = {}  # job_id -> {"cancel_event": Event, "saved_path": Path, "job_dir": Path}
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
                job_id            TEXT PRIMARY KEY,
                status            TEXT NOT NULL DEFAULT 'running',
                created_at        TEXT NOT NULL,
                finished_at       TEXT,
                original_filename TEXT,
                output_name       TEXT,
                output_subfolder  TEXT,
                params_json       TEXT,
                error_msg         TEXT,
                video_path        TEXT,
                package_path      TEXT,
                data_csv_path     TEXT,
                motion_stats_path TEXT
            )
        """)
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
            mp4s = list(job_dir.glob("**/*.mp4"))
            zips = [z for z in job_dir.glob("**/*.zip") if not z.name.endswith("_data.zip")]
            data_zips = [z for z in job_dir.glob("**/*.zip") if z.name.endswith("_data.zip")]
            jsons = list(job_dir.glob("**/*.json"))
            created_at = datetime.fromtimestamp(job_dir.stat().st_mtime, tz=timezone.utc).isoformat()
            conn.execute(
                """INSERT OR IGNORE INTO jobs
                   (job_id, status, created_at, video_path, package_path, data_csv_path, motion_stats_path)
                   VALUES (?, 'done', ?, ?, ?, ?, ?)""",
                (
                    job_id,
                    created_at,
                    f"/download/{job_id}/{mp4s[0].name}" if mp4s else None,
                    f"/download/{job_id}/{zips[0].name}" if zips else None,
                    f"/download/{job_id}/{data_zips[0].name}" if data_zips else None,
                    f"/download/{job_id}/{jsons[0].name}" if jsons else None,
                ),
            )


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


init_db()
migrate_existing_outputs()

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
    """Delete a completed job record and all its output files."""
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
    output_name: str | None = Form(None),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    # Unique job folder
    job_id = str(uuid4())
    job_dir = OUTPUTS / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    # Save the uploaded file
    saved_path = UPLOADS / f"{job_id}__{file.filename}"
    with saved_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Decide a base name for outputs
    base_name = output_name if output_name else "tracking01"

    # Create cancellation event for this job
    cancel_event = threading.Event()
    with active_jobs_lock:
        active_jobs[job_id] = {
            "cancel_event": cancel_event,
            "saved_path": saved_path,
            "job_dir": job_dir,
        }

    # Record job in DB
    params_json = json.dumps({
        "keypoints_per_worm": keypoints_per_worm,
        "area_threshold": area_threshold,
        "max_age": max_age,
        "persistence": persistence,
    })
    with get_db() as conn:
        conn.execute(
            """INSERT INTO jobs (job_id, status, created_at, original_filename, output_name, params_json)
               VALUES (?, 'running', ?, ?, ?, ?)""",
            (job_id, _now_iso(), file.filename, base_name, params_json),
        )

    def generate_sse():
        # Queue for progress updates from tracker thread
        progress_queue = queue.Queue()
        error_holder = [None]  # To capture exceptions from thread

        def progress_callback(stage, current, total):
            progress_queue.put({"stage": stage, "current": current, "total": total})

        def cancel_check():
            return cancel_event.is_set()

        def run_tracker():
            try:
                run_tracking(
                    video_path=str(saved_path),
                    output_dir=str(job_dir),
                    keypoints_per_worm=keypoints_per_worm,
                    area_threshold=area_threshold,
                    max_age=max_age,
                    show_video=False,
                    output_name=base_name,
                    persistence=persistence,
                    progress_callback=progress_callback,
                    cancel_check=cancel_check,
                )
            except Exception as e:
                error_holder[0] = e
                progress_queue.put({"stage": "error", "message": str(e)})

        # Start tracker in background thread
        tracker_thread = threading.Thread(target=run_tracker)
        tracker_thread.start()

        # Send job_id first so frontend can cancel if needed
        yield f"data: {json.dumps({'stage': 'started', 'job_id': job_id})}\n\n"

        # Yield progress events
        while True:
            # Check if cancelled
            if cancel_event.is_set():
                yield f"data: {json.dumps({'stage': 'cancelled', 'message': 'Processing cancelled'})}\n\n"
                tracker_thread.join(timeout=5)
                with active_jobs_lock:
                    active_jobs.pop(job_id, None)
                return

            try:
                msg = progress_queue.get(timeout=0.5)
                yield f"data: {json.dumps(msg)}\n\n"
                if msg.get("stage") in ("complete", "error", "cancelled"):
                    break
            except queue.Empty:
                if not tracker_thread.is_alive():
                    break
                continue

        tracker_thread.join()

        # Clean up from active jobs
        with active_jobs_lock:
            active_jobs.pop(job_id, None)

        # Check for errors
        if error_holder[0]:
            # Delete upload file on error path
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
            yield f"data: {json.dumps({'stage': 'error', 'message': str(error_holder[0])})}\n\n"
            return

        # Post-processing: transcode and package
        yield f"data: {json.dumps({'stage': 'finalizing', 'current': 0, 'total': 1})}\n\n"

        # Collect outputs from tracker (search recursively in subfolders)
        mp4s = list(job_dir.glob("**/*.mp4"))
        yaml_files = list(job_dir.glob("**/*.yaml"))
        npz_files = list(job_dir.glob("**/*.npz"))
        json_files = list(job_dir.glob("**/*.json"))
        csv_files = list(job_dir.glob("**/*.csv"))

        if not mp4s:
            with get_db() as conn:
                conn.execute(
                    "UPDATE jobs SET status='error', finished_at=?, error_msg=? WHERE job_id=?",
                    (_now_iso(), "No output video produced", job_id),
                )
            yield f"data: {json.dumps({'stage': 'error', 'message': 'No output video produced'})}\n\n"
            return

        src_mp4 = mp4s[0]
        output_subfolder = src_mp4.parent.name

        # Transcode to H.264
        h264_mp4 = src_mp4.parent / f"{output_subfolder}.mp4"
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
        except (subprocess.CalledProcessError, FileNotFoundError):
            h264_mp4 = src_mp4

        # Build ZIP package
        package_zip = src_mp4.parent / f"{output_subfolder}.zip"
        with zipfile.ZipFile(package_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            if saved_path.exists():
                zf.write(saved_path, arcname=f"original_{file.filename}")
            if h264_mp4.exists():
                zf.write(h264_mp4, arcname=h264_mp4.name)
            if yaml_files:
                zf.write(yaml_files[0], arcname=yaml_files[0].name)
            if npz_files:
                zf.write(npz_files[0], arcname=npz_files[0].name)
            if json_files:
                zf.write(json_files[0], arcname=json_files[0].name)

        # Delete upload file now that it's been archived in the ZIP
        try:
            if saved_path.exists():
                saved_path.unlink()
        except Exception:
            pass

        # Build CSV data ZIP for data science export
        data_zip = src_mp4.parent / f"{output_subfolder}_data.zip"
        if csv_files:
            with zipfile.ZipFile(data_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                for csv_file in csv_files:
                    zf.write(csv_file, arcname=csv_file.name)

        # Send final result
        motion_stats_file = json_files[0] if json_files else None
        result = {
            "stage": "done",
            "video": f"/download/{job_id}/{h264_mp4.name}" if h264_mp4.exists() else None,
            "package": f"/download/{job_id}/{package_zip.name}" if package_zip.exists() else None,
            "data_csv": f"/download/{job_id}/{data_zip.name}" if data_zip.exists() else None,
            "motion_stats": f"/download/{job_id}/{motion_stats_file.name}" if motion_stats_file else None,
            "params": {
                "keypoints_per_worm": keypoints_per_worm,
                "area_threshold": area_threshold,
                "max_age": max_age,
                "persistence": persistence,
                "output_name": base_name,
            },
        }

        # Persist completed job to DB
        with get_db() as conn:
            conn.execute(
                """UPDATE jobs SET
                       status='done',
                       finished_at=?,
                       output_subfolder=?,
                       video_path=?,
                       package_path=?,
                       data_csv_path=?,
                       motion_stats_path=?
                   WHERE job_id=?""",
                (
                    _now_iso(),
                    output_subfolder,
                    result["video"],
                    result["package"],
                    result["data_csv"],
                    result["motion_stats"],
                    job_id,
                ),
            )

        yield f"data: {json.dumps(result)}\n\n"

    return StreamingResponse(generate_sse(), media_type="text/event-stream")


@app.get("/download/{job_id}/{filename}")
def download_file(job_id: str, filename: str):
    # Sanitize filename to prevent path traversal attacks
    safe_filename = Path(filename).name  # Extracts just the filename, removes any path components
    if not safe_filename or safe_filename != filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    job_dir = OUTPUTS / job_id
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="Job not found")

    # Search recursively for the file (may be in a subfolder)
    matches = list(job_dir.glob(f"**/{safe_filename}"))
    if not matches:
        raise HTTPException(status_code=404, detail="File not found")

    # Verify the matched file is within job_dir (defense in depth)
    matched_path = matches[0].resolve()
    if not str(matched_path).startswith(str(job_dir.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")

    return FileResponse(matched_path, filename=safe_filename)


@app.post("/cancel/{job_id}")
def cancel_job(job_id: str):
    """Cancel an active job and clean up its files."""
    with active_jobs_lock:
        job_info = active_jobs.get(job_id)
        if not job_info:
            # Job might already be done or doesn't exist
            return JSONResponse({"ok": True, "message": "Job not found or already completed"})
        # Remove from active jobs immediately to prevent race conditions
        active_jobs.pop(job_id, None)

    # Signal cancellation
    job_info["cancel_event"].set()

    # Clean up files
    saved_path = job_info.get("saved_path")
    job_dir = job_info.get("job_dir")

    try:
        if saved_path and saved_path.exists():
            saved_path.unlink()
    except Exception:
        pass

    try:
        if job_dir and job_dir.exists():
            shutil.rmtree(job_dir)
    except Exception:
        pass

    with get_db() as conn:
        conn.execute(
            "UPDATE jobs SET status='cancelled', finished_at=? WHERE job_id=?",
            (_now_iso(), job_id),
        )

    return JSONResponse({"ok": True, "message": "Job cancelled and files cleaned up"})
