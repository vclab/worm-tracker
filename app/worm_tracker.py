import argparse
import logging
import os
import shutil
import json
import csv
import cv2
import numpy as np
from skimage.morphology import skeletonize
from skimage.graph import route_through_array
from skimage.util import invert
from scipy.ndimage import convolve
from scipy.optimize import linear_sum_assignment
from tqdm import tqdm
import yaml
from datetime import datetime
import subprocess

logger = logging.getLogger(__name__)

def _compute_git_commit_hash():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            timeout=3,
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return "not-a-git-repo"

_GIT_COMMIT_HASH = _compute_git_commit_hash()

def get_git_commit_hash():
    return _GIT_COMMIT_HASH

def preprocess_frame(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 2)
    binary = cv2.adaptiveThreshold(
        blurred, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        11, 3
    )
    return binary

def extract_worm_masks(binary, area_threshold, edge_margin=5):
    """
    Extract worm masks from binary image.

    Returns:
        list of tuples: (mask, is_partial) where is_partial indicates
        the worm touches a frame edge and may be only partially visible.
    """
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(binary)
    masks = []
    height, width = binary.shape
    for i in range(1, num_labels):
        if stats[i, cv2.CC_STAT_AREA] >= area_threshold:
            x = stats[i, cv2.CC_STAT_LEFT]
            y = stats[i, cv2.CC_STAT_TOP]
            w = stats[i, cv2.CC_STAT_WIDTH]
            h = stats[i, cv2.CC_STAT_HEIGHT]

            # Check if worm touches any edge (partially visible)
            is_partial = (x <= edge_margin or
                          y <= edge_margin or
                          x + w >= width - edge_margin or
                          y + h >= height - edge_margin)

            mask = (labels == i).astype(np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
            masks.append((mask, is_partial))
    return masks

def measure_width_at_point(pt, next_pt, mask):
    """
    Measure contour width perpendicular to skeleton direction at a point.

    Args:
        pt: Current point on skeleton (y, x)
        next_pt: Next point on skeleton for direction (y, x)
        mask: Binary mask of the worm

    Returns:
        Width in pixels perpendicular to skeleton at this point
    """
    direction = np.array(next_pt, dtype=float) - np.array(pt, dtype=float)
    norm = np.linalg.norm(direction)
    if norm < 1e-6:
        return 0

    # Perpendicular direction
    perpendicular = np.array([-direction[1], direction[0]]) / norm

    # Derive search half-range from the mask bounding-box diagonal so the
    # measurement scales with worm size and video resolution.  Clamp between
    # 10 px (minimum for tiny worms) and 200 px (maximum for very large ones).
    rows, cols = np.where(mask > 0)
    if len(rows) > 0:
        bbox_diag = np.hypot(rows.max() - rows.min(), cols.max() - cols.min())
        half_range = int(np.clip(bbox_diag / 4, 10, 200))
    else:
        half_range = 20  # fallback

    # Sample along perpendicular line and count mask pixels
    width = 0
    for d in range(-half_range, half_range + 1):
        sample = np.array(pt) + d * perpendicular
        y, x = int(round(sample[0])), int(round(sample[1]))
        if 0 <= y < mask.shape[0] and 0 <= x < mask.shape[1]:
            if mask[y, x] > 0:
                width += 1
    return width


def get_skeleton_points(mask, num_points):
    """
    Extract evenly-spaced keypoints along the worm skeleton.

    The skeleton is oriented so that keypoint 0 is the head (wider end)
    and keypoint[-1] is the tail (narrower end).
    """
    mask_dilated = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=1)
    skeleton = skeletonize(mask_dilated > 0)

    if np.count_nonzero(skeleton) < 2:
        return None

    kernel = np.ones((3, 3), dtype=int)
    neighbor_count = convolve(skeleton.astype(int), kernel, mode='constant') * skeleton
    endpoints = np.column_stack(np.where(neighbor_count == 2))

    if len(endpoints) < 2:
        return None

    # Pick the two endpoints that are farthest apart rather than first/last in
    # raster order — raster order can select two spatially close points for a
    # coiled or diagonal worm, producing a short or incorrect skeleton path.
    if len(endpoints) == 2:
        start, end = tuple(endpoints[0]), tuple(endpoints[1])
    else:
        diffs = endpoints[:, np.newaxis, :] - endpoints[np.newaxis, :, :]
        dist_matrix = np.linalg.norm(diffs, axis=2)
        i, j = np.unravel_index(np.argmax(dist_matrix), dist_matrix.shape)
        start, end = tuple(endpoints[i]), tuple(endpoints[j])
    try:
        path, _ = route_through_array(invert(skeleton).astype(np.float32), start, end, fully_connected=True)
    except Exception:
        return None

    path = np.array(path)
    if len(path) < 2:
        return None

    # Orient skeleton so head (wider end) is first
    # Measure width at both endpoints
    width_start = measure_width_at_point(path[0], path[min(3, len(path)-1)], mask)
    width_end = measure_width_at_point(path[-1], path[max(-4, -len(path))], mask)

    if width_end > width_start:
        path = path[::-1]  # Flip so head (wider end) is first

    indices = np.linspace(0, len(path) - 1, num=num_points, dtype=int)
    return path[indices]

_MAX_WORMS = 50  # cap to prevent O(N²) blowup on crowded plates


def compute_cost_matrix(current_pts, prev_pts):
    """Vectorised pairwise cost between previous and current worm keypoint sets.

    Cost = 0.7 × centroid distance + 0.3 × mean per-keypoint distance.
    Both inputs are capped at _MAX_WORMS to bound runtime.
    """
    prev_pts    = prev_pts[:_MAX_WORMS]
    current_pts = current_pts[:_MAX_WORMS]

    n_prev = len(prev_pts)
    n_curr = len(current_pts)

    # Stack into arrays: (N, K, 2)
    prev_arr = np.array(prev_pts)    # (n_prev, K, 2)
    curr_arr = np.array(current_pts) # (n_curr, K, 2)

    # Centroid distance: (n_prev, n_curr)
    prev_centroids = prev_arr.mean(axis=1)  # (n_prev, 2)
    curr_centroids = curr_arr.mean(axis=1)  # (n_curr, 2)
    centroid_dist = np.linalg.norm(
        prev_centroids[:, np.newaxis, :] - curr_centroids[np.newaxis, :, :], axis=2
    )  # (n_prev, n_curr)

    # Shape distance: mean per-keypoint Euclidean distance, (n_prev, n_curr)
    # prev_arr[:, np.newaxis] broadcasts over n_curr; curr_arr[np.newaxis] over n_prev
    shape_dist = np.linalg.norm(
        prev_arr[:, np.newaxis, :, :] - curr_arr[np.newaxis, :, :, :], axis=3
    ).mean(axis=2)  # (n_prev, n_curr)

    return 0.7 * centroid_dist + 0.3 * shape_dist

def draw_tracks(frame, worm_keypoints, worm_ids, keypoints_per_worm, partial_flags=None):
    """
    Draw worm tracks on frame.

    Args:
        partial_flags: list of bools indicating if each worm is partially visible.
                       Partial worms are drawn with a magenta outline indicator.
    """
    # Build a colour palette that scales to any keypoints_per_worm value.
    # Use HSV interpolation from red (head, hue=0) through green to blue (tail, hue=240).
    def _hsv_to_bgr(h_deg: float, s: float = 1.0, v: float = 1.0):
        import colorsys
        r, g, b = colorsys.hsv_to_rgb(h_deg / 360.0, s, v)
        return (int(b * 255), int(g * 255), int(r * 255))  # OpenCV uses BGR

    n = max(keypoints_per_worm, 1)
    keypoint_colors = [
        _hsv_to_bgr(240.0 * k / (n - 1) if n > 1 else 0.0)
        for k in range(n)
    ]
    partial_color = (255, 0, 255)  # Magenta for partial worms

    for i, points in enumerate(worm_keypoints):
        is_partial = partial_flags[i] if partial_flags else False

        for k, pt in enumerate(points):
            color = keypoint_colors[k] if k < len(keypoint_colors) else keypoint_colors[-1]
            x, y = int(pt[1]), int(pt[0])

            if is_partial:
                # Draw outer magenta ring for partial worms
                cv2.circle(frame, (x, y), 6, partial_color, 2)
            cv2.circle(frame, (x, y), 4, color, -1)

            if k > 0:
                pt1 = (int(points[k - 1][1]), int(points[k - 1][0]))
                pt2 = (int(pt[1]), int(pt[0]))
                cv2.line(frame, pt1, pt2, color, 2)

        worm_id = worm_ids[i]
        label = f"ID {worm_id}" + (" [P]" if is_partial else "")
        cv2.putText(frame, label, tuple(points[0][::-1]), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    partial_color if is_partial else (255, 255, 255), 1)
    return frame

def compute_motion_stats(keypoint_tracks):
    """
    Compute motion statistics aggregated across all worms.

    For each worm:
      - Compute displacement of each keypoint between consecutive frames
      - Sum all displacements across all keypoints and frames
      - Divide by (num_keypoints × num_frames) = average movement per keypoint per frame

    Also computes separate head (keypoint 0) and tail (last keypoint) motion.
    Includes per-frame motion data for time series visualization.

    Note: keypoint_tracks should already be filtered by persistence before calling.
    """
    if not keypoint_tracks:
        return None

    worm_ids = []  # Track actual worm IDs
    worm_motion_values = []  # One value per worm: avg movement per keypoint per frame
    head_motion_values = []  # Head (keypoint 0) motion per worm
    mid_motion_values = []   # Mid-body (middle keypoint) motion per worm
    tail_motion_values = []  # Tail (last keypoint) motion per worm
    per_frame_data = {}  # Per-frame motion for time series: {worm_id: {head: [...], mid: [...], tail: [...]}}

    for worm_id, kp_list in keypoint_tracks.items():
        # kp_list structure: kp_list[keypoint_idx] = list of [y,x] per frame
        # Shape when converted: (num_keypoints, num_frames, 2)
        num_keypoints = len(kp_list)
        num_frames = len(kp_list[0]) if kp_list else 0

        if num_frames < 2:
            continue

        # Convert to numpy: (num_keypoints, num_frames, 2)
        keypoints = np.array(kp_list)

        # Compute displacement for each keypoint between consecutive frames
        # Shape: (num_keypoints, num_frames-1, 2)
        displacements = np.diff(keypoints, axis=1)

        # Euclidean distance for each keypoint at each frame transition
        # Shape: (num_keypoints, num_frames-1)
        distances = np.linalg.norm(displacements, axis=2)

        # Sum all movements, divide by (num_keypoints × num_frame_transitions)
        total_movement = np.sum(distances)
        num_transitions = num_frames - 1
        avg_movement = total_movement / (num_keypoints * num_transitions)

        # Head motion (keypoint 0)
        head_distances = distances[0]  # Shape: (num_frames-1,)
        avg_head_motion = np.mean(head_distances)

        # Mid-body motion (average of 3 middle keypoints to reduce noise from single-point jitter)
        mid_idx = num_keypoints // 2
        if num_keypoints >= 3:
            mid_distances = (distances[mid_idx - 1] + distances[mid_idx] + distances[mid_idx + 1]) / 3.0
        else:
            mid_distances = distances[mid_idx]  # fallback for very few keypoints
        avg_mid_motion = np.mean(mid_distances)

        # Tail motion (last keypoint)
        tail_distances = distances[-1]  # Shape: (num_frames-1,)
        avg_tail_motion = np.mean(tail_distances)

        worm_ids.append(worm_id)
        worm_motion_values.append(avg_movement)
        head_motion_values.append(float(avg_head_motion))
        mid_motion_values.append(float(avg_mid_motion))
        tail_motion_values.append(float(avg_tail_motion))

        # Store per-frame data for time series (downsample if too many frames)
        # Use a sliding window average to reduce data size
        window_size = max(1, num_transitions // 200)  # Target ~200 points max
        if window_size > 1:
            # Downsample using averaging
            head_downsampled = [
                float(np.mean(head_distances[i:i+window_size]))
                for i in range(0, num_transitions, window_size)
            ]
            mid_downsampled = [
                float(np.mean(mid_distances[i:i+window_size]))
                for i in range(0, num_transitions, window_size)
            ]
            tail_downsampled = [
                float(np.mean(tail_distances[i:i+window_size]))
                for i in range(0, num_transitions, window_size)
            ]
        else:
            head_downsampled = [float(x) for x in head_distances]
            mid_downsampled = [float(x) for x in mid_distances]
            tail_downsampled = [float(x) for x in tail_distances]

        per_frame_data[worm_id] = {
            "head": head_downsampled,
            "mid": mid_downsampled,
            "tail": tail_downsampled,
            "window_size": window_size
        }

    if not worm_motion_values:
        return None

    worm_motion_array = np.array(worm_motion_values)
    head_motion_array = np.array(head_motion_values)
    mid_motion_array  = np.array(mid_motion_values)
    tail_motion_array = np.array(tail_motion_values)

    motion_stats = {
        "num_worms": len(worm_motion_values),
        "mean_motion": float(np.mean(worm_motion_array)),
        "std_motion": float(np.std(worm_motion_array)),
        "min_motion": float(np.min(worm_motion_array)),
        "max_motion": float(np.max(worm_motion_array)),
        "worm_ids": worm_ids,
        "per_worm_motion": worm_motion_values,
        # Head motion stats
        "head_mean_motion": float(np.mean(head_motion_array)),
        "head_std_motion": float(np.std(head_motion_array)),
        "head_min_motion": float(np.min(head_motion_array)),
        "head_max_motion": float(np.max(head_motion_array)),
        "per_worm_head_motion": head_motion_values,
        # Mid-body motion stats (middle keypoint, index num_keypoints // 2)
        "mid_mean_motion": float(np.mean(mid_motion_array)),
        "mid_std_motion": float(np.std(mid_motion_array)),
        "mid_min_motion": float(np.min(mid_motion_array)),
        "mid_max_motion": float(np.max(mid_motion_array)),
        "per_worm_mid_motion": mid_motion_values,
        # Tail motion stats
        "tail_mean_motion": float(np.mean(tail_motion_array)),
        "tail_std_motion": float(np.std(tail_motion_array)),
        "tail_min_motion": float(np.min(tail_motion_array)),
        "tail_max_motion": float(np.max(tail_motion_array)),
        "per_worm_tail_motion": tail_motion_values,
        # Per-frame data for time series visualization
        "per_frame_motion": per_frame_data
    }

    return motion_stats


def export_csv_files(motion_stats, output_dir, base_name):
    """
    Export motion data as CSV files for data science analysis.

    Creates two files:
    - {base_name}_timeseries.csv: Per-frame motion data for all worms
      Columns: frame, worm_id, head_motion, mid_motion, tail_motion
    - {base_name}_summary.csv: Per-worm summary + aggregate stats
      Columns: worm_id, overall_motion, head_motion, mid_motion, tail_motion
      Followed by aggregate rows with row_type='aggregate'.
    """
    import logging as _log
    _logger = _log.getLogger(__name__)

    if not motion_stats:
        return None, None

    # ------------------------------------------------------------------
    # Timeseries CSV
    # ------------------------------------------------------------------
    timeseries_path = os.path.join(output_dir, f"{base_name}_timeseries.csv")
    with open(timeseries_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['frame', 'worm_id', 'head_motion', 'mid_motion', 'tail_motion'])

        per_frame = motion_stats.get('per_frame_motion', {})
        for worm_id, data in per_frame.items():
            head = data.get('head', [])
            mid  = data.get('mid', [])
            tail = data.get('tail', [])
            window_size = data.get('window_size', 1)
            n = min(len(head), len(tail))
            if not mid:
                mid = [None] * n
            for i in range(n):
                frame = i * window_size
                writer.writerow([
                    frame, worm_id,
                    f"{head[i]:.6f}",
                    f"{mid[i]:.6f}" if mid[i] is not None else "",
                    f"{tail[i]:.6f}",
                ])

    _logger.info("Timeseries CSV saved at: %s", timeseries_path)

    # ------------------------------------------------------------------
    # Summary CSV
    # ------------------------------------------------------------------
    summary_path = os.path.join(output_dir, f"{base_name}_summary.csv")
    with open(summary_path, 'w', newline='') as f:
        writer = csv.writer(f)
        # Per-worm rows
        writer.writerow(['row_type', 'worm_id', 'overall_motion', 'head_motion', 'mid_motion', 'tail_motion'])

        worm_ids = motion_stats.get('worm_ids', [])
        overall  = motion_stats.get('per_worm_motion', [])
        head     = motion_stats.get('per_worm_head_motion', [])
        mid      = motion_stats.get('per_worm_mid_motion', [])
        tail     = motion_stats.get('per_worm_tail_motion', [])

        for i, worm_id in enumerate(worm_ids):
            writer.writerow([
                'worm',
                worm_id,
                f"{overall[i]:.6f}" if i < len(overall) else "",
                f"{head[i]:.6f}"    if i < len(head)    else "",
                f"{mid[i]:.6f}"     if i < len(mid)     else "",
                f"{tail[i]:.6f}"    if i < len(tail)    else "",
            ])

        # Aggregate rows — same columns, row_type distinguishes them
        for metric in ('mean', 'std', 'min', 'max'):
            writer.writerow([
                f"aggregate_{metric}",
                "",
                f"{motion_stats.get(f'{metric}_motion', 0):.6f}",
                f"{motion_stats.get(f'head_{metric}_motion', 0):.6f}",
                f"{motion_stats.get(f'mid_{metric}_motion', 0):.6f}",
                f"{motion_stats.get(f'tail_{metric}_motion', 0):.6f}",
            ])

    _logger.info("Summary CSV saved at: %s", summary_path)

    return timeseries_path, summary_path


def run_tracking(video_path, output_dir, keypoints_per_worm, area_threshold, max_age, show_video, output_name=None, keep_frames=False, persistence=50, progress_callback=None, cancel_check=None):
    # Create output subfolder: {timestamp}_{output_name}
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

    frame_idx = 0
    track_memory = []
    next_id = 0
    keypoint_tracks = {}
    partial_worm_ids = set()  # Track worms that have ever been partial (touched edge)

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    pbar = tqdm(total=total_frames, desc="Processing frames", unit="frame")
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            pbar.update(1)

            # Report progress every 10 frames
            if progress_callback and frame_idx % 10 == 0:
                progress_callback("processing", frame_idx, total_frames)

            # Check for cancellation
            if cancel_check and cancel_check():
                if progress_callback:
                    progress_callback("cancelled", frame_idx, total_frames)
                return None

            binary = preprocess_frame(frame)
            mask_data = extract_worm_masks(binary, area_threshold)
            current_keypoints = []
            current_partial_flags = []

            for mask, is_partial in mask_data:
                keypoints = get_skeleton_points(mask, keypoints_per_worm)
                if keypoints is not None:
                    current_keypoints.append(keypoints)
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
                            # Only flip if both vectors have meaningful length — avoids
                            # incorrectly reversing a worm that is nearly stationary or curled
                            if prev_mag > 1e-6 and curr_mag > 1e-6 and np.dot(prev_vec, curr_vec) < 0:
                                current_keypoints[j] = current_keypoints[j][::-1]
                            current_ids[j] = prev_ids[i]

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
                    updated_tracks.append({"id": old_track["id"], "keypoints": old_track["keypoints"], "age": old_track["age"] + 1})

            track_memory = updated_tracks

            for worm_id, keypoints, is_partial in zip(current_ids, current_keypoints, current_partial_flags):
                if worm_id not in keypoint_tracks:
                    keypoint_tracks[worm_id] = [[] for _ in range(keypoints_per_worm)]
                for i in range(keypoints_per_worm):
                    keypoint_tracks[worm_id][i].append(keypoints[i])
                # Mark worm as partial if it ever touches an edge
                if is_partial:
                    partial_worm_ids.add(worm_id)

            annotated = draw_tracks(frame.copy(), current_keypoints, current_ids, keypoints_per_worm, current_partial_flags)
            cv2.imwrite(os.path.join(frames_dir, f"frame_{frame_idx:04d}.png"), annotated)
            frame_idx += 1
    finally:
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
    out = cv2.VideoWriter(output_video_path, cv2.VideoWriter_fourcc(*'mp4v'), input_fps, (width, height))

    num_images = len(image_files)
    for i, filename in enumerate(tqdm(image_files, desc="Generating video", unit="frame")):
        # Check for cancellation
        if cancel_check and cancel_check():
            out.release()
            if progress_callback:
                progress_callback("cancelled", i, num_images)
            return None

        frame = cv2.imread(os.path.join(frames_dir, filename))
        if frame is None:
            logger.warning("Cannot read frame %s, skipping", filename)
            continue
        out.write(frame)
        # Report progress every 10 frames
        if progress_callback and i % 10 == 0:
            progress_callback("generating", i, num_images)

    out.release()
    logger.info("Tracking complete. Output folder: %s", job_output_dir)

    # Filter out worms with fewer than 'persistence' frames AND worms that were ever partial
    filtered_tracks = {
        worm_id: frames for worm_id, frames in keypoint_tracks.items()
        if len(frames[0]) >= persistence and worm_id not in partial_worm_ids
    }
    num_low_persistence = sum(1 for worm_id, frames in keypoint_tracks.items() if len(frames[0]) < persistence)
    num_partial = sum(1 for worm_id in keypoint_tracks if worm_id in partial_worm_ids and len(keypoint_tracks[worm_id][0]) >= persistence)
    num_retained = len(filtered_tracks)
    logger.info("Discarded %d worm(s) with fewer than %d frames", num_low_persistence, persistence)
    logger.info("Discarded %d partial worm(s) (touched frame edge)", num_partial)
    logger.info("Retained %d fully-visible worm(s)", num_retained)

    # Save tracking metadata to YAML
    # Extract original filename (strip job_id__ prefix if present)
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
        "parameters": {
            "keypoints": keypoints_per_worm,
            "min_area": area_threshold,
            "max_age": max_age,
            "persistence": persistence
        },
        "total_frames": frame_idx,
        "worms_tracked": num_retained,
        "worms_discarded_low_persistence": num_low_persistence,
        "worms_discarded_partial": num_partial
    }
    metadata_path = os.path.join(job_output_dir, f"{job_folder}_metadata.yaml")
    with open(metadata_path, 'w') as f:
        yaml.dump(metadata, f)
    logger.info("Metadata saved at: %s", metadata_path)

    # Save worm keypoints to .npz (per worm: [frame][keypoint][y,x])
    # Retained worms use their numeric ID as key; partial worms use "partial_{id}" prefix
    # so regenerate_tracked_video can redraw them with the magenta edge indicator.
    keypoints_npz_path = os.path.join(job_output_dir, f"{job_folder}_keypoints.npz")
    npz_data = {str(worm_id): np.array(frames) for worm_id, frames in filtered_tracks.items()}
    for worm_id, frames in keypoint_tracks.items():
        if worm_id in partial_worm_ids:
            npz_data[f"partial_{worm_id}"] = np.array(frames)
    np.savez_compressed(keypoints_npz_path, **npz_data)
    logger.info("Worm keypoints saved at: %s", keypoints_npz_path)

    # Compute and save motion statistics (filtered_tracks already filtered by persistence)
    motion_stats = compute_motion_stats(filtered_tracks)
    if motion_stats:
        motion_stats_path = os.path.join(job_output_dir, f"{job_folder}_motion_stats.json")
        with open(motion_stats_path, 'w') as f:
            json.dump(motion_stats, f, indent=2)
        logger.info("Motion stats saved at: %s", motion_stats_path)

        # Export CSV files for data science analysis
        export_csv_files(motion_stats, job_output_dir, job_folder)

    # Delete frames directory unless keep_frames is True
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

    # Signal completion
    if progress_callback:
        progress_callback("complete", 1, 1)

    return job_output_dir

def main():
    parser = argparse.ArgumentParser(
        description="Worm tracking from video using skeleton-based interpolation.\n\nExample:\n  python worm_tracker.py input.mov output_dir --keypoints 15 --min-area 50 --max-age 35",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument('video_path', type=str, help='Path to input video')
    parser.add_argument('output_dir', type=str, help='Base directory for output (a subfolder will be created)')
    parser.add_argument('--keypoints', type=int, default=15, help='Number of keypoints per worm (default: 15)')
    parser.add_argument('--min-area', type=int, default=50, help='Minimum area of worm region (default: 50)')
    parser.add_argument('--max-age', type=int, default=35, help='Maximum age to track missing worms (default: 35)')
    parser.add_argument('--show', action='store_true', help='Display the output video after processing')
    parser.add_argument('--output-name', type=str, default=None, help='Custom name for the output video file (e.g., output.mp4)')
    parser.add_argument('--keep-frames', action='store_true', help='Keep the generated frame images (deleted by default)')
    parser.add_argument('--persistence', type=int, default=50, help='Minimum frames a worm must be tracked to be included (default: 50)')

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    run_tracking(args.video_path, args.output_dir, args.keypoints, args.min_area, args.max_age, args.show, args.output_name, args.keep_frames, args.persistence)


if __name__ == "__main__":
    main()
