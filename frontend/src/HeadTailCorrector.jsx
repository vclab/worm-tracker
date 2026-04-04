import { useState, useEffect, useRef } from "react";

const API = "http://127.0.0.1:8000";

export default function HeadTailCorrector({
  jobId,
  originalVideoRef,
  overlayCanvasRef,
  onMotionStatsUpdated,
  onVideoUpdated,
}) {
  const [wormIds, setWormIds] = useState([]);
  const [numFrames, setNumFrames] = useState(0);
  const [headPositions, setHeadPositions] = useState({});
  const [tailPositions, setTailPositions] = useState({});
  const [selectedWorm, setSelectedWorm] = useState(null);
  const [flipping, setFlipping] = useState(false);
  const [flipError, setFlipError] = useState(null);
  const [pendingReload, setPendingReload] = useState(false);
  const rafRef = useRef(null);

  function fetchKeypoints() {
    return fetch(`${API}/jobs/${jobId}/keypoints`)
      .then((r) => r.json())
      .then((data) => {
        setWormIds(data.worm_ids || []);
        setNumFrames(data.num_frames || 0);
        setHeadPositions(data.head_positions || {});
        setTailPositions(data.tail_positions || {});
        return data;
      });
  }

  useEffect(() => {
    if (!jobId) return;
    fetchKeypoints()
      .then((data) => {
        if (data.worm_ids?.length > 0) setSelectedWorm(data.worm_ids[0]);
      })
      .catch(() => {});
  }, [jobId]);

  // Draw H/T dots on the overlay canvas using object-fit:contain scaling
  useEffect(() => {
    const video = originalVideoRef?.current;
    if (!video || !selectedWorm || numFrames === 0) return;

    let running = true;

    function drawDot(ctx, pos, color, label, scale, ox, oy) {
      if (!pos) return;
      const [y, x] = pos;
      const cx = x * scale + ox;
      const cy = y * scale + oy;
      ctx.beginPath();
      ctx.arc(cx, cy, 9, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
      ctx.strokeStyle = "#fff";
      ctx.lineWidth = 2;
      ctx.stroke();
      ctx.fillStyle = "#fff";
      ctx.font = "bold 10px sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(label, cx, cy);
    }

    function draw() {
      if (!running) return;
      const canvas = overlayCanvasRef?.current;
      if (!canvas) { rafRef.current = requestAnimationFrame(draw); return; }

      // Sync canvas resolution to its CSS-rendered size
      if (canvas.offsetWidth > 0 && canvas.offsetHeight > 0 &&
          (canvas.width !== canvas.offsetWidth || canvas.height !== canvas.offsetHeight)) {
        canvas.width = canvas.offsetWidth;
        canvas.height = canvas.offsetHeight;
      }

      const cw = canvas.width;
      const ch = canvas.height;
      const vw = video.videoWidth || cw;
      const vh = video.videoHeight || ch;

      const ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, cw, ch);

      if (!video.readyState) { rafRef.current = requestAnimationFrame(draw); return; }

      // object-fit: contain — compute rendered video rect
      const scale = Math.min(cw / vw, ch / vh);
      const ox = (cw - vw * scale) / 2;
      const oy = (ch - vh * scale) / 2;

      const fps = video.duration > 0 ? numFrames / video.duration : 30;
      const frameIdx = Math.min(Math.round(video.currentTime * fps), numFrames - 1);

      drawDot(ctx, headPositions[selectedWorm]?.[frameIdx], "#10b981", "H", scale, ox, oy);
      drawDot(ctx, tailPositions[selectedWorm]?.[frameIdx], "#ef4444", "T", scale, ox, oy);

      rafRef.current = requestAnimationFrame(draw);
    }

    rafRef.current = requestAnimationFrame(draw);
    return () => {
      running = false;
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      // Clear overlay on unmount
      const canvas = overlayCanvasRef?.current;
      if (canvas) canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
    };
  }, [selectedWorm, headPositions, tailPositions, numFrames, originalVideoRef, overlayCanvasRef]);

  async function handleFlip() {
    if (!selectedWorm || flipping) return;
    setFlipping(true);
    setFlipError(null);
    try {
      const res = await fetch(`${API}/jobs/${jobId}/flip/${selectedWorm}`, {
        method: "POST",
      });
      const data = await res.json();
      if (!res.ok) {
        setFlipError(data.detail || `Server error ${res.status}`);
        return;
      }
      if (data.ok) {
        const kpData = await fetch(`${API}/jobs/${jobId}/keypoints`).then((r) => r.json());
        setHeadPositions(kpData.head_positions || {});
        setTailPositions(kpData.tail_positions || {});
        if (data.motion_stats && onMotionStatsUpdated) {
          onMotionStatsUpdated(data.motion_stats);
        }
        setPendingReload(true);
      }
    } catch (e) {
      setFlipError(e.message || "Network error");
    } finally {
      setFlipping(false);
    }
  }

  function handleReloadVideo() {
    setPendingReload(false);
    if (onVideoUpdated) onVideoUpdated();
  }

  if (!jobId || wormIds.length === 0) return null;

  return (
    <div style={panelStyle}>
      <h3 style={titleStyle}>Head / Tail Correction</h3>
      <p style={subtitleStyle}>
        Select a worm to preview its head (H, green) and tail (T, red) on the video above. Click Flip to swap.
      </p>
      {flipping && (
        <div style={{ fontSize: "0.8rem", color: "#6366f1", marginBottom: 8 }}>
          Flipping worm {selectedWorm}…
        </div>
      )}
      {flipError && (
        <div style={{ fontSize: "0.8rem", color: "#ef4444", marginBottom: 8 }}>
          Error: {flipError}
        </div>
      )}
      {pendingReload && (
        <div style={{ marginBottom: 8, display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: "0.8rem", color: "#9ca3af" }}>
            Video is regenerating in the background.
          </span>
          <button onClick={handleReloadVideo} style={reloadBtnStyle}>
            Reload tracked video
          </button>
        </div>
      )}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {wormIds.map((wid) => (
          <div
            key={wid}
            onClick={() => setSelectedWorm(wid)}
            style={wormChipStyle(wid === selectedWorm)}
          >
            <span>Worm {wid}</span>
            {wid === selectedWorm && (
              <button
                onClick={(e) => { e.stopPropagation(); handleFlip(); }}
                disabled={flipping}
                style={flipBtnStyle(flipping)}
              >
                {flipping ? "…" : "Flip"}
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

const panelStyle = {
  marginTop: "1rem",
  padding: "14px 18px",
  background: "#0b1220",
  border: "1px solid #1f2937",
  borderRadius: 12,
};

const titleStyle = {
  margin: "0 0 4px 0",
  fontSize: "0.95rem",
  fontWeight: 600,
  color: "#e5e7eb",
};

const subtitleStyle = {
  margin: "0 0 10px 0",
  fontSize: "0.75rem",
  color: "#9ca3af",
};

function wormChipStyle(selected) {
  return {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    padding: "5px 10px",
    borderRadius: 6,
    cursor: "pointer",
    fontSize: "0.85rem",
    color: "#e5e7eb",
    background: selected ? "rgba(99, 102, 241, 0.15)" : "transparent",
    border: selected ? "1px solid rgba(99, 102, 241, 0.4)" : "1px solid #1f2937",
  };
}

function flipBtnStyle(disabled) {
  return {
    background: "none",
    border: "1px solid #374151",
    borderRadius: 4,
    color: disabled ? "#4b5563" : "#9ca3af",
    cursor: disabled ? "not-allowed" : "pointer",
    padding: "2px 8px",
    fontSize: "0.75rem",
  };
}

const reloadBtnStyle = {
  background: "#6366f1",
  border: "none",
  borderRadius: 5,
  color: "#fff",
  cursor: "pointer",
  padding: "4px 12px",
  fontSize: "0.8rem",
  fontWeight: 600,
};
