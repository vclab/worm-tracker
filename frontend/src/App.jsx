import { useRef, useState, useEffect, useCallback } from "react";

const SHOW_HEADER_IMAGE = true;

import MotionCharts from "./MotionCharts";
import JobHistory from "./JobHistory";
import HeadTailCorrector from "./HeadTailCorrector";
import Settings from "./Settings";
import RerunDialog from "./RerunDialog";
import ErrorBoundary from "./ErrorBoundary";
import MetricsPage from "./MetricsPage";
import { API } from "./api";

const STAGE_LABELS = {
  processing: "Analyzing frames",
  generating: "Generating video",
  finalizing: "Finalizing",
};

function App() {
  // Navigation
  const [activeTab, setActiveTab] = useState("tracker");

  // Results
  const [processedUrl, setProcessedUrl] = useState(null);
  const [originalUrl, setOriginalUrl] = useState(null);
  const [packageUrl, setPackageUrl] = useState(null);
  const [dataCsvUrl, setDataCsvUrl] = useState(null);
  const [outputFolderName, setOutputFolderName] = useState("");
  const [motionStats, setMotionStats] = useState(null);

  // UX
  const [fileName, setFileName] = useState("");
  const [historyKey, setHistoryKey] = useState(0);
  const [currentJobId, setCurrentJobId] = useState(null);
  const [showHtCorrector, setShowHtCorrector] = useState(false);
  const [regenPending, setRegenPending] = useState(false);
  const [submitError, setSubmitError] = useState(null);
  const [motionStatsLoading, setMotionStatsLoading] = useState(false);
  const [restartPending, setRestartPending] = useState(false);
  const [showRerunDialog, setShowRerunDialog] = useState(false);
  const [largeVideoPrompt, setLargeVideoPrompt] = useState(null);
  const [settingsModalOpen, setSettingsModalOpen] = useState(false);

  // Shared jobs state — read by both the Tracker strip and the History tab
  const [jobs, setJobs] = useState([]);

  // Head/tail overlay canvas
  const htCanvasRef = useRef(null);

  // Video comparison slider
  const [sliderPos, setSliderPos] = useState(50);
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
  const [pipeline, setPipeline] = useState("classical");
  const [confThreshold, setConfThreshold] = useState(0.25);
  const [usedParams, setUsedParams] = useState(null);

  const fileInputRef = useRef(null);
  const seekBarRef = useRef(null);
  const loadingJobRef = useRef(null);
  const motionStatsAbortRef = useRef(null);
  const sliderRafRef = useRef(null);
  const syncingRef = useRef(false);
  const jobPollRef = useRef(null);
  const mountedRef = useRef(true);

  // ── Jobs fetching (shared between Tracker strip and History tab) ──────────
  const fetchJobs = useCallback(async () => {
    try {
      const res = await fetch(`${API}/jobs`);
      if (res.ok && mountedRef.current) setJobs(await res.json());
    } catch { /* non-fatal */ }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  // Re-fetch when historyKey bumps (new upload, rerun, etc.)
  useEffect(() => {
    fetchJobs();
  }, [historyKey, fetchJobs]);

  // Poll every 2s while any job is pending, processing, or regenerating
  useEffect(() => {
    const hasActive = jobs.some(j => j.status === "pending" || j.status === "processing" || j.regen_pending);
    if (hasActive && !jobPollRef.current) {
      jobPollRef.current = setInterval(fetchJobs, 2000);
    } else if (!hasActive && jobPollRef.current) {
      clearInterval(jobPollRef.current);
      jobPollRef.current = null;
    }
    return () => {
      if (jobPollRef.current) { clearInterval(jobPollRef.current); jobPollRef.current = null; }
    };
  }, [jobs, fetchJobs]);

  // Heartbeat
  useEffect(() => {
    if (API !== "") return;
    const send = () => fetch(`${API}/api/heartbeat`, { method: "POST" }).catch(() => {});
    send();
    const id = setInterval(send, 5000);
    return () => clearInterval(id);
  }, []);

  // Check restart-pending
  useEffect(() => {
    fetch(`${API}/api/settings`)
      .then(r => r.ok ? r.json() : Promise.reject(new Error(r.statusText)))
      .then(data => { if (data.restart_pending) setRestartPending(true); })
      .catch(() => {});
  }, []);

  const syncVideos = useCallback((source, target) => {
    if (!source || !target || syncingRef.current) return;
    if (Math.abs(source.currentTime - target.currentTime) > 0.05) {
      syncingRef.current = true;
      target.currentTime = source.currentTime;
      target.addEventListener("seeked", () => { syncingRef.current = false; }, { once: true });
    }
  }, []);

  const handleSliderMove = useCallback((clientX) => {
    if (!compareContainerRef.current) return;
    if (sliderRafRef.current) cancelAnimationFrame(sliderRafRef.current);
    sliderRafRef.current = requestAnimationFrame(() => {
      sliderRafRef.current = null;
      const rect = compareContainerRef.current?.getBoundingClientRect();
      if (!rect) return;
      const x = clientX - rect.left;
      const percent = Math.max(0, Math.min(100, (x / rect.width) * 100));
      setSliderPos(percent);
    });
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

  // React to shared jobs state for regen-pending rather than its own interval
  useEffect(() => {
    if (!regenPending || !currentJobId) return;
    const job = jobs.find(j => j.job_id === currentJobId);
    if (job && !job.regen_pending) {
      setRegenPending(false);
      setProcessedUrl(url => {
        const base = url ? url.split("?")[0] : url;
        return base ? `${base}?t=${Date.now()}` : url;
      });
    }
  }, [jobs, regenPending, currentJobId]);

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
    setSubmitError(null);
    const errors = [];

    for (const file of files) {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("keypoints_per_worm", keypoints);
      formData.append("area_threshold", area);
      formData.append("max_age", maxAge);
      formData.append("persistence", persistence);
      formData.append("pipeline", pipeline);
      formData.append("conf_threshold", confThreshold);
      try {
        const res = await fetch(`${API}/upload`, { method: "POST", body: formData });
        const resData = await res.json().catch(() => ({}));
        if (!res.ok) {
          if (res.status === 503) {
            setRestartPending(true);
            setSubmitError(resData.detail || "Restart the app to apply settings changes before submitting jobs.");
            return;
          }
          errors.push(`${file.name}: ${resData.detail || res.statusText}`);
          continue;
        }
        if (resData.large_video) {
          setLargeVideoPrompt({
            jobId: resData.job_id,
            frameCount: resData.large_video.frame_count,
            sizeMb: resData.large_video.size_mb,
          });
          continue;
        }
      } catch (err) {
        errors.push(`${file.name}: ${err.message}`);
      }
    }

    fileInputRef.current.value = "";
    setFileName("");
    setHistoryKey(k => k + 1);
    if (errors.length > 0) {
      setSubmitError(`Failed to queue: ${errors.join("; ")}`);
    }
  };

  const confirmLargeVideo = async () => {
    if (!largeVideoPrompt) return;
    const { jobId } = largeVideoPrompt;
    setLargeVideoPrompt(null);
    try {
      const res = await fetch(`${API}/jobs/${jobId}/confirm`, { method: "POST" });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setSubmitError(data.detail || "Failed to confirm job");
        return;
      }
    } catch (err) {
      setSubmitError(`Confirm failed: ${err.message}`);
      return;
    }
    fileInputRef.current.value = "";
    setFileName("");
    setHistoryKey(k => k + 1);
  };

  const cancelLargeVideo = async () => {
    if (!largeVideoPrompt) return;
    const { jobId } = largeVideoPrompt;
    setLargeVideoPrompt(null);
    try {
      await fetch(`${API}/jobs/${jobId}`, { method: "DELETE" });
    } catch { /* ignore */ }
    fileInputRef.current.value = "";
    setFileName("");
  };

  // Load a completed job from history — also switches to Tracker tab
  const loadFromHistory = (job) => {
    setActiveTab("tracker");
    setOriginalUrl(job.original_video_path ? `${API}${job.original_video_path}` : null);
    setProcessedUrl(job.video_path ? `${API}${job.video_path}` : null);
    setPackageUrl(job.package_path ? `${API}${job.package_path}` : null);
    setDataCsvUrl(job.data_csv_path ? `${API}${job.data_csv_path}` : null);
    setFileName(job.original_filename || "");
    setOutputFolderName(job.output_subfolder || "");
    setCurrentJobId(job.job_id || null);
    setMotionStats(null);
    setMotionStatsLoading(false);
    setSliderPos(50);
    setIsPlaying(false);
    setShowHtCorrector(false);
    setRegenPending(job.regen_pending ? true : false);
    try {
      const p = job.params_json ? JSON.parse(job.params_json) : null;
      setUsedParams(p);
      if (p) {
        if (p.keypoints_per_worm != null) setKeypoints(p.keypoints_per_worm);
        if (p.area_threshold     != null) setArea(p.area_threshold);
        if (p.max_age            != null) setMaxAge(p.max_age);
        if (p.persistence        != null) setPersistence(p.persistence);
        setPipeline(p.pipeline ?? "classical");
        setConfThreshold(p.conf_threshold ?? 0.25);
      }
    } catch {
      setUsedParams(null);
    }
    if (seekBarRef.current) seekBarRef.current.value = 0;
    const thisJobId = job.job_id;
    loadingJobRef.current = thisJobId;
    if (motionStatsAbortRef.current) motionStatsAbortRef.current.abort();
    if (job.motion_stats_path) {
      setMotionStatsLoading(true);
      const ctrl = new AbortController();
      motionStatsAbortRef.current = ctrl;
      fetch(`${API}${job.motion_stats_path}`, { signal: ctrl.signal })
        .then(r => r.ok ? r.json() : Promise.reject(new Error(r.statusText)))
        .then(stats => {
          if (loadingJobRef.current === thisJobId) {
            setMotionStats(stats);
            setMotionStatsLoading(false);
          }
        })
        .catch(err => {
          if (err.name !== "AbortError" && loadingJobRef.current === thisJobId) {
            setMotionStatsLoading(false);
          }
        });
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const handleRerun = async (params) => {
    if (!currentJobId) return;
    setSubmitError(null);
    try {
      const res = await fetch(`${API}/jobs/${currentJobId}/rerun`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(params),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        if (res.status === 503) {
          setRestartPending(true);
          setSubmitError(data.detail || "Restart the app before submitting jobs.");
        } else {
          setSubmitError(data.detail || "Failed to start re-run");
        }
        return;
      }
      setShowRerunDialog(false);
      setHistoryKey(k => k + 1);
    } catch (err) {
      setSubmitError(`Re-run failed: ${err.message}`);
    }
  };

  const resetForAnother = () => {
    setShowRerunDialog(false);
    setUsedParams(null);
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

  // Active jobs for the Tracker-page strip
  const activeJobs = jobs.filter(j => j.status === "pending" || j.status === "processing");

  return (
    <div className="shell">
      {/* ── Modals (position: fixed, always in DOM) ── */}
      {showRerunDialog && (
        <RerunDialog
          usedParams={usedParams}
          onConfirm={handleRerun}
          onCancel={() => { setShowRerunDialog(false); setSubmitError(null); }}
          submitError={submitError}
          onClearError={() => setSubmitError(null)}
        />
      )}

      {largeVideoPrompt && (
        <div style={{
          position: "fixed", inset: 0, background: "rgba(0,0,0,0.7)",
          display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000,
        }}>
          <div style={{
            background: "var(--surface)", border: "0.5px solid var(--border)", borderRadius: 12,
            padding: "1.5rem", maxWidth: 420, width: "90%",
          }}>
            <h3 style={{ color: "var(--text-primary)", margin: "0 0 0.75rem", fontSize: "1rem" }}>
              Large video
            </h3>
            <p style={{ color: "var(--text-secondary)", fontSize: "0.875rem", margin: "0 0 1.25rem", lineHeight: 1.5 }}>
              This video is large ({largeVideoPrompt.frameCount.toLocaleString()} frames
              {largeVideoPrompt.sizeMb > 0 ? `, ${largeVideoPrompt.sizeMb} MB` : ""}).
              Processing may take a long time and use significant memory. Continue?
            </p>
            <div style={{ display: "flex", gap: 8 }}>
              <button className="btn" onClick={confirmLargeVideo}>Continue</button>
              <button
                className="btn"
                onClick={cancelLargeVideo}
                style={{ background: "rgba(239,68,68,0.12)", border: "0.5px solid #ef4444", color: "#ef4444" }}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Settings modal ── */}
      {settingsModalOpen && (
        <div
          style={{
            position: "fixed", inset: 0, background: "rgba(0,0,0,0.65)",
            display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000,
          }}
          onClick={() => setSettingsModalOpen(false)}
        >
          <div
            style={{
              background: "var(--surface)", border: "0.5px solid var(--border)",
              borderRadius: 12, padding: "1.5rem", maxWidth: 560, width: "90%",
              maxHeight: "80vh", overflowY: "auto",
            }}
            onClick={e => e.stopPropagation()}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "1.25rem" }}>
              <h2 style={{ margin: 0, fontSize: "1rem", fontWeight: 600, color: "var(--text-primary)" }}>Settings</h2>
              <button
                onClick={() => setSettingsModalOpen(false)}
                style={{
                  background: "none", border: "none", color: "var(--text-secondary)",
                  cursor: "pointer", fontSize: "1.1rem", padding: "2px 6px",
                  borderRadius: 4, lineHeight: 1, fontFamily: "inherit",
                }}
              >
                ✕
              </button>
            </div>
            <Settings pipeline={pipeline} hideTitle />
          </div>
        </div>
      )}

      {/* ── Sidebar ── */}
      <nav className="sidebar">
        <div className="sidebar-brand">
          {SHOW_HEADER_IMAGE && (
            <img
              src="/thumbnail.png"
              alt="Tracked microfilaria"
              className="sidebar-thumb"
            />
          )}
          <div className="header-title-block">
            <div className="title-row">
              <span className="title">PARATRACKER</span>
              <span className="version">v1.1.2</span>
            </div>
            <p className="subtitle">Microfilaria motion analysis</p>
          </div>
        </div>

        <div className="sidebar-nav">
          <button
            className={`nav-item${activeTab === "tracker" ? " nav-item--active" : ""}`}
            onClick={() => setActiveTab("tracker")}
          >
            Tracker
          </button>
          <button
            className={`nav-item${activeTab === "history" ? " nav-item--active" : ""}`}
            onClick={() => setActiveTab("history")}
          >
            History
          </button>
          <button
            className={`nav-item${activeTab === "metrics" ? " nav-item--active" : ""}`}
            onClick={() => setActiveTab("metrics")}
          >
            Metrics
          </button>
        </div>
      </nav>

      {/* ── Content area ── */}
      <div className="shell-content">

        {/* ── Tracker tab ── */}
        {activeTab === "tracker" && (
          <>
          {/* Centering wrapper */}
          <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", minHeight: "calc(100vh - 64px)" }}>
          <div className="card" style={{ position: "relative" }}>

            {/* Gear icon — opens Settings modal */}
            <button
              onClick={() => setSettingsModalOpen(true)}
              title="Settings"
              style={{
                position: "absolute", top: 14, right: 14,
                background: "none", border: "none", cursor: "pointer",
                color: "var(--text-muted)", fontSize: "1.1rem",
                padding: "4px 6px", borderRadius: 6, lineHeight: 1,
              }}
            >
              ⚙
            </button>

            {restartPending && (
              <div style={{
                background: "#1c1108", border: "0.5px solid #d97706", borderRadius: 8,
                padding: "10px 14px", marginBottom: "1rem",
                fontSize: "0.82rem", color: "#fbbf24", display: "flex", gap: 8, alignItems: "center",
              }}>
                <span>⚠</span>
                <span>Settings changed — restart the app before submitting new jobs.</span>
              </div>
            )}

            {/* Parameters */}
            {usedParams ? (
              <div className="used-params">
                <span className="used-params-label">Analysis parameters</span>
                <div className="used-params-values">
                  <span><span className="used-params-key">Keypoints</span>{usedParams.keypoints_per_worm ?? "—"}</span>
                  <span><span className="used-params-key">Area threshold</span>{usedParams.area_threshold ?? "—"}</span>
                  <span><span className="used-params-key">Max age</span>{usedParams.max_age ?? "—"}</span>
                  <span><span className="used-params-key">Persistence</span>{usedParams.persistence ?? "—"}</span>
                  <span><span className="used-params-key">Tracker</span>{(usedParams.pipeline ?? "classical") === "dl" ? "YOLO Tracker" : "Classical Tracker"}</span>
                  {usedParams.pipeline === "dl" && (
                    <span><span className="used-params-key">Conf. threshold</span>{usedParams.conf_threshold ?? "—"}</span>
                  )}
                </div>
              </div>
            ) : (
              <section className="form">
                <div className="field">
                  <label className="label">Keypoints per worm</label>
                  <input className="input" type="number" value={keypoints} onChange={e => setKeypoints(Number(e.target.value))} min={1} max={200} />
                </div>
                <div className="field">
                  <label className="label">Area threshold</label>
                  <input className="input" type="number" value={area} onChange={e => setArea(Number(e.target.value))} min={0} max={100000} />
                </div>
                <div className="field">
                  <label className="label">Max age</label>
                  <input className="input" type="number" value={maxAge} onChange={e => setMaxAge(Number(e.target.value))} min={0} max={10000} />
                </div>
                <div className="field">
                  <label className="label">Persistence</label>
                  <input className="input" type="number" value={persistence} onChange={e => setPersistence(Number(e.target.value))} min={1} max={10000} />
                </div>
                <div className="field">
                  <label className="label">Tracker</label>
                  <div style={{ display: "flex", gap: "1.25rem", alignItems: "center", paddingTop: "0.2rem" }}>
                    <label style={{ display: "flex", alignItems: "center", gap: "0.4rem", cursor: "pointer", fontSize: "0.9rem" }}>
                      <input type="radio" value="classical" checked={pipeline === "classical"} onChange={() => setPipeline("classical")} />
                      Classical Tracker
                    </label>
                    <label style={{ display: "flex", alignItems: "center", gap: "0.4rem", cursor: "pointer", fontSize: "0.9rem" }}>
                      <input type="radio" value="dl" checked={pipeline === "dl"} onChange={() => setPipeline("dl")} />
                      YOLO Tracker
                    </label>
                  </div>
                </div>
                {pipeline === "dl" && (
                  <div className="field">
                    <label className="label">Confidence threshold</label>
                    <input className="input" type="number" value={confThreshold} onChange={e => setConfThreshold(Number(e.target.value))} min={0} max={1} step={0.05} />
                  </div>
                )}
              </section>
            )}

            {/* File input */}
            {!processedUrl && (
              <section>
                <div className="file-wrap">
                  <label className="file-btn" htmlFor="file">Select videos</label>
                  <input
                    id="file"
                    ref={fileInputRef}
                    type="file"
                    accept="video/*"
                    multiple
                    onChange={e => {
                      const files = e.target.files;
                      if (files?.length === 1) setFileName(files[0].name);
                      else if (files?.length > 1) setFileName(`${files.length} files selected`);
                      else setFileName("");
                    }}
                  />
                  <span className="file-name">{fileName || "Select one or more videos to queue"}</span>
                </div>
                <div style={{ marginTop: "0.75rem" }}>
                  <button
                    className="btn"
                    onClick={handleSubmit}
                    disabled={restartPending}
                    style={restartPending ? { opacity: 0.4, cursor: "not-allowed" } : {}}
                  >
                    Add to queue
                  </button>
                  {submitError && (
                    <div style={{ marginTop: 8, color: "#ef4444", fontSize: "0.8rem", display: "flex", alignItems: "center", gap: 8 }}>
                      <span>{submitError}</span>
                      <button onClick={() => setSubmitError(null)} style={{ background: "none", border: "none", color: "#ef4444", cursor: "pointer", padding: 0, fontSize: "0.85rem" }}>✕</button>
                    </div>
                  )}
                </div>
              </section>
            )}

            {/* Player + actions */}
            {processedUrl && (
              <>
                {!originalUrl && (
                  <video src={processedUrl} controls style={{ width: "100%", borderRadius: 8, background: "#000", display: "block" }} />
                )}
                {originalUrl && (
                  <>
                    <div
                      className="video-compare"
                      ref={compareContainerRef}
                      onMouseDown={e => { if (e.target.closest(".compare-slider")) setIsDragging(true); }}
                      onTouchStart={e => { if (e.target.closest(".compare-slider")) setIsDragging(true); }}
                    >
                      <video
                        className="compare-video compare-original"
                        ref={originalVideoRef}
                        src={originalUrl}
                        style={{ clipPath: `inset(0 ${100 - sliderPos}% 0 0)` }}
                        onSeeked={() => syncVideos(originalVideoRef.current, trackedVideoRef.current)}
                        onTimeUpdate={() => {
                          if (!trackedVideoRef.current?.paused) return;
                          syncVideos(originalVideoRef.current, trackedVideoRef.current);
                        }}
                        muted
                      />
                      <video
                        className="compare-video compare-tracked"
                        ref={trackedVideoRef}
                        src={processedUrl}
                        style={{ clipPath: `inset(0 0 0 ${sliderPos}%)` }}
                        onPlay={() => setIsPlaying(true)}
                        onPause={() => setIsPlaying(false)}
                        onSeeked={() => syncVideos(trackedVideoRef.current, originalVideoRef.current)}
                        onTimeUpdate={() => {
                          if (!originalVideoRef.current?.paused) return;
                          syncVideos(trackedVideoRef.current, originalVideoRef.current);
                        }}
                        muted
                      />
                      {showHtCorrector && currentJobId && (
                        <canvas
                          ref={htCanvasRef}
                          style={{ position: "absolute", top: 0, left: 0, width: "100%", height: "100%", pointerEvents: "none", zIndex: 5 }}
                        />
                      )}
                      <div className="compare-slider" style={{ left: `${sliderPos}%` }}>
                        <div className="compare-slider-line" />
                        <div className="compare-slider-handle">
                          <span className="compare-label compare-label-left">Original</span>
                          <span className="compare-label compare-label-right">Tracked</span>
                        </div>
                      </div>
                    </div>

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
                        min="0" max="100" step="0.1"
                        defaultValue="0"
                        ref={seekBarRef}
                        onChange={e => {
                          const pct = e.target.value / 100;
                          if (trackedVideoRef.current) trackedVideoRef.current.currentTime = pct * trackedVideoRef.current.duration;
                          if (originalVideoRef.current) originalVideoRef.current.currentTime = pct * originalVideoRef.current.duration;
                        }}
                      />
                    </div>
                  </>
                )}

                <div className="actions">
                  {regenPending && (
                    <div style={{ fontSize: "0.8rem", color: "var(--accent-text)", marginBottom: 8, display: "flex", alignItems: "center", gap: 6 }}>
                      <span style={{ display: "inline-block", width: 10, height: 10, borderRadius: "50%", background: "var(--accent)", animation: "pulse 1.2s infinite" }} />
                      Regenerating outputs… downloads will be available when complete.
                    </div>
                  )}
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    {packageUrl && (
                      regenPending
                        ? <span className="btn" style={{ opacity: 0.4, cursor: "not-allowed", pointerEvents: "none" }}>Download All (ZIP)</span>
                        : <a className="btn" href={packageUrl} download>Download All (ZIP)</a>
                    )}
                    {dataCsvUrl && (
                      regenPending
                        ? <span className="btn" style={{ opacity: 0.4, cursor: "not-allowed", pointerEvents: "none" }}>Export CSV</span>
                        : <a className="btn" href={dataCsvUrl} download>Export CSV</a>
                    )}
                    {currentJobId && originalUrl && (
                      <button
                        className="btn"
                        onClick={() => setShowHtCorrector(v => !v)}
                        style={showHtCorrector ? { background: "var(--accent-bg)", border: "0.5px solid var(--accent)" } : {}}
                      >
                        {showHtCorrector ? "Hide H/T Correction" : "Head/Tail Correction"}
                      </button>
                    )}
                    {currentJobId && (
                      <button className="btn" onClick={() => { setSubmitError(null); setShowRerunDialog(true); }}>
                        Re-run with new parameters
                      </button>
                    )}
                    <button className="btn" onClick={resetForAnother}>Run on another file</button>
                  </div>
                </div>

                {showHtCorrector && currentJobId && originalUrl && (
                  <ErrorBoundary>
                    <HeadTailCorrector
                      jobId={currentJobId}
                      originalVideoRef={originalVideoRef}
                      overlayCanvasRef={htCanvasRef}
                      onMotionStatsUpdated={setMotionStats}
                      onFlipStarted={() => setRegenPending(true)}
                      regenPending={regenPending}
                    />
                  </ErrorBoundary>
                )}

                <div className="meta">
                  <span>Input: {fileName || "—"}</span>
                  <span>Output: {outputFolderName || "—"}</span>
                </div>

                {motionStatsLoading && (
                  <div style={{ color: "var(--text-muted)", fontSize: "0.82rem", marginTop: "0.5rem" }}>
                    Loading motion analysis…
                  </div>
                )}
                {motionStats && motionStats.num_worms === 0 && (
                  <div style={{ color: "var(--text-secondary)", fontSize: "0.82rem", marginTop: "0.5rem" }}>
                    No worms were detected in this video — try lowering the area threshold or check that worms are visible in the footage.
                  </div>
                )}
                {motionStats && motionStats.num_worms > 0 && (
                  <ErrorBoundary>
                    <MotionCharts data={motionStats} />
                  </ErrorBoundary>
                )}
              </>
            )}

            <footer className="footer">
              <span>A collaboration between the <a href="https://www.vclab.ca" target="_blank" rel="noopener noreferrer">Visual Computing Lab</a> and the Forrester Lab, Faculty of Science, Ontario Tech University.</span>
              <span>Lead developer: <a href="https://ca.linkedin.com/in/aaveg-shangari" target="_blank" rel="noopener noreferrer">Aaveg Shangari</a> — the first version of ParaTracker was completed during his Honours Thesis in the Visual Computing Lab.</span>
            </footer>
          </div>
          </div>{/* end centering wrapper */}
          </>
        )}

        {/* ── History tab ── */}
        {activeTab === "history" && (
          <div className="card card--history">
            <JobHistory
              jobs={jobs}
              onRefetch={fetchJobs}
              onLoad={loadFromHistory}
              currentJobId={currentJobId}
              onDeleteCurrent={resetForAnother}
            />
          </div>
        )}

        {/* ── Metrics tab ── */}
        {activeTab === "metrics" && (
          <ErrorBoundary>
            <MetricsPage />
          </ErrorBoundary>
        )}

      </div>

      {/* ── Active jobs strip — fixed bottom, Tracker tab only ── */}
      {activeTab === "tracker" && activeJobs.length > 0 && (
        <div style={{
          position: "fixed", bottom: 0, left: 260, right: 0, zIndex: 200,
          background: "#0f1115", borderTop: "0.5px solid var(--border)",
          padding: "7px 24px", display: "flex", flexDirection: "column", gap: 5,
        }}>
          {activeJobs.map(job => {
            const stageLabel = STAGE_LABELS[job.progress_stage] || "Processing";
            const statusText = job.status === "processing"
              ? `${stageLabel} — ${job.progress ?? 0}%`
              : "Pending";
            const fname = job.original_filename || "Unnamed";
            const displayName = fname.length > 38 ? fname.slice(0, 38) + "…" : fname;
            const isProc = job.status === "processing";
            return (
              <div key={job.job_id} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: "0.77rem" }}>
                <span style={{ color: isProc ? "var(--accent-text)" : "#f59e0b", fontSize: 9, flexShrink: 0 }}>●</span>
                <span style={{ color: "var(--text-primary)", maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flexShrink: 0 }}>
                  {displayName}
                </span>
                <span style={{ color: isProc ? "var(--accent-text)" : "#f59e0b", flexShrink: 0 }}>
                  {statusText}
                </span>
                {isProc && (
                  <div style={{ background: "var(--border)", borderRadius: 3, height: 3, width: 56, flexShrink: 0 }}>
                    <div style={{ background: "var(--accent)", borderRadius: 3, height: 3, width: `${job.progress ?? 0}%`, transition: "width 0.5s" }} />
                  </div>
                )}
                <button
                  onClick={() => setActiveTab("history")}
                  style={{ color: "var(--accent-text)", background: "none", border: "none", cursor: "pointer", fontSize: "0.77rem", padding: 0, textDecoration: "underline", fontFamily: "inherit", flexShrink: 0 }}
                >
                  History →
                </button>
              </div>
            );
          })}
        </div>
      )}

    </div>
  );
}

export default App;
