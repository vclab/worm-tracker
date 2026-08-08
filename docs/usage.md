# Using the App

1. Open the app in your browser.
2. Select the tracking pipeline: **Classical** (threshold-based, no training data required) or **YOLO** (deep learning, better on translucent or overlapping specimens).
3. Adjust tracking parameters if needed (see below).
4. Select one or more video files and click **Add to queue**.
5. Jobs process one at a time; the **Job History** panel shows live progress.
6. Click a completed job to load its results:
   - **Before/after comparison slider**: drag to reveal original vs. tracked video.
   - **Download All (ZIP)**: tracked video, original, keypoints (`.npz`), metadata (`.yaml`), motion stats (`.json`).
   - **Export CSV**: per-worm summary and per-frame timeseries.
   - **Head/Tail Correction**: flip head/tail for individual worms, then re-download.
   - **Motion Analysis**: per-worm heatmap and timeline (overall, head, mid-body, tail).
7. Use **Re-run with new parameters** to reprocess the same file with different settings.
8. Use **Run on another file** to reset and process a new video.

## Tracking parameters

| Parameter | Default | Description |
|---|---|---|
| Keypoints per worm | 15 | Skeleton sample points along each worm |
| Area threshold | 50 | Minimum pixel area to consider a blob a worm |
| Max age | 35 | Frames to keep tracking a worm after it disappears |
| Persistence | 50 | Minimum frames tracked to include a worm in output |

## Quitting a packaged app

Close the browser tab and the app shuts down automatically about 20 seconds later (a heartbeat watchdog). If a job is still processing, the server waits for it to finish first. Double-clicking the app while it is already running brings the existing browser tab forward instead of starting a second copy.

## Export and download options

Results can be exported in a few places. The two **Metrics** page exports produce analysis-ready ZIPs; the **History** page offers per-job downloads of the raw tracking outputs.

**Metrics page, Condition comparison export.** The **Export** button under *Condition comparison* downloads a ZIP for all the groups you've built:
- **Grouped comparison chart** as **PNG** and **SVG**.
- **`group_summary.csv`**: one row per group × pipeline, with worm count (`n`) and mean + standard deviation for head, mid-body, and tail motion.
- **`per_worm.csv`**: the raw per-worm rows behind those averages (group, video, pipeline, worm ID, and head/mid-body/tail/overall motion).

**Metrics page, Single video analysis export.** The **Export** button under *Single video analysis* downloads a ZIP for the selected video: the **drill-down chart** (PNG + SVG) plus that video's **summary CSV**, **timeseries CSV**, **`motion_stats.json`**, **metadata YAML**, and **`*_keypoints.npz`**, the complete, reproducible package for one video.

**History page, per-job downloads.** Each job row has its own actions:
- **View**: open the tracked result in the app.
- **Video**: download the tracked H.264 MP4.
- **ZIP**: the job's **package ZIP** (`{output_name}.zip`):

  | File | Description |
  | --- | --- |
  | `*_original.*` | Copy of the originally uploaded video |
  | `*_tracked.mp4` | H.264 video annotated with colored skeleton keypoints and worm IDs |
  | `*.yaml` | Metadata: git version, timestamp, parameters, frame count |
  | `*_keypoints.npz` | Per-worm skeleton keypoints over time (`[y, x]` per keypoint per frame; edge-touching worms under a `partial_` key prefix) |
  | `*_motion_stats.json` | Per-worm motion values (overall, head, mid-body, tail) and aggregate stats |

  The package ZIP does **not** include CSVs; those are in the separate `_data.zip`.
- **CSV**: the job's **data ZIP** (`{output_name}_data.zip`):

  | File | Description |
  | --- | --- |
  | `*_summary.csv` | One row per worm: mean motion values (overall, head, mid-body, tail) |
  | `*_timeseries.csv` | One row per frame window: per-worm head/mid-body/tail motion over time |
- **Delete**: remove the job and its outputs.

## Where your data lives

Everything the app writes lives in two places, both of which survive app uninstall and upgrades.

**Outputs directory.** Default location is `Documents/ParaTracker/` on all OSes. Change it via **Settings (⚙)** in the UI; the change takes effect after an app restart. This folder holds:

- `jobs.db` (SQLite): the job history the UI shows.
- `<job_id>/<timestamp>_<output_name>/`: one folder per job, containing the tracked video, keypoints, motion stats, metadata, and CSV/ZIP exports.
- `uploads/`: transient staging for in-flight uploads.

The outputs folder is self-contained and portable. Moving it to another drive, or copying it to another machine, takes your entire job history and all results with it.

**Config file.** Stores the `outputs_dir` path and the optional custom `model_path`:

| Platform | Path |
|---|---|
| macOS   | `~/Library/Application Support/ParaTracker/config.json` |
| Windows | `%APPDATA%/ParaTracker/config.json` |
| Linux   | `~/.config/ParaTracker/config.json` |

Uninstalling the app removes the app itself but leaves the outputs directory and the config file untouched by design, so upgrading (or reinstalling after uninstall) picks up right where you left off. See [Troubleshooting & Uninstalling](troubleshooting.md#uninstalling) for how to remove them when you actually want a clean slate.

## Keypoints NPZ format

```python
import numpy as np

with np.load("*_keypoints.npz") as npz:
    print(list(npz.keys()))  # e.g. ['0', '1', 'partial_2', 'partial_3']
    arr = npz["0"]           # shape: (num_keypoints, num_frames, 2)
    y, x = arr[0, 0]         # [y, x] position of keypoint 0 at frame 0
```

**Array shape:** `(num_keypoints, num_frames, 2)`. Axis 0 is keypoints along the skeleton (index 0 = head, index -1 = tail), axis 1 is frames, axis 2 is `[y, x]` pixel coordinates.

| Key pattern | Description |
|---|---|
| `"0"`, `"1"`, `"2"`, ... | Fully retained worms: tracked for ≥ `persistence` frames and never touched a frame edge |
| `"partial_0"`, `"partial_2"`, ... | Partial worms: touched a frame edge, excluded from motion analysis |

**Head/tail orientation:** keypoint 0 = head (wider end), keypoint -1 = tail (narrower end). Correctable via the Head/Tail Correction tool.

---

# CLI Usage (no UI)

Two separate module entry points; there is no unified `--pipeline` flag.

**Classical pipeline** (no model needed):

```bash
python -m app.worm_tracker input.mov output_dir \
    --keypoints 15 --min-area 50 --max-age 35 --persistence 50
```

**YOLO pipeline** (needs a weights file, e.g. from `make weights`):

```bash
python -m app.dl_worm_tracker input.mov output_dir \
    --model weights/worm_yolov8seg-<sha>.pt \
    --keypoints 15 --min-area 50 --max-age 35 --persistence 50 \
    --conf-threshold 0.25
```

Both write to `output_dir/{timestamp}_{output_name}/` and produce the same output-file layout as the web UI.
