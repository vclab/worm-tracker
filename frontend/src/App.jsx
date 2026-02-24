import { useRef, useState } from "react";
import MotionCharts from "./MotionCharts";

function App() {
  // Results
  const [processedUrl, setProcessedUrl] = useState(null); // MP4 (H.264) to view
  const [packageUrl, setPackageUrl] = useState(null); // ZIP with video+yaml+npz
  const [outputFolderName, setOutputFolderName] = useState(""); // e.g., "20260224_181803_tracking01"
  const [motionStats, setMotionStats] = useState(null); // Motion analysis data

  // UX
  const [loading, setLoading] = useState(false);
  const [fileName, setFileName] = useState("");

  // Progress tracking
  const [progress, setProgress] = useState({ stage: "", current: 0, total: 0 });

  // Parameters
  const [keypoints, setKeypoints] = useState(15);
  const [area, setArea] = useState(50);
  const [maxAge, setMaxAge] = useState(35);
  const [persistence, setPersistence] = useState(50);
  const [outName, setOutName] = useState("");

  // Ref to clear the file input on reset
  const fileInputRef = useRef(null);

  const onPickFile = (e) => {
    const f = e.target.files?.[0];
    if (f) setFileName(f.name);
  };

  const handleFileChange = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

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

    try {
      const res = await fetch("http://127.0.0.1:8000/upload", {
        method: "POST",
        body: formData,
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
              setLoading(false);
            } else if (data.stage === "error") {
              throw new Error(data.message);
            }
          }
        }
      }
    } catch (err) {
      alert("Error processing video: " + err.message);
      setLoading(false);
    }
  };

  // Reset UI to run on another file (keeps parameter values)
  const resetForAnother = () => {
    setProcessedUrl(null);
    setPackageUrl(null);
    setOutputFolderName("");
    setMotionStats(null);
    setLoading(false);
    setFileName("");
    if (fileInputRef.current) fileInputRef.current.value = "";
    // Optionally scroll to top for convenience
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  return (
    <div className="container">
      <main className="card">
        {/* Header */}
        <div className="header">
          <div>
            <div className="title">Worm Tracker</div>
            <div className="subtitle">
              Upload → Process → View → Download Package
            </div>
          </div>
          {processedUrl && <span className="badge">Ready</span>}
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
              </div>
            )}
          </section>
        )}

        {/* Player + actions */}
        {processedUrl && !loading && (
          <>
            <video className="player" src={processedUrl} controls />
            <div className="actions">
              <div style={{ display: "flex", gap: 8 }}>
                {packageUrl && (
                  <a className="btn" href={packageUrl} download>
                    Download All (ZIP)
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
      </main>
    </div>
  );
}

export default App;
