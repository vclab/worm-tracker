import { useRef, useState } from "react";

function App() {
  // Results
  const [processedUrl, setProcessedUrl] = useState(null); // MP4 (H.264) to view
  const [packageUrl, setPackageUrl] = useState(null); // ZIP with video+yaml+npz

  // UX
  const [loading, setLoading] = useState(false);
  const [fileName, setFileName] = useState("");

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

      const data = await res.json();
      const videoLink = data.video
        ? "http://127.0.0.1:8000" + data.video
        : null;
      const zipLink = data.package
        ? "http://127.0.0.1:8000" + data.package
        : null;

      setProcessedUrl(videoLink);
      setPackageUrl(zipLink);
    } catch (err) {
      alert("Error processing video: " + err.message);
    } finally {
      setLoading(false);
    }
  };

  // Reset UI to run on another file (keeps parameter values)
  const resetForAnother = () => {
    setProcessedUrl(null);
    setPackageUrl(null);
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
              placeholder="e.g. session1"
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
              <>
                <div className="progress">
                  <div className="progress__bar" />
                </div>
                <div className="helper">Processing your video… please wait</div>
              </>
            )}
          </section>
        )}

        {/* Player + actions */}
        {processedUrl && !loading && (
          <>
            <video className="player" src={processedUrl} controls />
            <div className="actions">
              <div className="helper">
                Video is web-optimized (H.264). Package includes YAML + NPZ.
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                {packageUrl && (
                  <a className="link" href={packageUrl} download>
                    Download All (ZIP)
                  </a>
                )}
                <button className="link" onClick={resetForAnother}>
                  Run on another file
                </button>
              </div>
            </div>
            <div className="meta">
              <span>File: {fileName || "—"}</span>
              <span>Output: {outName || "processed"}</span>
            </div>
          </>
        )}
      </main>
    </div>
  );
}

export default App;
