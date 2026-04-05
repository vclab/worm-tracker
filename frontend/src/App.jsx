import { useRef, useState, useEffect, useCallback } from "react";
import MotionCharts from "./MotionCharts";
import JobHistory from "./JobHistory";
import HeadTailCorrector from "./HeadTailCorrector";
import { API } from "./api";

function App() {
  // Results
  const [processedUrl, setProcessedUrl] = useState(null); // MP4 (H.264) to view
  const [originalUrl, setOriginalUrl] = useState(null); // Server URL for original video
  const [packageUrl, setPackageUrl] = useState(null); // ZIP with video+yaml+npz
  const [dataCsvUrl, setDataCsvUrl] = useState(null); // CSV data ZIP for export
  const [outputFolderName, setOutputFolderName] = useState(""); // e.g., "20260224_181803_tracking01"
  const [motionStats, setMotionStats] = useState(null); // Motion analysis data

  // UX
  const [fileName, setFileName] = useState("");
  const [historyKey, setHistoryKey] = useState(0);
  const [currentJobId, setCurrentJobId] = useState(null);
  const [showHtCorrector, setShowHtCorrector] = useState(false);
  const [regenPending, setRegenPending] = useState(false);

  // Head/tail overlay canvas (drawn over the comparison slider)
  const htCanvasRef = useRef(null);

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

  // Ref to clear the file input on reset
  const fileInputRef = useRef(null);

  // Seek bar ref + motion stats load tracking (prevents stale fetch from overwriting newer job)
  const seekBarRef = useRef(null);
  const loadingJobRef = useRef(null);

  // Sync video playback between original and tracked
  const syncVideos = useCallback((source, target) => {
    if (!source || !target) return;
    if (Math.abs(source.currentTime - target.currentTime) > 0.05) {
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

  // Poll while a regeneration is in progress, then auto-reload the video
  useEffect(() => {
    if (!regenPending || !currentJobId) return;
    const id = setInterval(async () => {
      try {
        const res = await fetch(`${API}/jobs`);
        if (!res.ok) return;
        const jobs = await res.json();
        const job = jobs.find((j) => j.job_id === currentJobId);
        if (job && !job.regen_pending) {
          setRegenPending(false);
          setProcessedUrl((url) => {
            const base = url ? url.split("?")[0] : url;
            return base ? `${base}?t=${Date.now()}` : url;
          });
        }
      } catch { /* ignore fetch errors during poll */ }
    }, 2000);
    return () => clearInterval(id);
  }, [regenPending, currentJobId]);

  // Keep seek bar in sync with tracked video — set up once per video URL
  useEffect(() => {
    const video = trackedVideoRef.current;
    const seek = seekBarRef.current;
    if (!video || !seek) return;
    seek.value = 0;
    const handler = () => {
      if (video.duration > 0 && isFinite(video.duration)) {
        seek.value = (video.currentTime / video.duration) * 100;
      }
    };
    video.addEventListener("timeupdate", handler);
    return () => video.removeEventListener("timeupdate", handler);
  }, [processedUrl]);

  const handleSubmit = async () => {
    const files = fileInputRef.current?.files;
    if (!files || files.length === 0) return;

    for (const file of files) {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("keypoints_per_worm", keypoints);
      formData.append("area_threshold", area);
      formData.append("max_age", maxAge);
      formData.append("persistence", persistence);
      try {
        await fetch(`${API}/upload`, { method: "POST", body: formData });
      } catch (err) {
        alert(`Failed to queue ${file.name}: ${err.message}`);
      }
    }

    fileInputRef.current.value = "";
    setFileName("");
    setHistoryKey((k) => k + 1);
  };

  // Load a completed job from history into the results view
  const loadFromHistory = (job) => {
    setOriginalUrl(job.original_video_path ? `${API}${job.original_video_path}` : null);
    setProcessedUrl(job.video_path ? `${API}${job.video_path}` : null);
    setPackageUrl(job.package_path ? `${API}${job.package_path}` : null);
    setDataCsvUrl(job.data_csv_path ? `${API}${job.data_csv_path}` : null);
    setFileName(job.original_filename || "");
    setOutputFolderName(job.output_subfolder || "");
    setCurrentJobId(job.job_id || null);
    setMotionStats(null);
    setSliderPos(50);
    setIsPlaying(false);
    setShowHtCorrector(false);
    setRegenPending(job.regen_pending ? true : false);
    const thisJobId = job.job_id;
    loadingJobRef.current = thisJobId;
    if (job.motion_stats_path) {
      fetch(`${API}${job.motion_stats_path}`)
        .then((r) => r.json())
        .then((stats) => {
          if (loadingJobRef.current === thisJobId) setMotionStats(stats);
        })
        .catch((err) => console.error("Failed to load motion stats:", err));
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  // Reset results view (keeps parameter values)
  const resetForAnother = () => {
    setOriginalUrl(null);
    setProcessedUrl(null);
    setPackageUrl(null);
    setDataCsvUrl(null);
    setOutputFolderName("");
    setCurrentJobId(null);
    setMotionStats(null);
    setFileName("");
    setSliderPos(50);
    setIsPlaying(false);
    setShowHtCorrector(false);
    setRegenPending(false);
    if (fileInputRef.current) fileInputRef.current.value = "";
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
              <span className="badge">Viewing results</span>
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
              onChange={(e) => setKeypoints(Number(e.target.value))}
              min={1}
            />
          </div>
          <div className="field">
            <label className="label">Area threshold</label>
            <input
              className="input"
              type="number"
              value={area}
              onChange={(e) => setArea(Number(e.target.value))}
              min={0}
            />
          </div>
          <div className="field">
            <label className="label">Max age</label>
            <input
              className="input"
              type="number"
              value={maxAge}
              onChange={(e) => setMaxAge(Number(e.target.value))}
              min={0}
            />
          </div>
          <div className="field">
            <label className="label">Persistence</label>
            <input
              className="input"
              type="number"
              value={persistence}
              onChange={(e) => setPersistence(Number(e.target.value))}
              min={1}
            />
          </div>
        </section>

        {/* File input */}
        {!processedUrl && (
          <section>
            <div className="file-wrap">
              <label className="file-btn" htmlFor="file">
                Select videos
              </label>
              <input
                id="file"
                ref={fileInputRef}
                type="file"
                accept="video/*"
                multiple
                onChange={(e) => {
                  const files = e.target.files;
                  if (files?.length === 1) setFileName(files[0].name);
                  else if (files?.length > 1) setFileName(`${files.length} files selected`);
                  else setFileName("");
                }}
              />
              <span className="file-name">
                {fileName || "Select one or more videos to queue"}
              </span>
            </div>
            <div style={{ marginTop: "0.75rem" }}>
              <button className="btn" onClick={handleSubmit}>
                Add to queue
              </button>
            </div>
          </section>
        )}

        {/* Player + actions */}
        {processedUrl && (
          <>
            {/* Plain player when no original is available (history load without blob) */}
            {!originalUrl && (
              <video
                src={processedUrl}
                controls
                style={{ width: "100%", borderRadius: 8, background: "#000", display: "block" }}
              />
            )}
            {/* Comparison slider when original is available */}
            {originalUrl && (
              <>
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
                  {/* H/T overlay canvas */}
                  {showHtCorrector && currentJobId && (
                    <canvas
                      ref={htCanvasRef}
                      style={{
                        position: "absolute",
                        top: 0, left: 0,
                        width: "100%", height: "100%",
                        pointerEvents: "none",
                        zIndex: 5,
                      }}
                    />
                  )}
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
                    ref={seekBarRef}
                    onChange={(e) => {
                      const pct = e.target.value / 100;
                      if (trackedVideoRef.current) {
                        trackedVideoRef.current.currentTime = pct * trackedVideoRef.current.duration;
                      }
                      if (originalVideoRef.current) {
                        originalVideoRef.current.currentTime = pct * originalVideoRef.current.duration;
                      }
                    }}
                  />
                </div>
              </>
            )}

            <div className="actions">
              {regenPending && (
                <div style={{ fontSize: "0.8rem", color: "#6366f1", marginBottom: 8, display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ display: "inline-block", width: 10, height: 10, borderRadius: "50%", background: "#6366f1", animation: "pulse 1.2s infinite" }} />
                  Regenerating outputs… downloads will be available when complete.
                </div>
              )}
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {packageUrl && (
                  regenPending ? (
                    <span className="btn" style={{ opacity: 0.4, cursor: "not-allowed", pointerEvents: "none" }}>
                      Download All (ZIP)
                    </span>
                  ) : (
                    <a className="btn" href={packageUrl} download>
                      Download All (ZIP)
                    </a>
                  )
                )}
                {dataCsvUrl && (
                  regenPending ? (
                    <span className="btn" style={{ opacity: 0.4, cursor: "not-allowed", pointerEvents: "none" }}>
                      Export CSV
                    </span>
                  ) : (
                    <a className="btn" href={dataCsvUrl} download>
                      Export CSV
                    </a>
                  )
                )}
                {currentJobId && originalUrl && (
                  <button
                    className="btn"
                    onClick={() => setShowHtCorrector((v) => !v)}
                    style={showHtCorrector ? { background: "rgba(99,102,241,0.2)", border: "1px solid #6366f1" } : {}}
                  >
                    {showHtCorrector ? "Hide H/T Correction" : "Head/Tail Correction"}
                  </button>
                )}
                <button className="btn" onClick={resetForAnother}>
                  Run on another file
                </button>
              </div>
            </div>
            {/* Head/Tail Correction */}
            {showHtCorrector && currentJobId && originalUrl && (
              <HeadTailCorrector
                jobId={currentJobId}
                originalVideoRef={originalVideoRef}
                overlayCanvasRef={htCanvasRef}
                onMotionStatsUpdated={setMotionStats}
                onFlipStarted={() => setRegenPending(true)}
                regenPending={regenPending}
              />
            )}

            <div className="meta">
              <span>Input: {fileName || "—"}</span>
              <span>Output: {outputFolderName || "—"}</span>
            </div>

            {/* Motion Analysis Charts */}
            {motionStats && <MotionCharts data={motionStats} />}
          </>
        )}

        <JobHistory refreshKey={historyKey} onLoad={loadFromHistory} />

        {/* Footer */}
        <footer className="footer">
          <a href="https://www.vclab.ca" target="_blank" rel="noopener noreferrer">VCLab</a><span>, Faculty of Science, Ontario Tech University</span>
        </footer>
      </main>
    </div>
  );
}

export default App;
