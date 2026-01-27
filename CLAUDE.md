# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Worm Tracker is a full-stack application for tracking C. elegans (microscopic worms) in video data. It extracts skeleton-based keypoints to capture body deformation over time for behavioral analysis.

- **Backend**: Python + FastAPI (in `/app`)
- **Frontend**: React + Vite (in `/frontend`)

## Common Commands

### Backend (from project root)
```bash
# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # macOS/Linux
venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt

# Run development server (with auto-reload)
uvicorn app.main:app --reload --port 8000
```

### Frontend (from `/frontend`)
```bash
npm install
npm run dev      # Development server at http://127.0.0.1:5173
npm run build    # Production build to /dist
npm run lint     # ESLint
npm run preview  # Preview production build
```

### External Dependency
FFmpeg is required for H.264 video transcoding (browser playback):
- macOS: `brew install ffmpeg`
- Linux: `apt install ffmpeg`

## Architecture

### Backend (`/app`)

**`main.py`** - FastAPI server with endpoints:
- `POST /upload` - Accepts video file + parameters, runs tracking, returns download URLs
- `GET /download/{job_id}/{filename}` - File download

**`worm_tracker.py`** - Core computer vision pipeline:
1. Frame preprocessing (grayscale, blur, adaptive threshold)
2. Worm detection via connected components
3. Skeleton extraction using scikit-image skeletonization
4. Multi-object tracking with Hungarian algorithm (scipy.optimize.linear_sum_assignment)
5. Output: annotated MP4, YAML metadata, NPZ keypoints

Key tracking parameters (configurable via UI):
- `keypoints_per_worm` (default: 15) - skeleton points per worm
- `area_threshold` (default: 50) - minimum pixels for valid worm region
- `max_age` (default: 35) - frames to track missing worm before dropping

### Frontend (`/frontend/src`)

**`App.jsx`** - Single-page app with file upload, parameter form, video player, and download links. Uses React hooks for state management.

**API calls**: POST to `http://127.0.0.1:8000/upload` with FormData

## Output Formats

- **Video**: MP4 with H.264 codec, annotated with colored skeleton keypoints and worm IDs
- **Metadata**: YAML with git version, timestamp, parameters, frame count
- **Keypoints**: NPZ file with per-worm arrays of shape `(frames, keypoints, 2)` containing `[y, x]` coordinates

## File Locations

- Uploads: `/app/uploads/` (gitignored, auto-created)
- Outputs: `/app/outputs/{job_id}/` (gitignored, auto-created)

## No Automated Tests

This project currently has no test suite. Testing is manual via the web interface.
