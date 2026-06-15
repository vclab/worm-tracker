#!/usr/bin/env python3
"""
chart_comparison.py — Publication-quality PNG charts from compare_pipelines.py output.

Reads the most recent comparison_metrics_*.json in the results directory and
generates three chart files in the output directory.

Usage:
    python chart_comparison.py                        # auto-detects results dir
    python chart_comparison.py pipeline_comparison_results/
    python chart_comparison.py results/ --output charts/
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import textwrap
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.ticker as ticker

# ── Brand colors (used consistently across ALL charts) ─────────────────────────
CLASSICAL_COLOR = "#D4622A"   # muted terracotta-orange
YOLO_COLOR      = "#2778B5"   # steel blue

# ── Typography ──────────────────────────────────────────────────────────────────
TITLE_SIZE  = 14
LABEL_SIZE  = 12
TICK_SIZE   = 10
LEGEND_SIZE = 11
BAR_LABEL_SIZE = 9

DPI = 160


# ── Shared helpers ──────────────────────────────────────────────────────────────

def _clean_axes(ax: plt.Axes) -> None:
    """Remove chartjunk; keep only a subtle y-grid."""
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#BBBBBB")
    ax.spines["bottom"].set_color("#BBBBBB")
    ax.yaxis.grid(True, linestyle="--", linewidth=0.55, color="#E2E2E2", zorder=0)
    ax.set_axisbelow(True)
    ax.tick_params(axis="both", labelsize=TICK_SIZE, colors="#444444")
    ax.tick_params(axis="x", length=0)


def _bar_label(ax: plt.Axes, bar: plt.Rectangle, value: float) -> None:
    """Place a value label 4 pts above the top of a bar."""
    text = f"{value:.1f}" if value % 1 != 0 else str(int(value))
    ax.annotate(
        text,
        xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
        xytext=(0, 4),
        textcoords="offset points",
        ha="center", va="bottom",
        fontsize=BAR_LABEL_SIZE, color="#333333", fontweight="bold",
    )


def _video_stem(video_path: str) -> str:
    return Path(video_path).stem


def _load_json(results_dir: Path) -> list[dict] | None:
    """
    Merge all comparison_metrics_*.json files found in results_dir.

    Each file may contain one or more video results. Results are de-duplicated
    by video path so that re-runs of the same video don't inflate the dataset
    (most-recent result for each video path wins).
    """
    candidates = sorted(results_dir.glob("comparison_metrics_*.json"))
    plain = results_dir / "comparison_metrics.json"
    if plain.exists() and plain not in candidates:
        candidates.append(plain)

    if not candidates:
        print(
            f"ERROR: No comparison_metrics*.json found in {results_dir}.\n"
            "Run compare_pipelines.py first.",
            file=sys.stderr,
        )
        return None

    # Merge, keeping the latest entry per video path (files are sorted ascending,
    # so later files overwrite earlier ones in the seen dict).
    seen: dict[str, dict] = {}
    for path in candidates:
        print(f"Reading: {path}")
        try:
            with open(path) as f:
                entries = json.load(f)
            if isinstance(entries, list):
                for entry in entries:
                    key = entry.get("video", str(path))
                    seen[key] = entry
            else:
                # Single-entry dict without a wrapping list (shouldn't happen, but be safe)
                key = entries.get("video", str(path))
                seen[key] = entries
        except Exception as exc:
            print(f"  WARNING: Could not parse {path}: {exc}", file=sys.stderr)

    if not seen:
        print("ERROR: No valid entries found across all JSON files.", file=sys.stderr)
        return None

    merged = list(seen.values())
    print(f"Loaded {len(merged)} video result(s) from {len(candidates)} file(s).")
    return merged


# ── Chart 1 ─────────────────────────────────────────────────────────────────────

def chart_detection_over_time(result: dict, output_dir: Path) -> None:
    """
    Line chart: worms detected per frame, Classical vs YOLO, for one video.
    Saved as detection_over_time_<stem>.png.
    """
    vname = _video_stem(result.get("video", "unknown"))
    c_counts = result.get("classical", {}).get("worms_detected_per_frame")
    y_counts  = result.get("yolo",      {}).get("worms_detected_per_frame")

    if not c_counts and not y_counts:
        print(f"  [skip] {vname}: no per-frame data available")
        return

    fig, ax = plt.subplots(figsize=(11, 4))

    if c_counts:
        ax.plot(
            np.arange(len(c_counts)), c_counts,
            color=CLASSICAL_COLOR, linewidth=0.9, alpha=0.80,
            label="Classical", zorder=3,
        )
    if y_counts:
        ax.plot(
            np.arange(len(y_counts)), y_counts,
            color=YOLO_COLOR, linewidth=0.9, alpha=0.80,
            label="YOLO", zorder=4,
        )

    ax.set_title(
        f"Worm Detections per Frame — {vname}",
        fontsize=TITLE_SIZE, fontweight="bold", pad=10,
    )
    ax.set_xlabel("Frame", fontsize=LABEL_SIZE)
    ax.set_ylabel("Worms detected", fontsize=LABEL_SIZE)
    ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: f"{int(v):,}"))
    ax.legend(fontsize=LEGEND_SIZE, framealpha=0.85, edgecolor="#CCCCCC")
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    _clean_axes(ax)

    fig.tight_layout()
    out = output_dir / f"detection_over_time_{vname}.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {out}")


# ── Chart 2 ─────────────────────────────────────────────────────────────────────

_SUMMARY_SPECS = [
    ("total_unique_ids",              "Unique Track IDs",    "count"),
    ("mean_track_length",             "Mean Track Length",   "frames"),
    ("max_worms_in_any_single_frame", "Max Worms per Frame", "count"),
]


def chart_summary_comparison(all_results: list[dict], output_dir: Path) -> None:
    """
    1×3 subplot: each panel shows Classical vs YOLO for one scalar metric.
    Values are averaged across all videos; individual video values shown as points.
    Saved as summary_comparison.png.
    """
    fig, axes = plt.subplots(1, len(_SUMMARY_SPECS), figsize=(12, 5))
    fig.suptitle(
        "Pipeline Comparison — Scalar Metrics (mean across videos)",
        fontsize=TITLE_SIZE, fontweight="bold", y=1.01,
    )

    bar_x = np.array([0.0, 1.0])
    bar_w = 0.50

    for ax, (metric_key, metric_label, unit) in zip(axes, _SUMMARY_SPECS):
        # Collect per-video values for each pipeline
        c_vals = [
            float(r["classical"][metric_key])
            for r in all_results
            if "classical" in r and metric_key in r["classical"] and r["classical"][metric_key] is not None
        ]
        y_vals = [
            float(r["yolo"][metric_key])
            for r in all_results
            if "yolo" in r and metric_key in r["yolo"] and r["yolo"][metric_key] is not None
        ]

        means = [
            np.mean(c_vals) if c_vals else 0.0,
            np.mean(y_vals) if y_vals else 0.0,
        ]
        stds = [
            np.std(c_vals)  if len(c_vals) > 1 else 0.0,
            np.std(y_vals)  if len(y_vals) > 1 else 0.0,
        ]
        point_sets = [c_vals, y_vals]

        bars = ax.bar(
            bar_x, means, width=bar_w,
            color=[CLASSICAL_COLOR, YOLO_COLOR],
            zorder=3, alpha=0.88,
        )

        # Error bars (only meaningful with > 1 video)
        if any(s > 0 for s in stds):
            ax.errorbar(
                bar_x, means, yerr=stds,
                fmt="none", color="#555555",
                linewidth=1.3, capsize=6, zorder=4,
            )

        # Individual video values as white-filled scatter
        for bx, pts in zip(bar_x, point_sets):
            if pts:
                ax.scatter(
                    [bx] * len(pts), pts,
                    color="white", edgecolors="#333333",
                    s=28, linewidths=1.2, zorder=5,
                )

        # Value labels above bars
        for bar, mean in zip(bars, means):
            _bar_label(ax, bar, mean)

        ax.set_xticks(bar_x)
        ax.set_xticklabels(["Classical", "YOLO"], fontsize=LABEL_SIZE)
        ax.set_ylabel(unit, fontsize=LABEL_SIZE - 1)
        ax.set_title(metric_label, fontsize=LABEL_SIZE, fontweight="semibold", pad=8)
        ax.set_xlim(-0.55, 1.55)
        ax.set_ylim(bottom=0)
        _clean_axes(ax)

    fig.tight_layout()
    out = output_dir / "summary_comparison.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {out}")


# ── Chart 3 ─────────────────────────────────────────────────────────────────────

def chart_per_video_consistency(all_results: list[dict], output_dir: Path) -> None:
    """
    Grouped bar chart: max_worms_in_any_single_frame per video, Classical vs YOLO.
    Shows the over-counting pattern holds across all videos.
    Saved as per_video_consistency.png.
    """
    metric = "max_worms_in_any_single_frame"

    video_names: list[str] = []
    c_vals: list[float | None] = []
    y_vals: list[float | None] = []

    for r in all_results:
        name = _video_stem(r.get("video", "unknown"))
        cv   = r.get("classical", {}).get(metric)
        yv   = r.get("yolo",      {}).get(metric)
        if cv is None and yv is None:
            continue
        video_names.append(name)
        c_vals.append(float(cv) if cv is not None else None)
        y_vals.append(float(yv) if yv is not None else None)

    if not video_names:
        print("  [skip] per_video_consistency: no max_worms data found")
        return

    n     = len(video_names)
    x     = np.arange(n, dtype=float)
    bar_w = 0.30
    fig_w = max(7.0, n * 2.6)
    fig, ax = plt.subplots(figsize=(fig_w, 5))

    c_bars: list[plt.Rectangle] = []
    y_bars: list[plt.Rectangle] = []

    for i, (cv, yv) in enumerate(zip(c_vals, y_vals)):
        if cv is not None:
            b = ax.bar(
                x[i] - bar_w / 2, cv, width=bar_w,
                color=CLASSICAL_COLOR, zorder=3, alpha=0.88,
                label="Classical" if i == 0 else "_nolegend_",
            )
            c_bars.append(b[0])
        if yv is not None:
            b = ax.bar(
                x[i] + bar_w / 2, yv, width=bar_w,
                color=YOLO_COLOR, zorder=3, alpha=0.88,
                label="YOLO" if i == 0 else "_nolegend_",
            )
            y_bars.append(b[0])

    # Labels after all bars are drawn (ylim is now set by data)
    for bar in c_bars:
        _bar_label(ax, bar, bar.get_height())
    for bar in y_bars:
        _bar_label(ax, bar, bar.get_height())

    ax.set_xticks(x)
    wrapped = [textwrap.fill(v, width=16) for v in video_names]
    ax.set_xticklabels(wrapped, fontsize=LABEL_SIZE, ha="center")
    ax.set_ylabel("Max worms in any single frame", fontsize=LABEL_SIZE)
    ax.set_title(
        "Peak Detection Count per Video — Classical vs YOLO",
        fontsize=TITLE_SIZE, fontweight="bold", pad=12,
    )

    legend_handles = [
        mpatches.Patch(facecolor=CLASSICAL_COLOR, label="Classical"),
        mpatches.Patch(facecolor=YOLO_COLOR,      label="YOLO"),
    ]
    ax.legend(handles=legend_handles, fontsize=LEGEND_SIZE, framealpha=0.85, edgecolor="#CCCCCC")
    ax.set_xlim(-0.6, n - 0.4)
    ax.set_ylim(bottom=0)
    _clean_axes(ax)

    fig.tight_layout()
    out = output_dir / "per_video_consistency.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {out}")


# ── CLI ──────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "results_dir",
        nargs="?",
        default=None,
        help="Directory containing compare_pipelines.py output "
             "(default: pipeline_comparison_results/ or results/, whichever exists first).",
    )
    parser.add_argument(
        "--output", "-o",
        default="charts",
        metavar="DIR",
        help="Output directory for PNG files (default: charts/).",
    )
    args = parser.parse_args()

    if args.results_dir:
        results_dir = Path(args.results_dir)
    else:
        for candidate in ("pipeline_comparison_results", "results"):
            if Path(candidate).is_dir():
                results_dir = Path(candidate)
                break
        else:
            print(
                "ERROR: Could not find a results directory.\n"
                "Pass the path as the first argument, or run compare_pipelines.py first.",
                file=sys.stderr,
            )
            sys.exit(1)

    if not results_dir.is_dir():
        print(f"ERROR: Directory not found: {results_dir}", file=sys.stderr)
        sys.exit(1)

    all_results = _load_json(results_dir)
    if not all_results:
        sys.exit(1)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nGenerating charts -> {output_dir}/\n")

    errors: list[str] = []

    for result in all_results:
        vname = _video_stem(result.get("video", "unknown"))
        try:
            chart_detection_over_time(result, output_dir)
        except Exception as exc:
            msg = f"detection chart [{vname}]: {exc}"
            print(f"  WARNING: {msg}", file=sys.stderr)
            errors.append(msg)

    try:
        chart_summary_comparison(all_results, output_dir)
    except Exception as exc:
        msg = f"summary_comparison: {exc}"
        print(f"  WARNING: {msg}", file=sys.stderr)
        errors.append(msg)

    try:
        chart_per_video_consistency(all_results, output_dir)
    except Exception as exc:
        msg = f"per_video_consistency: {exc}"
        print(f"  WARNING: {msg}", file=sys.stderr)
        errors.append(msg)

    print(f"\nDone: {output_dir}/")
    if errors:
        print(f"  {len(errors)} chart(s) skipped due to errors (see warnings above).")


if __name__ == "__main__":
    main()
