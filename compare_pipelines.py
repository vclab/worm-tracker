#!/usr/bin/env python3
"""
compare_pipelines.py — Proxy tracking-quality comparison: Classical vs YOLO pipeline.

Runs both pipelines on the same video(s) WITHOUT writing any tracking output files.
Computes proxy metrics from each pipeline's own output (no ground-truth labels),
then writes:
  - CSV : one row per (video, pipeline), scalar metrics only.
  - JSON: same scalars + per-frame detection counts (for time-series charting).
  - Console: a readable side-by-side summary table.

ALL metrics are PROXY metrics — derived from the pipeline's own behaviour, not from
ground truth.  They measure self-consistency and stability.  Interpret comparatively.

Usage (run from project root so that `app/` is importable):
    python compare_pipelines.py video.mp4 --model weights/best.pt
    python compare_pipelines.py /path/to/videos/ --model weights/best.pt
    python compare_pipelines.py video.mp4 --model weights/best.pt --output-dir results/
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment

# ── Allow running from the project root without installing the package ─────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.worm_tracker import (
    preprocess_frame,
    extract_worm_masks,
    get_skeleton_points,
    compute_cost_matrix,
)
from app.dl_worm_tracker import (
    load_yolo_model,
    extract_yolo_masks,
)

# ──────────────────────────────────────────────────────────────────────────────
# Tunable constants
# All thresholds and defaults live here; pass CLI flags to override tracking params.
# ──────────────────────────────────────────────────────────────────────────────

# Tracking parameters applied identically to both pipelines for a fair comparison.
KEYPOINTS_PER_WORM  = 15    # skeleton keypoints per worm
AREA_THRESHOLD      = 50    # minimum mask pixels to accept a detection
MAX_AGE             = 35    # frames to keep a track alive without a fresh detection
PERSISTENCE         = 50    # min frames for a track to count as a "real" worm (context only)

# YOLO inference
CONF_THRESHOLD      = 0.65  # YOLO confidence cut-off

# Production pipeline values replicated here so matching behaviour is identical.
ASSIGNMENT_COST_THRESHOLD = 80   # Hungarian cost above which a match is rejected
PROXIMITY_GUARD_PX        = 50   # min centroid distance before a brand-new ID is created

# ID-discontinuity detection thresholds (see _count_discontinuities docstring).
# A discontinuity event is counted when a new worm ID appears within
# TEMPORAL_THRESHOLD_FR frames of an existing track's death AND within
# SPATIAL_THRESHOLD_PX pixels of that track's last centroid.
# Tune these to match your microscope resolution and typical worm speed.
SPATIAL_THRESHOLD_PX  = 110   # pixels — centroid proximity for death→birth pairing
TEMPORAL_THRESHOLD_FR = 50   # frames — max gap between death and a nearby rebirth

# Output defaults
DEFAULT_OUTPUT_DIR = "pipeline_comparison_results"
VIDEO_EXTENSIONS   = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".wmv"}

# Progress log every N frames (avoids flooding logs for long videos)
LOG_PROGRESS_EVERY = 200

# ──────────────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("compare_pipelines")


# ──────────────────────────────────────────────────────────────────────────────
# Video path collection
# ──────────────────────────────────────────────────────────────────────────────

def collect_video_paths(input_path: str) -> list[str]:
    """Return sorted video file paths from a single file or a directory."""
    p = Path(input_path)
    if p.is_file():
        if p.suffix.lower() not in VIDEO_EXTENSIONS:
            log.warning("File %s has an unexpected extension; attempting anyway.", p)
        return [str(p)]
    if p.is_dir():
        videos = sorted(
            str(f) for f in p.iterdir()
            if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
        )
        if not videos:
            log.warning("No video files found in %s", p)
        return videos
    log.error("Input path does not exist: %s", input_path)
    return []


# ──────────────────────────────────────────────────────────────────────────────
# Core tracking loop (detection-agnostic)
# ──────────────────────────────────────────────────────────────────────────────

def _run_tracking_loop(
    video_path: str,
    detect_fn,
    label: str,
    keypoints_per_worm: int = KEYPOINTS_PER_WORM,
    max_age: int = MAX_AGE,
) -> dict | None:
    """
    Run the tracking loop on a video using `detect_fn` for per-frame detection.
    No output files are written.

    Replicates the exact tracking logic from the production pipelines
    (Hungarian matching, track memory, proximity guard, head/tail orientation fix),
    calling only imported helper functions.  The only thing stripped out is file I/O.

    Parameters
    ----------
    video_path        : path to the input video
    detect_fn         : callable(frame) -> list of (mask: np.ndarray, is_partial: bool)
                        Swapped between classical and YOLO.
    label             : human-readable pipeline name for log messages
    keypoints_per_worm: number of skeleton keypoints per worm
    max_age           : frames to keep a track alive without a detection

    Returns
    -------
    dict with:
        per_frame_counts : list[int] — active track count per frame
        track_events     : dict[int, dict] — per-track lifecycle info
    or None on unrecoverable failure (bad path, corrupt video that yields zero frames).
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        log.error("[%s] Cannot open video: %s", label, video_path)
        return None

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    log.info("[%s] Starting on %s  (%d frames reported by header)", label, os.path.basename(video_path), total_frames)

    # Track memory: list of {"id": int, "keypoints": np.ndarray, "age": int}
    track_memory: list[dict] = []
    next_id = 0

    # Collected per-run data for metrics
    per_frame_counts: list[int] = []
    # track_events[worm_id] = {
    #   first_frame, first_centroid, last_frame, last_centroid, frame_count
    # }
    track_events: dict[int, dict] = {}

    frame_idx              = 0
    skipped_frames         = 0
    consecutive_read_fails = 0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                # Mirror the production pipeline: tolerate up to 5 consecutive
                # read failures (common with some codecs near the end) before stopping.
                consecutive_read_fails += 1
                if consecutive_read_fails <= 5:
                    skipped_frames += 1
                    log.debug("[%s] Unreadable frame near index %d, skipping.", label, frame_idx)
                    continue
                break  # end of video or unrecoverable codec error
            consecutive_read_fails = 0

            if frame_idx % LOG_PROGRESS_EVERY == 0 and frame_idx > 0:
                log.info("[%s] Frame %d / ~%d", label, frame_idx, total_frames)

            # ── Detection ─────────────────────────────────────────────────────
            # Per-frame failures (e.g. a single corrupt frame) must not stop the run.
            try:
                mask_data = detect_fn(frame)
            except Exception as exc:
                log.warning("[%s] Detection failed on frame %d: %s — skipping frame.", label, frame_idx, exc)
                per_frame_counts.append(0)
                frame_idx += 1
                continue

            # ── Keypoint extraction (imported, shared across both pipelines) ──
            current_keypoints: list[np.ndarray] = []
            for mask, _is_partial in mask_data:
                try:
                    kps = get_skeleton_points(mask, keypoints_per_worm)
                except Exception as exc:
                    log.debug("[%s] get_skeleton_points failed frame %d: %s", label, frame_idx, exc)
                    kps = None
                if kps is not None:
                    current_keypoints.append(kps)

            # ── Hungarian assignment (exact replica of production logic) ───────
            current_ids = [-1] * len(current_keypoints)
            if track_memory and current_keypoints:
                prev_keypoints = [t["keypoints"] for t in track_memory if t["age"] <= max_age]
                prev_ids       = [t["id"]        for t in track_memory if t["age"] <= max_age]
                if prev_keypoints:
                    cost = compute_cost_matrix(current_keypoints, prev_keypoints)
                    row_ind, col_ind = linear_sum_assignment(cost)
                    for i, j in zip(row_ind, col_ind):
                        if i < len(prev_keypoints) and j < len(current_keypoints):
                            if cost[i, j] < ASSIGNMENT_COST_THRESHOLD:
                                # Head/tail orientation fix: if the skeleton is reversed
                                # relative to the previous frame, flip it so orientation
                                # stays consistent across frames in track memory.
                                pv = prev_keypoints[i][-1] - prev_keypoints[i][0]
                                cv_ = current_keypoints[j][-1] - current_keypoints[j][0]
                                pm, cm = np.linalg.norm(pv), np.linalg.norm(cv_)
                                if pm > 1e-6 and cm > 1e-6 and np.dot(pv, cv_) < 0:
                                    current_keypoints[j] = current_keypoints[j][::-1]
                                current_ids[j] = prev_ids[i]

            # ── New-ID assignment with proximity guard ─────────────────────────
            # Suppress a detection that is too close to an existing live track:
            # prevents one worm from spawning multiple IDs simultaneously.
            for j in range(len(current_keypoints)):
                if current_ids[j] != -1:
                    continue
                centroid = np.mean(current_keypoints[j], axis=0)
                too_close = any(
                    np.linalg.norm(centroid - np.mean(t["keypoints"], axis=0)) < PROXIMITY_GUARD_PX
                    for t in track_memory
                )
                if not too_close:
                    current_ids[j] = next_id
                    next_id += 1
                else:
                    current_keypoints[j] = None  # suppress; filtered out below

            # ── Filter out suppressed and unmatched detections ─────────────────
            active_ids: list[int] = []
            active_kps: list[np.ndarray] = []
            for cid, kp in zip(current_ids, current_keypoints):
                if kp is not None and cid != -1:
                    active_ids.append(cid)
                    active_kps.append(kp)

            # ── Update track memory ────────────────────────────────────────────
            # Tracks seen this frame reset to age 0; missing tracks age by 1 until
            # they reach max_age and are dropped (same rule as production pipeline).
            updated_memory: list[dict] = []
            for tid, kps in zip(active_ids, active_kps):
                updated_memory.append({"id": tid, "keypoints": kps, "age": 0})
            active_id_set = set(active_ids)
            for old in track_memory:
                if old["id"] not in active_id_set and old["age"] < max_age:
                    updated_memory.append({
                        "id": old["id"],
                        "keypoints": old["keypoints"],
                        "age": old["age"] + 1,
                    })
            track_memory = updated_memory

            # ── Record per-frame count and per-track lifecycle data ────────────
            per_frame_counts.append(len(active_ids))
            for tid, kps in zip(active_ids, active_kps):
                centroid = np.mean(kps, axis=0)
                if tid not in track_events:
                    track_events[tid] = {
                        "first_frame":    frame_idx,
                        "first_centroid": centroid.copy(),
                        "last_frame":     frame_idx,
                        "last_centroid":  centroid.copy(),
                        "frame_count":    1,
                    }
                else:
                    ev = track_events[tid]
                    ev["last_frame"]    = frame_idx
                    ev["last_centroid"] = centroid.copy()
                    ev["frame_count"]  += 1

            frame_idx += 1

    except Exception as exc:
        # Unexpected loop-level failure: log it but return whatever we collected.
        # Partial data (even a few frames) is more useful than crashing the whole run.
        log.error("[%s] Unexpected error at frame %d: %s", label, frame_idx, exc, exc_info=True)
    finally:
        cap.release()

    if skipped_frames:
        log.warning("[%s] Skipped %d unreadable frame(s).", label, skipped_frames)

    if not per_frame_counts:
        log.error("[%s] No frames were processed for %s.", label, video_path)
        return None

    log.info(
        "[%s] Done — %d frames processed, %d unique IDs created.",
        label, frame_idx, len(track_events),
    )
    return {"per_frame_counts": per_frame_counts, "track_events": track_events}


# ──────────────────────────────────────────────────────────────────────────────
# Metric computation
# ──────────────────────────────────────────────────────────────────────────────

def _count_discontinuities(track_events: dict) -> int:
    """
    Count ID discontinuity events (proxy metric for track fragmentation / ID loss).

    DEFINITION
    ----------
    A discontinuity event is counted when ALL THREE conditions hold:
      (1) A worm track terminates ("death") — its ID stops being seen.
      (2) A NEW worm ID appears ("birth") at most TEMPORAL_THRESHOLD_FR frames later.
      (3) The new ID's first centroid is within SPATIAL_THRESHOLD_PX pixels of the
          dead track's last centroid.
    This pattern suggests the tracker lost a worm and re-detected it as a new ID
    (fragmentation).  It is a PROXY — a genuine new worm entering the field near a
    recently-lost one would also trigger it, so the number over-estimates in crowded
    conditions.

    ALGORITHM
    ---------
    Build lists of "death" (last_frame, last_centroid) and "birth" events (for IDs
    that first appear after frame 0 — frame-0 IDs are founding detections, not
    re-detections).  For each birth in chronological order, search for an unmatched
    death within the threshold windows.  Greedy one-to-one matching: once a death is
    matched it cannot match another birth.  Count matched pairs.

    TUNING
    ------
    SPATIAL_THRESHOLD_PX  and TEMPORAL_THRESHOLD_FR are named constants at the top
    of this file.  Lower values → fewer false positives but risk missing real
    fragmentations.  Higher values → catches more fragmentations but conflates with
    true new-worm events.
    """
    if not track_events:
        return 0

    deaths = [
        (v["last_frame"], v["last_centroid"], k)
        for k, v in track_events.items()
    ]

    # Sort by frame number only (int scalar).  Do NOT let the centroid array
    # participate in the comparison — Python would try to compare numpy arrays
    # element-wise and raise "ambiguous truth value" when frame numbers tie.
    births = sorted(
        [
            (v["first_frame"], v["first_centroid"], k)
            for k, v in track_events.items()
            if v["first_frame"] > 0  # exclude founding detections on frame 0
        ],
        key=lambda x: int(x[0]),
    )

    consumed_death_ids: set[int] = set()
    count = 0

    for birth_frame, birth_centroid, birth_id in births:
        for death_frame, death_centroid, death_id in deaths:
            if death_id == birth_id or death_id in consumed_death_ids:
                continue
            temporal_gap = birth_frame - death_frame
            if temporal_gap <= 0 or temporal_gap > TEMPORAL_THRESHOLD_FR:
                continue  # death must precede birth within the temporal window
            if np.linalg.norm(birth_centroid - death_centroid) <= SPATIAL_THRESHOLD_PX:
                count += 1
                consumed_death_ids.add(death_id)
                break  # this birth is matched; move to the next one

    return count


def compute_metrics(raw: dict) -> dict:
    """
    Compute all proxy metrics from raw tracking loop output.

    Returned keys
    -------------
    worms_detected_per_frame      : list[int]  — active track count per frame
    total_unique_ids              : int         — distinct IDs created over the video
    id_discontinuity_events       : int         — estimated track fragmentations
    mean_track_length             : float       — avg frames a track persists
    max_worms_in_any_single_frame : int         — peak concurrent detection count
    """
    per_frame    = raw["per_frame_counts"]
    track_events = raw["track_events"]

    total_unique_ids = len(track_events)
    max_worms        = max(per_frame) if per_frame else 0

    lengths = [v["frame_count"] for v in track_events.values()]
    mean_track_length = float(np.mean(lengths)) if lengths else 0.0

    discontinuities = _count_discontinuities(track_events)

    return {
        "worms_detected_per_frame":     per_frame,
        "total_unique_ids":             total_unique_ids,
        "id_discontinuity_events":      discontinuities,
        "mean_track_length":            round(mean_track_length, 2),
        "max_worms_in_any_single_frame": max_worms,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Per-video comparison driver
# ──────────────────────────────────────────────────────────────────────────────

def run_pipeline_comparison(
    video_path: str,
    model_path: str,
    keypoints_per_worm: int = KEYPOINTS_PER_WORM,
    area_threshold: int     = AREA_THRESHOLD,
    max_age: int            = MAX_AGE,
    conf_threshold: float   = CONF_THRESHOLD,
) -> dict | None:
    """
    Run both pipelines on one video and return a comparison result dict.

    Each pipeline runs independently on the same source video with identical tracking
    parameters.  If one pipeline errors, the result for that pipeline is omitted but
    the other's data is still returned.

    Returns None only if BOTH pipelines fail to produce any output.
    """
    log.info("=== %s ===", os.path.basename(video_path))

    # Classical detection function (closure over area_threshold)
    def classical_detect(frame):
        binary = preprocess_frame(frame)
        return extract_worm_masks(binary, area_threshold)

    results: dict = {}

    # ── Classical pipeline ─────────────────────────────────────────────────────
    try:
        raw = _run_tracking_loop(
            video_path, classical_detect, "classical",
            keypoints_per_worm=keypoints_per_worm, max_age=max_age,
        )
        if raw is not None:
            results["classical"] = compute_metrics(raw)
        else:
            log.warning("Classical pipeline returned no data for %s", video_path)
    except Exception as exc:
        log.error("Classical pipeline failed for %s: %s", video_path, exc, exc_info=True)

    # ── YOLO pipeline ──────────────────────────────────────────────────────────
    try:
        model = load_yolo_model(model_path)

        def yolo_detect(frame):
            res = model.predict(frame, conf=conf_threshold, verbose=False)
            return extract_yolo_masks(res, frame.shape, area_threshold)

        raw = _run_tracking_loop(
            video_path, yolo_detect, "yolo",
            keypoints_per_worm=keypoints_per_worm, max_age=max_age,
        )
        if raw is not None:
            results["yolo"] = compute_metrics(raw)
        else:
            log.warning("YOLO pipeline returned no data for %s", video_path)
    except Exception as exc:
        log.error("YOLO pipeline failed for %s: %s", video_path, exc, exc_info=True)

    if not results:
        log.error("Both pipelines failed for %s — no result to record.", video_path)
        return None

    return {"video": video_path, **results}


# ──────────────────────────────────────────────────────────────────────────────
# Output writers
# ──────────────────────────────────────────────────────────────────────────────

# Scalar metric columns (the per-frame array is JSON-only)
SCALAR_METRICS = [
    "total_unique_ids",
    "id_discontinuity_events",
    "mean_track_length",
    "max_worms_in_any_single_frame",
]


def write_csv(all_results: list[dict], output_path: str) -> None:
    """Write one row per (video, pipeline) with scalar metrics."""
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["video", "pipeline"] + SCALAR_METRICS)
        writer.writeheader()
        for result in all_results:
            video = result["video"]
            for pipeline in ("classical", "yolo"):
                if pipeline not in result:
                    continue
                row: dict = {"video": video, "pipeline": pipeline}
                for m in SCALAR_METRICS:
                    row[m] = result[pipeline].get(m, "")
                writer.writerow(row)
    log.info("CSV  → %s", output_path)


def write_json(all_results: list[dict], output_path: str) -> None:
    """Write full results including per-frame detection count arrays."""
    # np.ndarray values can't be JSON-serialised; convert to Python lists
    def _convert(obj):
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        raise TypeError(f"Object of type {type(obj)} is not JSON serialisable")

    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2, default=_convert)
    log.info("JSON → %s", output_path)


def format_console_table(all_results: list[dict]) -> str:
    """Return a formatted side-by-side comparison table as a string."""
    COL_W    = 14
    METRIC_W = 38

    lines: list[str] = []
    header = f"{'Metric':<{METRIC_W}} {'Classical':>{COL_W}} {'YOLO':>{COL_W}}"
    sep    = "─" * len(header)

    for result in all_results:
        video_name = os.path.basename(result["video"])
        lines.append(f"\n{sep}")
        lines.append(f"Video: {video_name}")
        lines.append(sep)
        lines.append(header)
        lines.append(sep)

        for m in SCALAR_METRICS:
            c_val = result.get("classical", {}).get(m, "n/a")
            y_val = result.get("yolo",      {}).get(m, "n/a")
            c_str = f"{c_val:.1f}" if isinstance(c_val, float) else str(c_val)
            y_str = f"{y_val:.1f}" if isinstance(y_val, float) else str(y_val)
            lines.append(f"{m:<{METRIC_W}} {c_str:>{COL_W}} {y_str:>{COL_W}}")

        # Extra: frames actually processed (sanity check)
        c_n = len(result.get("classical", {}).get("worms_detected_per_frame", []))
        y_n = len(result.get("yolo",      {}).get("worms_detected_per_frame", []))
        lines.append(sep)
        lines.append(
            f"{'frames_processed (actual)':<{METRIC_W}} {str(c_n):>{COL_W}} {str(y_n):>{COL_W}}"
        )

    lines.append(f"\n{sep}")
    lines.append(
        "NOTE: All metrics are proxy metrics — no ground-truth labels were used.\n"
        f"      id_discontinuity_events uses spatial={SPATIAL_THRESHOLD_PX}px / "
        f"temporal={TEMPORAL_THRESHOLD_FR}fr thresholds."
    )
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "input",
        help="Path to a single video file or a directory of videos.",
    )
    parser.add_argument(
        "--model",
        required=True,
        help="Path to YOLOv8-seg .pt weights file.",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory for CSV/JSON output (default: {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--keypoints",
        type=int,
        default=KEYPOINTS_PER_WORM,
        help=f"Skeleton keypoints per worm (default: {KEYPOINTS_PER_WORM}).",
    )
    parser.add_argument(
        "--min-area",
        type=int,
        default=AREA_THRESHOLD,
        help=f"Minimum mask pixels to accept a detection (default: {AREA_THRESHOLD}).",
    )
    parser.add_argument(
        "--max-age",
        type=int,
        default=MAX_AGE,
        help=f"Frames to keep a track alive without a detection (default: {MAX_AGE}).",
    )
    parser.add_argument(
        "--conf",
        type=float,
        default=CONF_THRESHOLD,
        help=f"YOLO confidence threshold (default: {CONF_THRESHOLD}).",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable DEBUG-level logging.",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if not os.path.isfile(args.model):
        log.error("YOLO model file not found: %s", args.model)
        sys.exit(1)

    video_paths = collect_video_paths(args.input)
    if not video_paths:
        log.error("No videos to process.")
        sys.exit(1)

    os.makedirs(args.output_dir, exist_ok=True)

    log.info(
        "Processing %d video(s) | keypoints=%d, min_area=%d, max_age=%d, conf=%.2f",
        len(video_paths), args.keypoints, args.min_area, args.max_age, args.conf,
    )
    log.info(
        "Discontinuity thresholds: spatial=%dpx, temporal=%dfr",
        SPATIAL_THRESHOLD_PX, TEMPORAL_THRESHOLD_FR,
    )

    all_results: list[dict] = []
    failed_videos: list[str] = []

    for vp in video_paths:
        try:
            result = run_pipeline_comparison(
                vp,
                args.model,
                keypoints_per_worm=args.keypoints,
                area_threshold=args.min_area,
                max_age=args.max_age,
                conf_threshold=args.conf,
            )
            if result is not None:
                all_results.append(result)
            else:
                failed_videos.append(vp)
        except Exception as exc:
            log.error("Unhandled error processing %s: %s", vp, exc, exc_info=True)
            failed_videos.append(vp)

    if not all_results:
        log.error("No results to write — all videos failed.")
        sys.exit(1)

    run_ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path  = os.path.join(args.output_dir, f"comparison_metrics_{run_ts}.csv")
    json_path = os.path.join(args.output_dir, f"comparison_metrics_{run_ts}.json")

    write_csv(all_results, csv_path)
    write_json(all_results, json_path)

    print(format_console_table(all_results))

    if failed_videos:
        print(f"\nFailed ({len(failed_videos)} video(s)):")
        for vp in failed_videos:
            print(f"  {vp}")

    print(f"\nOutputs written to: {os.path.abspath(args.output_dir)}/")


if __name__ == "__main__":
    main()
