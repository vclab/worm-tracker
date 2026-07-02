import argparse
import logging
import os
import shutil
import json
import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment
from tqdm import tqdm
import yaml
from datetime import datetime
import subprocess

from app.worm_tracker import (
    get_skeleton_points,
    compute_cost_matrix,
    draw_tracks,
    compute_motion_stats,
    export_csv_files,
    get_git_commit_hash,
    _MAX_WORMS,
)

logger = logging.getLogger(__name__)

_model_cache: dict = {}


def load_yolo_model(model_path: str):
    """Load and cache a YOLO model by resolved absolute path."""
    resolved = os.path.realpath(model_path)
    if resolved not in _model_cache:
        from ultralytics import YOLO
        _model_cache[resolved] = YOLO(resolved)
    return _model_cache[resolved]


def extract_yolo_masks(results, frame_shape, area_threshold, edge_margin=5):
    # TODO: batch inference for throughput
    """Convert one frame's YOLO segmentation results to the same (mask, is_partial)
    list format returned by extract_worm_masks in the classical pipeline.

    Args:
        results: ultralytics Results list from model.predict()
        frame_shape: (height, width[, channels]) of the original frame
        area_threshold: minimum non-zero pixel count to keep a detection
        edge_margin: pixels from any border within which a worm is partial

    Returns:
        list of (mask, is_partial) where mask is uint8 binary (0 or 255)
    """
    height, width = frame_shape[:2]
    mask_list = []

    if results[0].masks is None:
        return mask_list

    # masks.data is a float tensor [N, H_yolo, W_yolo], possibly on GPU
    masks_np = results[0].masks.data.cpu().numpy()  # [N, H_yolo, W_yolo] float32

    for i in range(masks_np.shape[0]):
        raw_mask = masks_np[i]  # [H_yolo, W_yolo] float32 in [0, 1]

        # Resize to original frame dimensions (bilinear) first, then threshold.
        # Thresholding before resize produces jagged edges on upscaled masks.
        resized = cv2.resize(raw_mask, (width, height), interpolation=cv2.INTER_LINEAR)
        binary = (resized > 0.5).astype(np.uint8) * 255

        # Morphological closing — same 3x3 kernel as classical pipeline
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))

        if np.count_nonzero(binary) < area_threshold:
            continue

        # is_partial: any non-zero pixel within edge_margin of any frame border.
        # Checks mask pixels (not bounding boxes) for consistency with classical pipeline.
        rows, cols = np.where(binary > 0)
        is_partial = bool(
            np.any(rows < edge_margin) or
            np.any(rows >= height - edge_margin) or
            np.any(cols < edge_margin) or
            np.any(cols >= width - edge_margin)
        )

        mask_list.append((binary, is_partial))

    return mask_list


def dl_run_tracking(
    video_path,
    output_dir,
    model_path,
    keypoints_per_worm,
    area_threshold,
    max_age,
    show_video,
    output_name=None,
    keep_frames=False,
    persistence=50,
    conf_threshold=0.25,
    progress_callback=None,
    cancel_check=None,
):
    # Validate model path before any file I/O or model loading
    if not model_path or not os.path.isfile(model_path):
        raise RuntimeError(
            "DL pipeline requires a model path. Configure it in Settings → DL model path."
        )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    folder_name = output_name if output_name else "tracking01"
    job_folder = f"{timestamp}_{folder_name}"
    job_output_dir = os.path.join(output_dir, job_folder)
    frames_dir = os.path.join(job_output_dir, "frames")

    os.makedirs(job_output_dir, exist_ok=True)
    os.makedirs(frames_dir, exist_ok=True)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        shutil.rmtree(frames_dir, ignore_errors=True)
        raise RuntimeError(f"Cannot open video: {video_path}")

    input_fps = cap.get(cv2.CAP_PROP_FPS) or 30
    _vid_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    _vid_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if _vid_w < 10 or _vid_h < 10 or _vid_w > 10_000 or _vid_h > 10_000:
        cap.release()
        shutil.rmtree(frames_dir, ignore_errors=True)
        raise ValueError(
            f"Unsupported video dimensions: {_vid_w}x{_vid_h} (must be 10–10000 px per side)"
        )

    model = load_yolo_model(model_path)

    frame_idx = 0
    track_memory = []
    next_id = 0
    keypoint_tracks = {}
    partial_cutoff = {}  # worm_id → track-index of first partial frame (slice [:cutoff] to truncate)

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    pbar = tqdm(total=total_frames, desc="Processing frames (DL)", unit="frame")
    _skipped_frames = 0
    _consecutive_read_failures = 0
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                # Allow a short run of unreadable frames (corrupt but recoverable codec);
                # break only after 5 consecutive failures (normal end-of-file or unrecoverable).
                _consecutive_read_failures += 1
                if _consecutive_read_failures <= 5:
                    _skipped_frames += 1
                    logger.warning(
                        "Could not read frame near index %d, skipping (%d skipped so far)",
                        frame_idx, _skipped_frames,
                    )
                    continue
                break
            _consecutive_read_failures = 0
            pbar.update(1)

            if progress_callback and frame_idx % 10 == 0:
                progress_callback("processing", frame_idx, total_frames)

            if cancel_check and cancel_check():
                if progress_callback:
                    progress_callback("cancelled", frame_idx, total_frames)
                return None

            results = model.predict(frame, conf=conf_threshold, verbose=False)
            mask_data = extract_yolo_masks(results, frame.shape, area_threshold)

            current_keypoints = []
            current_partial_flags = []

            for mask, is_partial in mask_data:
                kps = get_skeleton_points(mask, keypoints_per_worm)
                if kps is not None:
                    current_keypoints.append(kps)
                    current_partial_flags.append(is_partial)

            current_ids = [-1] * len(current_keypoints)

            if len(track_memory) > 0:
                prev_keypoints = [t["keypoints"] for t in track_memory if t["age"] <= max_age]
                prev_ids = [t["id"] for t in track_memory if t["age"] <= max_age]
                cost = compute_cost_matrix(current_keypoints, prev_keypoints)
                row_ind, col_ind = linear_sum_assignment(cost)

                for i, j in zip(row_ind, col_ind):
                    if i < len(prev_keypoints) and j < len(current_keypoints):
                        if cost[i, j] < 80:
                            prev_vec = prev_keypoints[i][-1] - prev_keypoints[i][0]
                            curr_vec = current_keypoints[j][-1] - current_keypoints[j][0]
                            prev_mag = np.linalg.norm(prev_vec)
                            curr_mag = np.linalg.norm(curr_vec)
                            if prev_mag > 1e-6 and curr_mag > 1e-6 and np.dot(prev_vec, curr_vec) < 0:
                                current_keypoints[j] = current_keypoints[j][::-1]
                            current_ids[j] = prev_ids[i]

            # If the model produces two overlapping detections for one worm, the 50 px
            # centroid-proximity guard below suppresses the second as a duplicate.
            # Do not add NMS here — Hungarian matching + proximity handles it.
            for j in range(len(current_keypoints)):
                if current_ids[j] == -1:
                    curr_centroid = np.mean(current_keypoints[j], axis=0)
                    too_close = False
                    for track in track_memory:
                        prev_centroid = np.mean(track["keypoints"], axis=0)
                        if np.linalg.norm(curr_centroid - prev_centroid) < 50:
                            too_close = True
                            break
                    if not too_close:
                        current_ids[j] = next_id
                        next_id += 1
                    else:
                        current_keypoints[j] = None
                        current_partial_flags[j] = None

            filtered_ids = []
            filtered_keypoints = []
            filtered_partial_flags = []
            for cid, kp, pf in zip(current_ids, current_keypoints, current_partial_flags):
                if kp is not None and cid != -1:
                    filtered_ids.append(cid)
                    filtered_keypoints.append(kp)
                    filtered_partial_flags.append(pf)
            current_ids = filtered_ids
            current_keypoints = filtered_keypoints
            current_partial_flags = filtered_partial_flags

            updated_tracks = []
            for tid, kps in zip(current_ids, current_keypoints):
                updated_tracks.append({"id": tid, "keypoints": kps, "age": 0})

            for old_track in track_memory:
                if old_track["id"] not in current_ids and old_track["age"] < max_age:
                    updated_tracks.append({
                        "id": old_track["id"],
                        "keypoints": old_track["keypoints"],
                        "age": old_track["age"] + 1,
                    })

            track_memory = updated_tracks

            for worm_id, kps, is_partial in zip(current_ids, current_keypoints, current_partial_flags):
                if worm_id not in keypoint_tracks:
                    keypoint_tracks[worm_id] = [[] for _ in range(keypoints_per_worm)]
                for i in range(keypoints_per_worm):
                    keypoint_tracks[worm_id][i].append(kps[i])
                if is_partial and worm_id not in partial_cutoff:
                    partial_cutoff[worm_id] = len(keypoint_tracks[worm_id][0]) - 1

            annotated = draw_tracks(
                frame.copy(), current_keypoints, current_ids, keypoints_per_worm, current_partial_flags
            )
            cv2.imwrite(os.path.join(frames_dir, f"frame_{frame_idx:04d}.png"), annotated)
            frame_idx += 1
    finally:
        if _skipped_frames > 0:
            logger.warning("Skipped %d unreadable frame(s) during processing", _skipped_frames)
        pbar.close()
        cap.release()

    output_video_path = os.path.join(job_output_dir, f"{job_folder}_raw.mp4")

    image_files = sorted([f for f in os.listdir(frames_dir) if f.endswith(".png")])
    if not image_files:
        shutil.rmtree(frames_dir, ignore_errors=True)
        raise RuntimeError("No frames were written — video may be empty or unreadable")

    first_image = cv2.imread(os.path.join(frames_dir, image_files[0]))
    if first_image is None:
        shutil.rmtree(frames_dir, ignore_errors=True)
        raise RuntimeError(f"Cannot read first frame: {image_files[0]}")

    height, width, _ = first_image.shape
    out = cv2.VideoWriter(
        output_video_path, cv2.VideoWriter_fourcc(*"mp4v"), input_fps, (width, height)
    )

    num_images = len(image_files)
    for i, filename in enumerate(tqdm(image_files, desc="Generating video", unit="frame")):
        if cancel_check and cancel_check():
            out.release()
            if progress_callback:
                progress_callback("cancelled", i, num_images)
            return None

        img = cv2.imread(os.path.join(frames_dir, filename))
        if img is None:
            logger.warning("Cannot read frame %s, skipping", filename)
            continue
        out.write(img)
        if progress_callback and i % 10 == 0:
            progress_callback("generating", i, num_images)

    out.release()
    logger.info("DL tracking complete. Output folder: %s", job_output_dir)

    # Step 1: truncate edge-touching worms at their first partial frame
    truncated_tracks = {}
    for worm_id, kp_lists in keypoint_tracks.items():
        if worm_id in partial_cutoff:
            cutoff = partial_cutoff[worm_id]
            truncated_tracks[worm_id] = [lst[:cutoff] for lst in kp_lists]
        else:
            truncated_tracks[worm_id] = kp_lists

    # Step 2: persistence filter on the (possibly truncated) length
    filtered_tracks = {
        worm_id: frames for worm_id, frames in truncated_tracks.items()
        if len(frames[0]) >= persistence
    }
    num_truncated = len(partial_cutoff)
    num_low_persistence = sum(1 for frames in truncated_tracks.values() if len(frames[0]) < persistence)
    num_retained = len(filtered_tracks)
    logger.info("Truncated %d worm(s) at first edge-touch", num_truncated)
    logger.info("Discarded %d worm(s) with fewer than %d frames after truncation", num_low_persistence, persistence)
    logger.info("Retained %d fully-visible worm(s)", num_retained)

    input_filename = os.path.basename(video_path)
    if "__" in input_filename:
        original_filename = input_filename.split("__", 1)[1]
    else:
        original_filename = input_filename

    metadata = {
        "git_version": get_git_commit_hash(),
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "input_file": original_filename,
        "output_name": output_name,
        "pipeline": "dl-yolo",
        "model": os.path.basename(model_path),
        "parameters": {
            "keypoints": keypoints_per_worm,
            "min_area": area_threshold,
            "max_age": max_age,
            "persistence": persistence,
            "conf_threshold": conf_threshold,
        },
        "total_frames": frame_idx,
        "worms_tracked": num_retained,
        "worms_truncated_at_edge": num_truncated,
        "worms_discarded_low_persistence": num_low_persistence,
    }
    metadata_path = os.path.join(job_output_dir, f"{job_folder}_metadata.yaml")
    with open(metadata_path, "w") as f:
        yaml.dump(metadata, f)
    logger.info("Metadata saved at: %s", metadata_path)

    keypoints_npz_path = os.path.join(job_output_dir, f"{job_folder}_keypoints.npz")
    npz_data = {str(worm_id): np.array(frames) for worm_id, frames in filtered_tracks.items()}
    for worm_id in partial_cutoff:
        npz_data[f"partial_{worm_id}"] = np.array(keypoint_tracks[worm_id])
    np.savez_compressed(keypoints_npz_path, **npz_data)
    logger.info("Worm keypoints saved at: %s", keypoints_npz_path)

    motion_stats = compute_motion_stats(filtered_tracks)
    if motion_stats:
        motion_stats_path = os.path.join(job_output_dir, f"{job_folder}_motion_stats.json")
        with open(motion_stats_path, "w") as f:
            json.dump(motion_stats, f, indent=2)
        logger.info("Motion stats saved at: %s", motion_stats_path)
        export_csv_files(motion_stats, job_output_dir, job_folder)

    if not keep_frames:
        shutil.rmtree(frames_dir)
        logger.info("Frames deleted.")
    else:
        logger.info("Frames saved in: %s", frames_dir)

    if show_video:
        try:
            import platform
            if platform.system() == "Darwin":
                subprocess.Popen(["open", output_video_path])
            elif platform.system() == "Windows":
                os.startfile(output_video_path)
            else:
                subprocess.Popen(["xdg-open", output_video_path])
        except Exception as e:
            logger.warning("Could not open video: %s", e)

    if progress_callback:
        progress_callback("complete", 1, 1)

    return job_output_dir


def main():
    parser = argparse.ArgumentParser(
        description=(
            "DL worm tracking via YOLOv8-seg segmentation.\n\n"
            "Example:\n"
            "  python -m app.dl_worm_tracker input.mov output_dir --model weights/best.pt"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("video_path", type=str, help="Path to input video")
    parser.add_argument("output_dir", type=str, help="Base output directory (a subfolder will be created)")
    parser.add_argument("--model", type=str, required=True, help="Path to YOLOv8-seg .pt weights file")
    parser.add_argument("--keypoints", type=int, default=15, help="Keypoints per worm (default: 15)")
    parser.add_argument("--min-area", type=int, default=50, help="Minimum mask area in pixels (default: 50)")
    parser.add_argument("--max-age", type=int, default=35, help="Frames to keep tracking a missing worm (default: 35)")
    parser.add_argument("--show", action="store_true", help="Open the output video after processing")
    parser.add_argument("--output-name", type=str, default=None, help="Custom name for the output folder")
    parser.add_argument("--keep-frames", action="store_true", help="Keep per-frame PNG images (deleted by default)")
    parser.add_argument("--persistence", type=int, default=50, help="Minimum tracked frames to include a worm (default: 50)")
    parser.add_argument("--conf-threshold", type=float, default=0.25, help="YOLO confidence threshold (default: 0.25)")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    dl_run_tracking(
        args.video_path,
        args.output_dir,
        args.model,
        args.keypoints,
        args.min_area,
        args.max_age,
        args.show,
        args.output_name,
        args.keep_frames,
        args.persistence,
        args.conf_threshold,
    )


if __name__ == "__main__":
    main()
