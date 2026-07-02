"""Cross-video aggregation over completed jobs.

Reads jobs.db (read-only), loads each job's *_summary.csv, filters to
row_type='worm' rows, and builds two tables:

  per_worm  — one row per worm: job_id, filename, pipeline, worm_id,
              head, midbody, tail, overall
  per_video — one row per (filename, pipeline) pair: filename, pipeline,
              job_id, worm_count, head, midbody, tail, overall (averages)

Deduplication: most-recent job per (original_filename, pipeline) pair,
so the same video processed by both pipelines produces two rows rather
than one.
"""

import json
import logging
from pathlib import Path

import pandas as pd

from app.config import load_config

logger = logging.getLogger(__name__)


def _outputs_and_db() -> tuple[Path, Path]:
    cfg = load_config()
    outputs = Path(cfg["outputs_dir"])
    return outputs, outputs / "jobs.db"


def build_tables() -> tuple[list[dict], list[dict]]:
    """Return ``(per_worm_rows, per_video_rows)`` from all completed jobs.

    Skips jobs whose CSV is missing or unreadable and logs a warning for each.
    Returns empty lists when the database does not exist.
    """
    import sqlite3

    outputs, db_path = _outputs_and_db()

    if not db_path.exists():
        logger.warning("jobs.db not found at %s — returning empty tables", db_path)
        return [], []

    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        all_done = con.execute(
            "SELECT job_id, original_filename, output_subfolder, params_json, "
            "       created_at, created_at_unix "
            "FROM   jobs "
            "WHERE  status = 'done' "
            "ORDER  BY created_at_unix DESC"
        ).fetchall()
    finally:
        con.close()

    # Dedup: keep most-recent job per (filename, pipeline) pair
    seen: dict[tuple[str, str], dict] = {}
    for r in all_done:
        d = dict(r)
        params = json.loads(d.get("params_json") or "{}")
        d["pipeline"] = params.get("pipeline", "classical")
        fname = d["original_filename"] or ""
        key = (fname, d["pipeline"])
        if key not in seen:
            seen[key] = d

    jobs = list(seen.values())

    records: list[dict] = []
    for j in jobs:
        job_id   = j["job_id"]
        filename = j["original_filename"] or "unknown"
        pipeline = j["pipeline"]
        subfolder = j["output_subfolder"]

        if not subfolder:
            logger.warning("Aggregate: job %s (%s) has no output_subfolder — skipped", job_id[:8], filename)
            continue

        subdir = outputs / job_id / subfolder
        csvs = list(subdir.glob("*_summary.csv"))
        if not csvs:
            logger.warning("Aggregate: no *_summary.csv in %s — skipped", subdir)
            continue

        try:
            df_raw = pd.read_csv(csvs[0])
            worm_rows = df_raw[df_raw["row_type"] == "worm"]
            if worm_rows.empty:
                logger.warning("Aggregate: job %s has no row_type='worm' rows — skipped", job_id[:8])
                continue
            for _, row in worm_rows.iterrows():
                records.append({
                    "job_id"  : job_id,
                    "filename": filename,
                    "pipeline": pipeline,
                    "worm_id" : row["worm_id"],
                    "head"    : float(row["head_motion"]),
                    "midbody" : float(row["mid_motion"]),
                    "tail"    : float(row["tail_motion"]),
                    "overall" : float(row["overall_motion"]),
                })
        except Exception as exc:
            logger.warning("Aggregate: could not read CSV for job %s: %s — skipped", job_id[:8], exc)

    if not records:
        return [], []

    pw = pd.DataFrame(records)

    # Per-video: group by (filename, pipeline, job_id).
    # After dedup there is exactly one job_id per (filename, pipeline) pair,
    # so including job_id in the groupby key does not split any group further.
    pv = (
        pw
        .groupby(["filename", "pipeline", "job_id"], as_index=False)
        .agg(
            worm_count=("worm_id", "count"),
            head      =("head",    "mean"),
            midbody   =("midbody", "mean"),
            tail      =("tail",    "mean"),
            overall   =("overall", "mean"),
        )
    )

    per_worm  = records
    per_video = pv.to_dict(orient="records")
    return per_worm, per_video


if __name__ == "__main__":
    import sys

    pw, pv = build_tables()
    if not pw:
        print("No data found — make sure at least one job is completed.", file=sys.stderr)
        sys.exit(1)

    pw_df = pd.DataFrame(pw)
    pv_df = pd.DataFrame(pv)

    print("=== combined_per_worm ===")
    print(pw_df.to_csv(index=False))

    print("=== combined_per_video ===")
    print(pv_df.to_csv(index=False))
