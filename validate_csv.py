"""
CSV validation script for Worm Tracker exports.

Usage:
    python validate_csv.py <output_dir>

    output_dir: the job subfolder inside app/outputs/{job_id}/
                e.g. "app/outputs/62c4.../20260405_083619_..."

For flip validation:
    python validate_csv.py <output_dir> --pre-flip <pre_flip_data_dir> --flipped-worm <worm_id>

    --pre-flip: path to the _data/ folder from BEFORE the flip
    --flipped-worm: worm_id that was flipped (e.g. 0)
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
WARN = "\033[93m⚠\033[0m"

errors = []

def ok(msg):
    print(f"  {PASS} {msg}")

def fail(msg):
    print(f"  {FAIL} {msg}")
    errors.append(msg)

def warn(msg):
    print(f"  {WARN} {msg}")

def check(condition, pass_msg, fail_msg):
    if condition:
        ok(pass_msg)
    else:
        fail(fail_msg)
    return condition


def read_summary_csv(path):
    """Read summary CSV, stopping before the blank / aggregate block."""
    rows = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get("worm_id") or row["worm_id"].startswith("#"):
                break
            rows.append(row)
    return rows


def read_aggregate_block(path):
    """Read the aggregate stats block from summary CSV.

    Supports both the legacy '# Aggregate' comment-block format and the
    current row_type='aggregate_<metric>' format.
    """
    agg = {}
    in_block = False
    with open(path, newline="") as f:
        reader = csv.reader(f)
        header = None
        for row in reader:
            if not row:
                continue
            # Current format: row_type column with aggregate_mean etc.
            if header is None and row[0] == "row_type":
                header = row
                continue
            if header is not None and row[0].startswith("aggregate_"):
                metric = row[0][len("aggregate_"):]  # e.g. "mean"
                agg[metric] = {
                    "overall": float(row[2]),
                    "head":    float(row[3]),
                    "tail":    float(row[5]),
                }
                continue
            # Legacy format: # Aggregate comment block
            if row[0].startswith("# Aggregate"):
                in_block = True
                continue
            if in_block and row[0] == "metric":
                continue
            if in_block and len(row) >= 4:
                agg[row[0]] = {"overall": float(row[1]),
                               "head":    float(row[2]),
                               "tail":    float(row[3])}
    return agg


def read_timeseries_csv(path):
    """Read timeseries CSV into a dict: {worm_id: {frame: [frame,...], head: [...], tail: [...]}}."""
    worms = {}
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            wid = row["worm_id"]
            if wid not in worms:
                worms[wid] = {"frame": [], "head": [], "tail": []}
            worms[wid]["frame"].append(int(row["frame"]))
            worms[wid]["head"].append(float(row["head_motion"]))
            worms[wid]["tail"].append(float(row["tail_motion"]))
    return worms


# ─────────────────────────────────────────────────────────────────────────────
# Scheme 1 — Summary CSV vs JSON
# ─────────────────────────────────────────────────────────────────────────────

def validate_summary_vs_json(stats, summary_rows, agg_block):
    print("\n[Scheme 1] Summary CSV vs motion_stats.json")

    worm_ids_json = [str(w) for w in stats["worm_ids"]]

    # Worm count
    check(len(summary_rows) == len(worm_ids_json),
          f"Row count matches: {len(summary_rows)} worms",
          f"Row count mismatch: CSV={len(summary_rows)}, JSON={len(worm_ids_json)}")

    # Per-worm values
    for i, wid in enumerate(worm_ids_json):
        row = next((r for r in summary_rows if str(r["worm_id"]) == wid), None)
        if row is None:
            fail(f"Worm {wid} missing from summary CSV")
            continue

        ov_csv = float(row["overall_motion"])
        hd_csv = float(row["head_motion"])
        tl_csv = float(row["tail_motion"])
        ov_json = stats["per_worm_motion"][i]
        hd_json = stats["per_worm_head_motion"][i]
        tl_json = stats["per_worm_tail_motion"][i]

        check(abs(ov_csv - ov_json) < 1e-4,
              f"Worm {wid} overall_motion matches  ({ov_csv:.6f})",
              f"Worm {wid} overall_motion MISMATCH  CSV={ov_csv:.6f} JSON={ov_json:.6f}")
        check(abs(hd_csv - hd_json) < 1e-4,
              f"Worm {wid} head_motion    matches  ({hd_csv:.6f})",
              f"Worm {wid} head_motion    MISMATCH  CSV={hd_csv:.6f} JSON={hd_json:.6f}")
        check(abs(tl_csv - tl_json) < 1e-4,
              f"Worm {wid} tail_motion    matches  ({tl_csv:.6f})",
              f"Worm {wid} tail_motion    MISMATCH  CSV={tl_csv:.6f} JSON={tl_json:.6f}")

    # Aggregate block
    if not agg_block:
        fail("Aggregate block missing from summary CSV")
        return

    for metric in ["mean", "std", "min", "max"]:
        json_keys = {
            "mean": ("mean_motion", "head_mean_motion", "tail_mean_motion"),
            "std":  ("std_motion",  "head_std_motion",  "tail_std_motion"),
            "min":  ("min_motion",  "head_min_motion",  "tail_min_motion"),
            "max":  ("max_motion",  "head_max_motion",  "tail_max_motion"),
        }
        ok_key, hk_key, tk_key = json_keys[metric]
        if metric not in agg_block:
            fail(f"Aggregate metric '{metric}' missing from CSV")
            continue
        check(abs(agg_block[metric]["overall"] - stats[ok_key]) < 1e-4,
              f"Aggregate {metric} overall matches ({agg_block[metric]['overall']:.6f})",
              f"Aggregate {metric} overall MISMATCH  CSV={agg_block[metric]['overall']:.6f} JSON={stats[ok_key]:.6f}")
        check(abs(agg_block[metric]["head"] - stats[hk_key]) < 1e-4,
              f"Aggregate {metric} head    matches",
              f"Aggregate {metric} head    MISMATCH  CSV={agg_block[metric]['head']:.6f} JSON={stats[hk_key]:.6f}")
        check(abs(agg_block[metric]["tail"] - stats[tk_key]) < 1e-4,
              f"Aggregate {metric} tail    matches",
              f"Aggregate {metric} tail    MISMATCH  CSV={agg_block[metric]['tail']:.6f} JSON={stats[tk_key]:.6f}")


# ─────────────────────────────────────────────────────────────────────────────
# Scheme 2 — Timeseries CSV vs JSON
# ─────────────────────────────────────────────────────────────────────────────

def validate_timeseries_vs_json(stats, ts_worms):
    print("\n[Scheme 2] Timeseries CSV vs motion_stats.json")

    per_frame = stats.get("per_frame_motion", {})

    for wid_raw, pf in per_frame.items():
        wid = str(wid_raw)
        if wid not in ts_worms:
            fail(f"Worm {wid} missing from timeseries CSV")
            continue

        head_json = pf["head"]
        tail_json = pf["tail"]
        window_size = pf["window_size"]

        head_csv = ts_worms[wid]["head"]
        tail_csv = ts_worms[wid]["tail"]
        frames_csv = ts_worms[wid]["frame"]

        # Row count
        check(len(head_csv) == len(head_json),
              f"Worm {wid}: row count matches ({len(head_csv)} rows)",
              f"Worm {wid}: row count MISMATCH CSV={len(head_csv)} JSON={len(head_json)}")

        # Frame indices
        expected_frames = [i * window_size for i in range(len(head_json))]
        frames_match = all(abs(a - b) < 1 for a, b in zip(frames_csv, expected_frames))
        check(frames_match,
              f"Worm {wid}: frame indices correct (window_size={window_size})",
              f"Worm {wid}: frame index MISMATCH at first diff: "
              f"CSV={frames_csv[:5]} expected={expected_frames[:5]}")

        # Values
        n = min(len(head_csv), len(head_json))
        max_head_err = max(abs(head_csv[i] - head_json[i]) for i in range(n)) if n else 0
        max_tail_err = max(abs(tail_csv[i] - tail_json[i]) for i in range(n)) if n else 0
        check(max_head_err < 1e-4,
              f"Worm {wid}: head_motion values match  (max_err={max_head_err:.2e})",
              f"Worm {wid}: head_motion MISMATCH  max_err={max_head_err:.6f}")
        check(max_tail_err < 1e-4,
              f"Worm {wid}: tail_motion values match  (max_err={max_tail_err:.2e})",
              f"Worm {wid}: tail_motion MISMATCH  max_err={max_tail_err:.6f}")


# ─────────────────────────────────────────────────────────────────────────────
# Scheme 3 — Recompute from NPZ and compare to timeseries CSV
# ─────────────────────────────────────────────────────────────────────────────

def validate_npz_recompute(npz_path, ts_worms, summary_rows):
    print("\n[Scheme 3] Recompute from NPZ vs CSV")

    npz = np.load(npz_path, allow_pickle=True)
    retained_keys = [k for k in npz.files if not k.startswith("partial_")]
    partial_keys  = [k for k in npz.files if k.startswith("partial_")]

    ok(f"NPZ contains {len(retained_keys)} retained worm(s): {retained_keys}")
    if partial_keys:
        ok(f"NPZ contains {len(partial_keys)} partial worm(s) — excluded from CSV as expected: {partial_keys}")

    for wid in retained_keys:
        kp = npz[wid]  # (num_keypoints, num_frames, 2)
        if kp.ndim != 3 or kp.shape[2] != 2:
            fail(f"Worm {wid}: unexpected NPZ shape {kp.shape}")
            continue

        num_keypoints, num_frames, _ = kp.shape
        if num_frames < 2:
            warn(f"Worm {wid}: only {num_frames} frame(s), skipping")
            continue

        head_kp = kp[0]   # (num_frames, 2)
        tail_kp = kp[-1]

        head_dist = np.linalg.norm(np.diff(head_kp, axis=0), axis=1)
        tail_dist = np.linalg.norm(np.diff(tail_kp, axis=0), axis=1)
        all_dist  = np.linalg.norm(np.diff(kp, axis=1), axis=2)  # (kp, frames-1)

        num_transitions = num_frames - 1
        window_size = max(1, num_transitions // 200)

        head_ds = [float(np.mean(head_dist[i:i+window_size]))
                   for i in range(0, num_transitions, window_size)]
        tail_ds = [float(np.mean(tail_dist[i:i+window_size]))
                   for i in range(0, num_transitions, window_size)]

        avg_overall = float(np.sum(all_dist) / (num_keypoints * num_transitions))
        avg_head    = float(np.mean(head_dist))
        avg_tail    = float(np.mean(tail_dist))

        # Compare timeseries
        if wid in ts_worms:
            n = min(len(head_ds), len(ts_worms[wid]["head"]))
            max_h = max(abs(head_ds[i] - ts_worms[wid]["head"][i]) for i in range(n))
            max_t = max(abs(tail_ds[i] - ts_worms[wid]["tail"][i]) for i in range(n))
            check(max_h < 1e-4,
                  f"Worm {wid}: NPZ→head timeseries matches CSV  (max_err={max_h:.2e})",
                  f"Worm {wid}: NPZ→head timeseries MISMATCH  max_err={max_h:.6f}")
            check(max_t < 1e-4,
                  f"Worm {wid}: NPZ→tail timeseries matches CSV  (max_err={max_t:.2e})",
                  f"Worm {wid}: NPZ→tail timeseries MISMATCH  max_err={max_t:.6f}")
        else:
            fail(f"Worm {wid}: not found in timeseries CSV")

        # Compare summary
        row = next((r for r in summary_rows if str(r["worm_id"]) == str(wid)), None)
        if row:
            check(abs(float(row["overall_motion"]) - avg_overall) < 1e-4,
                  f"Worm {wid}: NPZ→overall_motion matches summary CSV  ({avg_overall:.6f})",
                  f"Worm {wid}: NPZ→overall_motion MISMATCH  recomputed={avg_overall:.6f} CSV={row['overall_motion']}")
            check(abs(float(row["head_motion"]) - avg_head) < 1e-4,
                  f"Worm {wid}: NPZ→head_motion   matches summary CSV  ({avg_head:.6f})",
                  f"Worm {wid}: NPZ→head_motion   MISMATCH  recomputed={avg_head:.6f} CSV={row['head_motion']}")
            check(abs(float(row["tail_motion"]) - avg_tail) < 1e-4,
                  f"Worm {wid}: NPZ→tail_motion   matches summary CSV  ({avg_tail:.6f})",
                  f"Worm {wid}: NPZ→tail_motion   MISMATCH  recomputed={avg_tail:.6f} CSV={row['tail_motion']}")
        else:
            fail(f"Worm {wid}: not found in summary CSV")

    npz.close()


# ─────────────────────────────────────────────────────────────────────────────
# Scheme 4 — H/T flip validation
# ─────────────────────────────────────────────────────────────────────────────

def validate_flip(pre_dir, post_ts_worms, post_summary_rows, flipped_worm_id):
    print(f"\n[Scheme 4] H/T flip validation (flipped worm: {flipped_worm_id})")

    fwid = str(flipped_worm_id)

    # Find pre-flip timeseries
    pre_ts_files = list(Path(pre_dir).glob("*_timeseries.csv"))
    pre_sum_files = list(Path(pre_dir).glob("*_summary.csv"))
    if not pre_ts_files or not pre_sum_files:
        fail(f"Could not find pre-flip CSVs in {pre_dir}")
        return

    pre_ts_worms = read_timeseries_csv(pre_ts_files[0])
    pre_summary  = read_summary_csv(pre_sum_files[0])

    if fwid not in pre_ts_worms:
        fail(f"Worm {fwid} not found in pre-flip timeseries CSV")
        return
    if fwid not in post_ts_worms:
        fail(f"Worm {fwid} not found in post-flip timeseries CSV")
        return

    pre_head  = pre_ts_worms[fwid]["head"]
    pre_tail  = pre_ts_worms[fwid]["tail"]
    post_head = post_ts_worms[fwid]["head"]
    post_tail = post_ts_worms[fwid]["tail"]

    n = min(len(pre_head), len(post_head))

    # After flip: post_head == pre_tail and post_tail == pre_head
    max_err_ht = max(abs(post_head[i] - pre_tail[i]) for i in range(n))
    max_err_th = max(abs(post_tail[i] - pre_head[i]) for i in range(n))

    check(max_err_ht < 1e-4,
          f"Worm {fwid}: post-flip head_motion == pre-flip tail_motion  (max_err={max_err_ht:.2e})",
          f"Worm {fwid}: head/tail NOT swapped in timeseries  max_err={max_err_ht:.6f}")
    check(max_err_th < 1e-4,
          f"Worm {fwid}: post-flip tail_motion == pre-flip head_motion  (max_err={max_err_th:.2e})",
          f"Worm {fwid}: tail/head NOT swapped in timeseries  max_err={max_err_th:.6f}")

    # Summary: head_motion and tail_motion should be swapped
    pre_row  = next((r for r in pre_summary  if str(r["worm_id"]) == fwid), None)
    post_row = next((r for r in post_summary_rows if str(r["worm_id"]) == fwid), None)
    if pre_row and post_row:
        pre_hd  = float(pre_row["head_motion"])
        pre_tl  = float(pre_row["tail_motion"])
        post_hd = float(post_row["head_motion"])
        post_tl = float(post_row["tail_motion"])
        pre_ov  = float(pre_row["overall_motion"])
        post_ov = float(post_row["overall_motion"])

        check(abs(post_hd - pre_tl) < 1e-4,
              f"Worm {fwid}: summary head_motion swapped correctly  ({post_hd:.6f} == {pre_tl:.6f})",
              f"Worm {fwid}: summary head_motion NOT swapped  post={post_hd:.6f} pre_tail={pre_tl:.6f}")
        check(abs(post_tl - pre_hd) < 1e-4,
              f"Worm {fwid}: summary tail_motion swapped correctly  ({post_tl:.6f} == {pre_hd:.6f})",
              f"Worm {fwid}: summary tail_motion NOT swapped  post={post_tl:.6f} pre_head={pre_hd:.6f}")
        check(abs(post_ov - pre_ov) < 1e-4,
              f"Worm {fwid}: overall_motion unchanged after flip  ({post_ov:.6f})",
              f"Worm {fwid}: overall_motion changed after flip  pre={pre_ov:.6f} post={post_ov:.6f}")

    # Unflipped worms: timeseries must be identical
    all_worms = set(pre_ts_worms.keys()) | set(post_ts_worms.keys())
    for wid in sorted(all_worms):
        if str(wid) == fwid:
            continue
        if wid not in pre_ts_worms or wid not in post_ts_worms:
            warn(f"Worm {wid}: only present in one of the CSVs, skipping")
            continue
        n2 = min(len(pre_ts_worms[wid]["head"]), len(post_ts_worms[wid]["head"]))
        max_h = max(abs(pre_ts_worms[wid]["head"][i] - post_ts_worms[wid]["head"][i]) for i in range(n2))
        max_t = max(abs(pre_ts_worms[wid]["tail"][i] - post_ts_worms[wid]["tail"][i]) for i in range(n2))
        check(max_h < 1e-4 and max_t < 1e-4,
              f"Worm {wid}: unchanged after flip of worm {fwid}",
              f"Worm {wid}: CHANGED after flip of worm {fwid}  head_err={max_h:.6f} tail_err={max_t:.6f}")


# ─────────────────────────────────────────────────────────────────────────────
# Plot generation (Scheme 2 visual)
# ─────────────────────────────────────────────────────────────────────────────

def generate_plots(ts_worms, output_path):
    worm_ids = sorted(ts_worms.keys())
    n = len(worm_ids)
    fig, axes = plt.subplots(n, 1, figsize=(14, 4 * n), squeeze=False)
    fig.patch.set_facecolor("#111827")

    for row_i, wid in enumerate(worm_ids):
        ax = axes[row_i][0]
        ax.set_facecolor("#1f2937")
        frames = ts_worms[wid]["frame"]
        head   = ts_worms[wid]["head"]
        tail   = ts_worms[wid]["tail"]

        ax.plot(frames, head, color="#ef4444", linewidth=1.2, label="Head")
        ax.plot(frames, tail, color="#3b82f6", linewidth=1.2, label="Tail")

        ax.set_title(f"Worm {wid} — Motion Over Time", color="#e5e7eb", fontsize=11)
        ax.set_xlabel("Frame", color="#9ca3af"); ax.set_ylabel("px/frame", color="#9ca3af")
        ax.tick_params(colors="#9ca3af")
        for spine in ax.spines.values(): spine.set_edgecolor("#374151")
        ax.grid(color="#374151", linestyle="--", linewidth=0.5)
        ax.legend(facecolor="#374151", edgecolor="#4b5563", labelcolor="#e5e7eb")

    plt.tight_layout(pad=2)
    plt.savefig(output_path, dpi=120, facecolor=fig.get_facecolor())
    plt.close()
    print(f"\n  Plot saved: {output_path}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Validate worm tracker CSV exports")
    parser.add_argument("output_dir", help="Job output subfolder (contains _keypoints.npz etc.)")
    parser.add_argument("--pre-flip", metavar="DIR",
                        help="Path to data folder from BEFORE the flip (contains *_timeseries.csv)")
    parser.add_argument("--flipped-worm", metavar="ID",
                        help="Worm ID that was flipped (required with --pre-flip)")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    if not out_dir.exists():
        print(f"ERROR: output_dir not found: {out_dir}"); sys.exit(1)

    # Locate files
    def find(pattern):
        hits = list(out_dir.glob(pattern))
        return hits[0] if hits else None

    stats_path    = find("*_motion_stats.json")
    summary_path  = find("*_summary.csv")
    ts_path       = find("*_timeseries.csv")
    npz_path      = find("*_keypoints.npz")

    missing = [n for n, p in [("motion_stats.json", stats_path),
                               ("summary.csv",       summary_path),
                               ("timeseries.csv",    ts_path),
                               ("keypoints.npz",     npz_path)] if p is None]
    if missing:
        print(f"ERROR: missing files: {missing}"); sys.exit(1)

    print(f"\nValidating: {out_dir.name}")
    print(f"  JSON  : {stats_path.name}")
    print(f"  Summary CSV : {summary_path.name}")
    print(f"  Timeseries CSV : {ts_path.name}")
    print(f"  NPZ   : {npz_path.name}")

    with open(stats_path) as f:
        stats = json.load(f)

    summary_rows = read_summary_csv(summary_path)
    agg_block    = read_aggregate_block(summary_path)
    ts_worms     = read_timeseries_csv(ts_path)

    validate_summary_vs_json(stats, summary_rows, agg_block)
    validate_timeseries_vs_json(stats, ts_worms)
    validate_npz_recompute(npz_path, ts_worms, summary_rows)

    # Scheme 4
    if args.pre_flip:
        if not args.flipped_worm:
            print("\nERROR: --pre-flip requires --flipped-worm"); sys.exit(1)
        validate_flip(args.pre_flip, ts_worms, summary_rows, args.flipped_worm)
    else:
        print("\n[Scheme 4] H/T flip validation — skipped (no --pre-flip provided)")
        print("           To validate: flip a worm in the UI, export CSV again, then run:")
        print("           python validate_csv.py <post_flip_output_dir> \\")
        print("               --pre-flip <pre_flip_data_dir> --flipped-worm <id>")

    # Generate plots
    plot_path = out_dir / "validation_timeseries_plot.png"
    generate_plots(ts_worms, str(plot_path))

    # Final summary
    print()
    if errors:
        print(f"\033[91m{'─'*60}")
        print(f"RESULT: {len(errors)} FAILURE(S):")
        for e in errors:
            print(f"  • {e}")
        print(f"{'─'*60}\033[0m")
        sys.exit(1)
    else:
        print(f"\033[92m{'─'*60}")
        print(f"RESULT: ALL CHECKS PASSED")
        print(f"{'─'*60}\033[0m")


if __name__ == "__main__":
    main()
