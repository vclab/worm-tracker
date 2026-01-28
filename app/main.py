# Thesis/app/main.py
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from uuid import uuid4
import shutil
import subprocess
import zipfile

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
    base_name = output_name if output_name else "processed"

    # Run your tracker
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
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tracking failed: {e}")

    # Collect outputs from tracker
    mp4s = list(job_dir.glob("*.mp4"))
    yaml_files = list(job_dir.glob("*.yaml"))
    npz_files = list(job_dir.glob("*.npz"))

    if not mp4s:
        raise HTTPException(status_code=500, detail="No output video produced.")
    src_mp4 = mp4s[0]

    # Always transcode to browser-friendly H.264 for viewing
    h264_mp4 = job_dir / f"{base_name}_h264.mp4"
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
        h264_mp4 = src_mp4  # fallback (may not stream in-browser)

    # Build a ZIP package containing MP4 (H.264), YAML, and NPZ (if present)
    package_zip = job_dir / f"{base_name}_package.zip"
    with zipfile.ZipFile(package_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        # MP4 (H.264)
        if h264_mp4.exists():
            zf.write(h264_mp4, arcname=h264_mp4.name)
        # YAML (first one if exists)
        if yaml_files:
            zf.write(yaml_files[0], arcname=yaml_files[0].name)
        # NPZ (first one if exists)
        if npz_files:
            zf.write(npz_files[0], arcname=npz_files[0].name)

    # Return URLs for frontend
    return {
        "video": f"/download/{job_id}/{h264_mp4.name}" if h264_mp4.exists() else None,
        "package": f"/download/{job_id}/{package_zip.name}" if package_zip.exists() else None,
        "params": {
            "keypoints_per_worm": keypoints_per_worm,
            "area_threshold": area_threshold,
            "max_age": max_age,
            "persistence": persistence,
            "output_name": base_name,
        },
    }


@app.get("/download/{job_id}/{filename}")
def download_file(job_id: str, filename: str):
    path = OUTPUTS / job_id / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, filename=filename)
