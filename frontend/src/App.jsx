import { useRef, useState, useEffect, useCallback } from "react";
import MotionCharts from "./MotionCharts";
import JobHistory from "./JobHistory";

function App() {
  // Results
  const [processedUrl, setProcessedUrl] = useState(null); // MP4 (H.264) to view
  const [originalUrl, setOriginalUrl] = useState(null); // Blob URL for original video
  const [packageUrl, setPackageUrl] = useState(null); // ZIP with video+yaml+npz
  const [dataCsvUrl, setDataCsvUrl] = useState(null); // CSV data ZIP for export
  const [outputFolderName, setOutputFolderName] = useState(""); // e.g., "20260224_181803_tracking01"
  const [motionStats, setMotionStats] = useState(null); // Motion analysis data

  // UX
  const [loading, setLoading] = useState(false);
  const [fileName, setFileName] = useState("");
  const [historyKey, setHistoryKey] = useState(0);

  // Progress tracking
  const [progress, setProgress] = useState({ stage: "", current: 0, total: 0 });
  const [currentJobId, setCurrentJobId] = useState(null);

  // Video comparison slider
  const [sliderPos, setSliderPos] = useState(50); // Percentage position of divider
  const [isDragging, setIsDragging] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const compareContainerRef = useRef(null);
  const originalVideoRef = useRef(null);
  const trackedVideoRef = useRef(null);

  // Parameters
  const [keypoints, setKeypoints] = useState(15);
  const [area, setArea] = useState(50);
  const [maxAge, setMaxAge] = useState(35);
  const [persistence, setPersistence] = useState(50);
  const [outName, setOutName] = useState("");

  // Ref to clear the file input on reset
  const fileInputRef = useRef(null);
  const abortControllerRef = useRef(null);

  // Sync video playback between original and tracked
  const syncVideos = useCallback((source, target) => {
    if (!source || !target) return;
    if (Math.abs(source.currentTime - target.currentTime) > 0.1) {
      target.currentTime = source.currentTime;
    }
  }, []);

  // Handle slider drag
  const handleSliderMove = useCallback((clientX) => {
    if (!compareContainerRef.current) return;
    const rect = compareContainerRef.current.getBoundingClientRect();
    const x = clientX - rect.left;
    const percent = Math.max(0, Math.min(100, (x / rect.width) * 100));
    setSliderPos(percent);
  }, []);

  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e) => handleSliderMove(e.clientX);
    const handleTouchMove = (e) => handleSliderMove(e.touches[0].clientX);
    const handleEnd = () => setIsDragging(false);

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("touchmove", handleTouchMove);
    window.addEventListener("mouseup", handleEnd);
    window.addEventListener("touchend", handleEnd);

    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("touchmove", handleTouchMove);
      window.removeEventListener("mouseup", handleEnd);
      window.removeEventListener("touchend", handleEnd);
    };
  }, [isDragging, handleSliderMove]);

  const onPickFile = (e) => {
    const f = e.target.files?.[0];
    if (f) setFileName(f.name);
  };

  const handleFileChange = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    // Create blob URL for original video comparison
    const blobUrl = URL.createObjectURL(file);
    setOriginalUrl(blobUrl);

    setLoading(true);
    setProcessedUrl(null);
    setPackageUrl(null);
    setProgress({ stage: "uploading", current: 0, total: 1 });
    window.processingStartTime = Date.now();

    const formData = new FormData();
    formData.append("file", file);
    formData.append("keypoints_per_worm", keypoints);
    formData.append("area_threshold", area);
    formData.append("max_age", maxAge);
    formData.append("persistence", persistence);
    formData.append("output_name", outName);

    // Create abort controller for cancellation
    abortControllerRef.current = new AbortController();

    try {
      const res = await fetch("http://127.0.0.1:8000/upload", {
        method: "POST",
        body: formData,
        signal: abortControllerRef.current.signal,
      });

      if (!res.ok) {
        const errText = await res.text();
        throw new Error(errText || `Server error ${res.status}`);
      }

      // Read SSE stream
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const data = JSON.parse(line.slice(6));
            setProgress(data);

            // Capture job_id when processing starts
            if (data.stage === "started" && data.job_id) {
              setCurrentJobId(data.job_id);
            }

            // Reset timer when processing starts
            if (data.stage === "processing" && data.current === 0) {
              window.processingStartTime = Date.now();
            }

            if (data.stage === "done") {
              const videoLink = data.video
                ? "http://127.0.0.1:8000" + data.video
                : null;
              const zipLink = data.package
                ? "http://127.0.0.1:8000" + data.package
                : null;
              const csvLink = data.data_csv
                ? "http://127.0.0.1:8000" + data.data_csv
                : null;
              // Extract folder name from package URL (e.g., "20260224_181803_tracking01")
              if (data.package) {
                const parts = data.package.split("/");
                const zipName = parts[parts.length - 1];
                setOutputFolderName(zipName.replace(".zip", ""));
              }
              // Fetch motion stats
              if (data.motion_stats) {
                fetch("http://127.0.0.1:8000" + data.motion_stats)
                  .then((r) => r.json())
                  .then((stats) => setMotionStats(stats))
                  .catch(() => setMotionStats(null));
              }
              setProcessedUrl(videoLink);
              setPackageUrl(zipLink);
              setDataCsvUrl(csvLink);
              setCurrentJobId(null);
              setLoading(false);
              setHistoryKey((k) => k + 1);
            } else if (data.stage === "error") {
              throw new Error(data.message);
            }
          }
        }
      }
    } catch (err) {
      if (err.name === "AbortError") {
        // User cancelled - don't show error
        setProgress({ stage: "", current: 0, total: 0 });
      } else {
        alert("Error processing video: " + err.message);
      }
      setLoading(false);
    } finally {
      abortControllerRef.current = null;
    }
  };

  // Cancel ongoing processing
  const cancelProcessing = async () => {
    // Abort the fetch request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    // Call backend to cancel job and clean up files
    if (currentJobId) {
      try {
        await fetch(`http://127.0.0.1:8000/cancel/${currentJobId}`, {
          method: "POST",
        });
      } catch (e) {
        // Ignore errors - job might already be done
      }
    }

    // Revoke blob URL since we're cancelling
    if (originalUrl) URL.revokeObjectURL(originalUrl);
    setOriginalUrl(null);
    setCurrentJobId(null);
    setLoading(false);
    setFileName("");
    setProgress({ stage: "", current: 0, total: 0 });
    setHistoryKey((k) => k + 1);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  // Reset UI to run on another file (keeps parameter values)
  const resetForAnother = () => {
    // Revoke blob URL to free memory
    if (originalUrl) URL.revokeObjectURL(originalUrl);
    setOriginalUrl(null);
    setProcessedUrl(null);
    setPackageUrl(null);
    setDataCsvUrl(null);
    setOutputFolderName("");
    setMotionStats(null);
    setCurrentJobId(null);
    setLoading(false);
    setFileName("");
    setSliderPos(50);
    setIsPlaying(false);
    if (fileInputRef.current) fileInputRef.current.value = "";
    // Optionally scroll to top for convenience
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  return (
    <div className="container">
      <main className="card">
        {/* Header */}
        <div className="header">
          <div className="header-left">
            <div className="title-row">
              <h1 className="title">WORM TRACKER</h1>
              <span className="version">v1.0</span>
            </div>
            <p className="subtitle">C. elegans motion analysis</p>
          </div>
          <div className="header-right">
            {processedUrl ? (
              <span className="badge">Ready</span>
            ) : loading ? (
              <span className="badge badge-processing">Processing</span>
            ) : (
              <span className="status-idle">Ready to analyze</span>
            )}
          </div>
        </div>

        {/* Parameters */}
        <section className="form">
          <div className="field">
            <label className="label">Keypoints per worm</label>
            <input
              className="input"
              type="number"
              value={keypoints}
              onChange={(e) => setKeypoints(e.target.value)}
              min={1}
            />
          </div>
          <div className="field">
            <label className="label">Area threshold</label>
            <input
              className="input"
              type="number"
              value={area}
              onChange={(e) => setArea(e.target.value)}
              min={0}
            />
          </div>
          <div className="field">
            <label className="label">Max age</label>
            <input
              className="input"
              type="number"
              value={maxAge}
              onChange={(e) => setMaxAge(e.target.value)}
              min={0}
            />
          </div>
          <div className="field">
            <label className="label">Persistence</label>
            <input
              className="input"
              type="number"
              value={persistence}
              onChange={(e) => setPersistence(e.target.value)}
              min={1}
            />
          </div>
          <div className="field">
            <label className="label">Output name</label>
            <input
              className="input"
              type="text"
              value={outName}
              onChange={(e) => setOutName(e.target.value)}
              placeholder="tracking01"
            />
          </div>
        </section>

        {/* File input (pretty) */}
        {!processedUrl && (
          <section>
            <div className="file-wrap">
              <label className="file-btn" htmlFor="file">
                Select video
              </label>
              <input
                id="file"
                ref={fileInputRef}
                type="file"
                accept="video/*"
                onChange={(e) => {
                  onPickFile(e);
                  handleFileChange(e);
                }}
              />
              <span className="file-name">
                {fileName || "MP4 recommended (H.264 plays fastest)"}
              </span>
            </div>

            {/* Progress */}
            {loading && (
              <div className="progress-container">
                <div className="progress-header">
                  <span className="progress-stage">
                    {progress.stage === "uploading" && "Uploading..."}
                    {progress.stage === "processing" && "Analyzing frames..."}
                    {progress.stage === "generating" && "Generating video..."}
                    {progress.stage === "finalizing" && "Finalizing..."}
                    {progress.stage === "complete" && "Almost done..."}
                  </span>
                  {progress.total > 0 && progress.stage !== "finalizing" && (
                    <span className="progress-percent">
                      {Math.round((progress.current / progress.total) * 100)}%
                    </span>
                  )}
                </div>
                <div className="progress">
                  <div
                    className="progress__bar"
                    style={{
                      width: progress.total > 0
                        ? `${(progress.current / progress.total) * 100}%`
                        : "100%",
                      animation: progress.total > 0 ? "none" : undefined,
                    }}
                  />
                </div>
                {progress.total > 0 && progress.stage !== "finalizing" && (
                  <div className="progress-details">
                    Frame {progress.current} of {progress.total}
                    {progress.current > 0 && progress.stage === "processing" && (
                      <span className="progress-eta">
                        {" "}
                        — ~{Math.round(((progress.total - progress.current) / progress.current) * (Date.now() - window.processingStartTime) / 1000)}s remaining
                      </span>
                    )}
                  </div>
                )}
                <button className="btn btn-cancel" onClick={cancelProcessing}>
                  Cancel
                </button>
              </div>
            )}
          </section>
        )}

        {/* Player + actions */}
        {processedUrl && !loading && (
          <>
            {/* Video comparison slider */}
            <div
              className="video-compare"
              ref={compareContainerRef}
              onMouseDown={(e) => {
                if (e.target.closest('.compare-slider')) {
                  setIsDragging(true);
                }
              }}
              onTouchStart={(e) => {
                if (e.target.closest('.compare-slider')) {
                  setIsDragging(true);
                }
              }}
            >
              {/* Original video (bottom layer, clipped from left) */}
              <video
                className="compare-video compare-original"
                ref={originalVideoRef}
                src={originalUrl}
                style={{ clipPath: `inset(0 ${100 - sliderPos}% 0 0)` }}
                onPlay={() => trackedVideoRef.current?.play()}
                onPause={() => trackedVideoRef.current?.pause()}
                onSeeked={() => syncVideos(originalVideoRef.current, trackedVideoRef.current)}
                onTimeUpdate={() => {
                  if (!trackedVideoRef.current?.paused) return;
                  syncVideos(originalVideoRef.current, trackedVideoRef.current);
                }}
                muted
              />
              {/* Tracked video (top layer, clipped from right) */}
              <video
                className="compare-video compare-tracked"
                ref={trackedVideoRef}
                src={processedUrl}
                style={{ clipPath: `inset(0 0 0 ${sliderPos}%)` }}
                onPlay={() => {
                  originalVideoRef.current?.play();
                  setIsPlaying(true);
                }}
                onPause={() => {
                  originalVideoRef.current?.pause();
                  setIsPlaying(false);
                }}
                onSeeked={() => syncVideos(trackedVideoRef.current, originalVideoRef.current)}
                onTimeUpdate={() => {
                  if (!originalVideoRef.current?.paused) return;
                  syncVideos(trackedVideoRef.current, originalVideoRef.current);
                }}
                muted
              />
              {/* Slider handle */}
              <div
                className="compare-slider"
                style={{ left: `${sliderPos}%` }}
              >
                <div className="compare-slider-line" />
                <div className="compare-slider-handle">
                  <span className="compare-label compare-label-left">Original</span>
                  <span className="compare-label compare-label-right">Tracked</span>
                </div>
              </div>
            </div>

            {/* Video controls */}
            <div className="video-controls">
              <button
                className="control-btn"
                onClick={() => {
                  if (isPlaying) {
                    trackedVideoRef.current?.pause();
                    originalVideoRef.current?.pause();
                  } else {
                    trackedVideoRef.current?.play();
                    originalVideoRef.current?.play();
                  }
                }}
              >
                {isPlaying ? "⏸" : "▶"}
              </button>
              <input
                type="range"
                className="control-seek"
                min="0"
                max="100"
                step="0.1"
                defaultValue="0"
                onChange={(e) => {
                  const pct = e.target.value / 100;
                  if (trackedVideoRef.current) {
                    trackedVideoRef.current.currentTime = pct * trackedVideoRef.current.duration;
                  }
                  if (originalVideoRef.current) {
                    originalVideoRef.current.currentTime = pct * originalVideoRef.current.duration;
                  }
                }}
                ref={(el) => {
                  if (el && trackedVideoRef.current) {
                    trackedVideoRef.current.ontimeupdate = () => {
                      if (trackedVideoRef.current) {
                        el.value = (trackedVideoRef.current.currentTime / trackedVideoRef.current.duration) * 100;
                      }
                    };
                  }
                }}
              />
            </div>

            <div className="actions">
              <div style={{ display: "flex", gap: 8 }}>
                {packageUrl && (
                  <a className="btn" href={packageUrl} download>
                    Download All (ZIP)
                  </a>
                )}
                {dataCsvUrl && (
                  <a className="btn" href={dataCsvUrl} download>
                    Export CSV
                  </a>
                )}
                <button className="btn" onClick={resetForAnother}>
                  Run on another file
                </button>
              </div>
            </div>
            <div className="meta">
              <span>Input: {fileName || "—"}</span>
              <span>Output: {outputFolderName || "—"}</span>
            </div>

            {/* Motion Analysis Charts */}
            {motionStats && <MotionCharts data={motionStats} />}
          </>
        )}

        <JobHistory refreshKey={historyKey} />

        {/* Footer */}
        <footer className="footer">
          <a href="https://www.vclab.ca" target="_blank" rel="noopener noreferrer">VCLab</a><span>, Faculty of Science, Ontario Tech University</span>
        </footer>
      </main>
    </div>
  );
}

export default App;
