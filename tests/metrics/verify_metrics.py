"""
Standalone verification script for worm motion metrics.

Independently recomputes all metrics from worm_keypoints.npz and compares
against motion_stats.json, summary CSV, and timeseries CSV.

Usage:
    python verify_metrics.py \
        --npz worm_keypoints.npz \
        --json motion_stats.json \
        --summary summary.csv \
        --timeseries timeseries.csv
"""

import argparse
import csv
import json
import sys

import numpy as np

TOLERANCE = 1e-5

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def close_enough(a, b, tol=TOLERANCE):
    return abs(a - b) <= tol


def check(label, expected, actual, tol=TOLERANCE):
    """Print PASS/FAIL for a single scalar comparison. Returns True if pass."""
    ok = close_enough(expected, actual, tol)
    status = "PASS" if ok else "FAIL"
    if ok:
        print(f"  [{status}] {label}")
    else:
        print(f"  [{status}] {label}  expected={expected!r}  actual={actual!r}  diff={abs(expected-actual):.3e}")
    return ok


def check_list(label, expected_list, actual_list, tol=TOLERANCE):
    """Compare two lists element-by-element. Returns True if all match."""
    if len(expected_list) != len(actual_list):
        preview_e = [round(float(v), 6) for v in expected_list[:5]]
        preview_a = [round(float(v), 6) for v in actual_list[:5]]
        print(f"  [FAIL] {label}  length mismatch: expected {len(expected_list)}, got {len(actual_list)}")
        print(f"         expected first 5: {preview_e}")
        print(f"         actual   first 5: {preview_a}")
        return False
    all_ok = True
    for i, (e, a) in enumerate(zip(expected_list, actual_list)):
        if not close_enough(float(e), float(a), tol):
            print(f"  [FAIL] {label}[{i}]  expected={e!r}  actual={a!r}  diff={abs(float(e)-float(a)):.3e}")
            all_ok = False
    if all_ok:
        print(f"  [PASS] {label}  ({len(expected_list)} values)")
    return all_ok


# ---------------------------------------------------------------------------
# Recompute motion stats from raw keypoints
# ---------------------------------------------------------------------------

def recompute_from_keypoints(npz_path):
    """
    Load worm_keypoints.npz and recompute all motion stats.

    NPZ format: each key is a worm_id (string), value is an array of shape
    (num_keypoints, num_frames, 2).

    Returns a dict matching the structure of motion_stats.json.
    """
    data = np.load(npz_path, allow_pickle=False)
    worm_keys = sorted(data.files)

    if not worm_keys:
        print("ERROR: NPZ file contains no arrays.")
        sys.exit(1)

    worm_ids = []
    worm_motion_values = []
    head_motion_values = []
    tail_motion_values = []
    mid_motion_values = []
    per_frame_data = {}

    for worm_id in worm_keys:
        keypoints = data[worm_id]  # (num_keypoints, num_frames, 2)

        if keypoints.ndim != 3 or keypoints.shape[2] != 2:
            print(f"  WARNING: unexpected shape {keypoints.shape} for worm '{worm_id}', skipping.")
            continue

        num_keypoints, num_frames, _ = keypoints.shape

        if num_frames < 2:
            continue

        # Displacement between consecutive frames: (num_keypoints, num_frames-1, 2)
        displacements = np.diff(keypoints, axis=1)

        # Euclidean distance per keypoint per transition: (num_keypoints, num_frames-1)
        distances = np.linalg.norm(displacements, axis=2)

        num_transitions = num_frames - 1

        # Overall: sum of all distances / (num_keypoints * num_transitions)
        total_movement = np.sum(distances)
        avg_movement = total_movement / (num_keypoints * num_transitions)

        # Head = keypoint 0
        head_distances = distances[0]
        avg_head_motion = float(np.mean(head_distances))

        # Tail = last keypoint
        tail_distances = distances[-1]
        avg_tail_motion = float(np.mean(tail_distances))

        # Midbody = average of 3 middle keypoints
        mid_idx = num_keypoints // 2
        mid_distances = np.mean(distances[mid_idx - 1:mid_idx + 2], axis=0)
        avg_mid_motion = float(np.mean(mid_distances))

        worm_ids.append(worm_id)
        worm_motion_values.append(float(avg_movement))
        head_motion_values.append(avg_head_motion)
        tail_motion_values.append(avg_tail_motion)
        mid_motion_values.append(avg_mid_motion)

        # Per-frame time series with downsampling (same logic as compute_motion_stats)
        window_size = max(1, num_transitions // 200)
        if window_size > 1:
            head_downsampled = [
                float(np.mean(head_distances[i:i + window_size]))
                for i in range(0, num_transitions, window_size)
            ]
            tail_downsampled = [
                float(np.mean(tail_distances[i:i + window_size]))
                for i in range(0, num_transitions, window_size)
            ]
            mid_downsampled = [
                float(np.mean(mid_distances[i:i + window_size]))
                for i in range(0, num_transitions, window_size)
            ]
        else:
            head_downsampled = [float(x) for x in head_distances]
            tail_downsampled = [float(x) for x in tail_distances]
            mid_downsampled = [float(x) for x in mid_distances]

        per_frame_data[worm_id] = {
            "head": head_downsampled,
            "tail": tail_downsampled,
            "mid": mid_downsampled,
            "window_size": window_size,
        }

    if not worm_motion_values:
        print("ERROR: no worms with >= 2 frames found in NPZ.")
        sys.exit(1)

    worm_motion_array = np.array(worm_motion_values)
    head_motion_array = np.array(head_motion_values)
    tail_motion_array = np.array(tail_motion_values)
    mid_motion_array = np.array(mid_motion_values)

    return {
        "num_worms": len(worm_motion_values),
        "mean_motion": float(np.mean(worm_motion_array)),
        "std_motion": float(np.std(worm_motion_array)),
        "min_motion": float(np.min(worm_motion_array)),
        "max_motion": float(np.max(worm_motion_array)),
        "worm_ids": worm_ids,
        "per_worm_motion": worm_motion_values,
        "head_mean_motion": float(np.mean(head_motion_array)),
        "head_std_motion": float(np.std(head_motion_array)),
        "head_min_motion": float(np.min(head_motion_array)),
        "head_max_motion": float(np.max(head_motion_array)),
        "per_worm_head_motion": head_motion_values,
        "tail_mean_motion": float(np.mean(tail_motion_array)),
        "tail_std_motion": float(np.std(tail_motion_array)),
        "tail_min_motion": float(np.min(tail_motion_array)),
        "tail_max_motion": float(np.max(tail_motion_array)),
        "per_worm_tail_motion": tail_motion_values,
        "mid_mean_motion": float(np.mean(mid_motion_array)),
        "mid_std_motion": float(np.std(mid_motion_array)),
        "mid_min_motion": float(np.min(mid_motion_array)),
        "mid_max_motion": float(np.max(mid_motion_array)),
        "per_worm_mid_motion": mid_motion_values,
        "per_frame_motion": per_frame_data,
    }


# ---------------------------------------------------------------------------
# Verification sections
# ---------------------------------------------------------------------------

def verify_json(recomputed, json_path):
    print("\n=== Verifying motion_stats.json ===")
    with open(json_path) as f:
        stored = json.load(f)

    passes = []

    # num_worms
    passes.append(check("num_worms", recomputed["num_worms"], stored.get("num_worms")))

    # Overall summary stats
    for key in ("mean_motion", "std_motion", "min_motion", "max_motion"):
        passes.append(check(key, recomputed[key], stored.get(key, float("nan"))))

    # Head summary stats
    for key in ("head_mean_motion", "head_std_motion", "head_min_motion", "head_max_motion"):
        passes.append(check(key, recomputed[key], stored.get(key, float("nan"))))

    # Tail summary stats
    for key in ("tail_mean_motion", "tail_std_motion", "tail_min_motion", "tail_max_motion"):
        passes.append(check(key, recomputed[key], stored.get(key, float("nan"))))

    # Midbody summary stats
    for key in ("mid_mean_motion", "mid_std_motion", "mid_min_motion", "mid_max_motion"):
        passes.append(check(key, recomputed[key], stored.get(key, float("nan"))))

    # worm_ids order — normalize both sides to int before comparing
    # (NPZ keys are strings; JSON may store integers)
    stored_ids = [int(x) for x in stored.get("worm_ids", [])]
    recomp_ids = [int(x) for x in recomputed["worm_ids"]]
    if stored_ids == recomp_ids:
        print(f"  [PASS] worm_ids order ({len(recomp_ids)} worms)")
        passes.append(True)
    else:
        print(f"  [FAIL] worm_ids order  expected={recomp_ids}  got={stored_ids}")
        passes.append(False)

    # Per-worm motion lists
    passes.append(check_list("per_worm_motion", recomputed["per_worm_motion"], stored.get("per_worm_motion", [])))
    passes.append(check_list("per_worm_head_motion", recomputed["per_worm_head_motion"], stored.get("per_worm_head_motion", [])))
    passes.append(check_list("per_worm_tail_motion", recomputed["per_worm_tail_motion"], stored.get("per_worm_tail_motion", [])))
    passes.append(check_list("per_worm_mid_motion", recomputed["per_worm_mid_motion"], stored.get("per_worm_mid_motion", [])))

    # Per-frame time series
    recomp_pf = recomputed["per_frame_motion"]
    stored_pf = stored.get("per_frame_motion", {})
    print(f"  Checking per_frame_motion for {len(recomp_pf)} worm(s)...")
    for worm_id, recomp_worm in recomp_pf.items():
        wid_str = str(worm_id)
        if wid_str not in stored_pf:
            print(f"  [FAIL] per_frame_motion: worm_id '{wid_str}' missing from JSON  "
                  f"(present keys: {list(stored_pf.keys())})")
            passes.append(False)
            continue
        stored_worm = stored_pf[wid_str]
        passes.append(check(f"per_frame_motion[{wid_str}].window_size",
                            recomp_worm["window_size"], stored_worm.get("window_size")))
        passes.append(check_list(f"per_frame_motion[{wid_str}].head",
                                 recomp_worm["head"], stored_worm.get("head", [])))
        passes.append(check_list(f"per_frame_motion[{wid_str}].tail",
                                 recomp_worm["tail"], stored_worm.get("tail", [])))
        passes.append(check_list(f"per_frame_motion[{wid_str}].mid",
                                 recomp_worm["mid"], stored_worm.get("mid", [])))

    return all(passes)


def verify_summary_csv(recomputed, csv_path):
    print("\n=== Verifying summary CSV ===")
    passes = []

    with open(csv_path, newline='') as f:
        reader = csv.reader(f)
        rows = list(reader)

    # Build expected per-worm rows from recomputed data
    worm_ids = recomputed["worm_ids"]
    overall = recomputed["per_worm_motion"]
    head = recomputed["per_worm_head_motion"]
    tail = recomputed["per_worm_tail_motion"]
    mid = recomputed["per_worm_mid_motion"]

    # First row should be header
    if not rows or rows[0] != ['worm_id', 'overall_motion', 'head_motion', 'tail_motion', 'mid_motion']:
        print(f"  [FAIL] header row  expected=['worm_id','overall_motion','head_motion','tail_motion','mid_motion']  got={rows[0] if rows else []}")
        passes.append(False)
    else:
        print("  [PASS] header row")
        passes.append(True)

    # Per-worm data rows
    for i, worm_id in enumerate(worm_ids):
        csv_row = rows[i + 1] if i + 1 < len(rows) else None
        if csv_row is None:
            print(f"  [FAIL] per-worm row {i} (worm_id={worm_id}): row missing from CSV")
            passes.append(False)
            continue

        # worm_id column
        if str(csv_row[0]) != str(worm_id):
            print(f"  [FAIL] per-worm row {i} worm_id  expected={worm_id}  got={csv_row[0]}")
            passes.append(False)
        else:
            passes.append(True)

        # Numeric columns — compare via float
        for col_idx, (col_name, recomp_val) in enumerate(
            [("overall_motion", overall[i]), ("head_motion", head[i]), ("tail_motion", tail[i]), ("mid_motion", mid[i])],
            start=1,
        ):
            if col_idx >= len(csv_row) or csv_row[col_idx] == "":
                print(f"  [FAIL] row {i} {col_name}: missing value  expected={recomp_val:.6f}  got=(empty)")
                passes.append(False)
            else:
                csv_val = float(csv_row[col_idx])
                passes.append(check(f"row {i} {col_name} (worm {worm_id})", recomp_val, csv_val))

    # Locate aggregate section — find 'mean', 'std', 'min', 'max' rows after the blank line
    agg_map = {}
    for row in rows:
        if row and row[0] in ('mean', 'std', 'min', 'max'):
            agg_map[row[0]] = row

    agg_checks = [
        ('mean', 'overall', recomputed['mean_motion']),
        ('mean', 'head',    recomputed['head_mean_motion']),
        ('mean', 'tail',    recomputed['tail_mean_motion']),
        ('mean', 'mid',     recomputed['mid_mean_motion']),
        ('std',  'overall', recomputed['std_motion']),
        ('std',  'head',    recomputed['head_std_motion']),
        ('std',  'tail',    recomputed['tail_std_motion']),
        ('std',  'mid',     recomputed['mid_std_motion']),
        ('min',  'overall', recomputed['min_motion']),
        ('min',  'head',    recomputed['head_min_motion']),
        ('min',  'tail',    recomputed['tail_min_motion']),
        ('min',  'mid',     recomputed['mid_min_motion']),
        ('max',  'overall', recomputed['max_motion']),
        ('max',  'head',    recomputed['head_max_motion']),
        ('max',  'tail',    recomputed['tail_max_motion']),
        ('max',  'mid',     recomputed['mid_max_motion']),
    ]
    col_to_idx = {'overall': 1, 'head': 2, 'tail': 3, 'mid': 4}

    for metric, col, expected in agg_checks:
        row = agg_map.get(metric)
        if row is None:
            print(f"  [FAIL] aggregate {metric} row missing from CSV  "
                  f"(found rows: {list(agg_map.keys())})  expected={expected:.6f}")
            passes.append(False)
            continue
        idx = col_to_idx[col]
        if idx >= len(row) or row[idx] == "":
            print(f"  [FAIL] aggregate {metric}/{col}: missing value  expected={expected:.6f}  got=(empty)")
            passes.append(False)
        else:
            passes.append(check(f"aggregate {metric}/{col}", expected, float(row[idx])))

    return all(passes)


def verify_timeseries_csv(recomputed, csv_path):
    print("\n=== Verifying timeseries CSV ===")
    passes = []

    with open(csv_path, newline='') as f:
        reader = csv.reader(f)
        rows = list(reader)

    if not rows or rows[0] != ['frame', 'worm_id', 'head_motion', 'tail_motion', 'mid_motion']:
        print(f"  [FAIL] header row  expected=['frame','worm_id','head_motion','tail_motion','mid_motion']  got={rows[0] if rows else []}")
        passes.append(False)
    else:
        print("  [PASS] header row")
        passes.append(True)

    # Build expected rows from recomputed per_frame_motion
    expected_rows = []
    per_frame = recomputed["per_frame_motion"]
    for worm_id, wdata in per_frame.items():
        head_list = wdata["head"]
        tail_list = wdata["tail"]
        mid_list = wdata["mid"]
        window_size = wdata["window_size"]
        for i, (h, t, m) in enumerate(zip(head_list, tail_list, mid_list)):
            frame = i * window_size
            expected_rows.append((frame, str(worm_id), h, t, m))

    data_rows = rows[1:]  # skip header

    if len(data_rows) != len(expected_rows):
        print(f"  [FAIL] row count  expected={len(expected_rows)}  got={len(data_rows)}")
        passes.append(False)
        # Still try to check as many rows as possible
    else:
        print(f"  [PASS] row count ({len(expected_rows)} data rows)")
        passes.append(True)

    for i, (exp, got) in enumerate(zip(expected_rows, data_rows)):
        exp_frame, exp_wid, exp_h, exp_t, exp_m = exp

        if len(got) < 5:
            print(f"  [FAIL] timeseries row {i+1}: only {len(got)} columns  "
                  f"got={got}  expected=[{exp_frame}, '{exp_wid}', {exp_h:.6f}, {exp_t:.6f}, {exp_m:.6f}]")
            passes.append(False)
            continue

        got_frame = int(got[0])
        got_wid = got[1]
        got_h = float(got[2])
        got_t = float(got[3])
        got_m = float(got[4])

        row_ok = True
        if got_frame != exp_frame:
            print(f"  [FAIL] row {i+1} frame  expected={exp_frame}  got={got_frame}")
            row_ok = False
        if got_wid != str(exp_wid):
            print(f"  [FAIL] row {i+1} worm_id  expected={exp_wid}  got={got_wid}")
            row_ok = False
        if not close_enough(exp_h, got_h):
            print(f"  [FAIL] row {i+1} head_motion  expected={exp_h}  got={got_h}  diff={abs(exp_h-got_h):.3e}")
            row_ok = False
        if not close_enough(exp_t, got_t):
            print(f"  [FAIL] row {i+1} tail_motion  expected={exp_t}  got={got_t}  diff={abs(exp_t-got_t):.3e}")
            row_ok = False
        if not close_enough(exp_m, got_m):
            print(f"  [FAIL] row {i+1} mid_motion  expected={exp_m}  got={got_m}  diff={abs(exp_m-got_m):.3e}")
            row_ok = False

        if row_ok:
            passes.append(True)
        else:
            passes.append(False)

    if all(p is True for p in passes[2:]):  # skip header/count checks already printed
        print(f"  [PASS] all {len(expected_rows)} timeseries data rows match")

    return all(passes)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Verify worm motion metrics.")
    parser.add_argument("--npz",        required=True, help="Path to worm_keypoints.npz")
    parser.add_argument("--json",       required=True, help="Path to motion_stats.json")
    parser.add_argument("--summary",    required=True, help="Path to summary CSV")
    parser.add_argument("--timeseries", required=True, help="Path to timeseries CSV")
    args = parser.parse_args()

    print(f"Loading and recomputing from: {args.npz}")
    recomputed = recompute_from_keypoints(args.npz)
    print(f"  Found {recomputed['num_worms']} worm(s) with >= 2 frames.")

    json_ok  = verify_json(recomputed, args.json)
    summ_ok  = verify_summary_csv(recomputed, args.summary)
    ts_ok    = verify_timeseries_csv(recomputed, args.timeseries)

    print("\n" + "=" * 50)
    results = {
        "motion_stats.json":  json_ok,
        "summary CSV":        summ_ok,
        "timeseries CSV":     ts_ok,
    }
    all_passed = True
    for name, ok in results.items():
        status = "PASS" if ok else "FAIL"
        print(f"  {status}  {name}")
        if not ok:
            all_passed = False

    print("=" * 50)
    if all_passed:
        print("OVERALL: PASS")
    else:
        print("OVERALL: FAIL")
        sys.exit(1)


if __name__ == "__main__":
    main()
