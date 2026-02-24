# Thesis/app/main.py
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from uuid import uuid4
import shutil
import subprocess
import zipfile
import json
import queue
import threading

from app.worm_tracker import run_tracking

app = FastAPI(title="Worm Tracker API (Local)")
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


@app.get("/")
def root():
    return {"ok": True, "message": "Worm Tracker API running"}


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

    def generate_sse():
        # Queue for progress updates from tracker thread
        progress_queue = queue.Queue()
        error_holder = [None]  # To capture exceptions from thread

        def progress_callback(stage, current, total):
            progress_queue.put({"stage": stage, "current": current, "total": total})

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
                )
            except Exception as e:
                error_holder[0] = e
                progress_queue.put({"stage": "error", "message": str(e)})

        # Start tracker in background thread
        tracker_thread = threading.Thread(target=run_tracker)
        tracker_thread.start()

        # Yield progress events
        while True:
            try:
                msg = progress_queue.get(timeout=0.5)
                yield f"data: {json.dumps(msg)}\n\n"
                if msg.get("stage") in ("complete", "error"):
                    break
            except queue.Empty:
                if not tracker_thread.is_alive():
                    break
                continue

        tracker_thread.join()

        # Check for errors
        if error_holder[0]:
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
            if h264_mp4.exists():
                zf.write(h264_mp4, arcname=h264_mp4.name)
            if yaml_files:
                zf.write(yaml_files[0], arcname=yaml_files[0].name)
            if npz_files:
                zf.write(npz_files[0], arcname=npz_files[0].name)
            if json_files:
                zf.write(json_files[0], arcname=json_files[0].name)

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
        yield f"data: {json.dumps(result)}\n\n"

    return StreamingResponse(generate_sse(), media_type="text/event-stream")


@app.get("/download/{job_id}/{filename}")
def download_file(job_id: str, filename: str):
    job_dir = OUTPUTS / job_id
    # Search recursively for the file (may be in a subfolder)
    matches = list(job_dir.glob(f"**/{filename}"))
    if not matches:
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(matches[0], filename=filename)
