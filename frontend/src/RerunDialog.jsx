import { useState, useEffect } from "react";
import { API } from "./api";

export default function RerunDialog({ usedParams, onConfirm, onCancel, submitError, onClearError }) {
  const [pipeline, setPipeline] = useState(usedParams?.pipeline ?? "classical");
  const [keypoints, setKeypoints] = useState(usedParams?.keypoints_per_worm ?? 15);
  const [area, setArea] = useState(usedParams?.area_threshold ?? 50);
  const [maxAge, setMaxAge] = useState(usedParams?.max_age ?? 35);
  const [persistence, setPersistence] = useState(usedParams?.persistence ?? 50);
  const [confThreshold, setConfThreshold] = useState(
    usedParams?.pipeline === "dl" ? (usedParams?.conf_threshold ?? 0.4) : 0.4
  );
  const [modelWeights, setModelWeights] = useState(usedParams?.model_weights ?? "");

  useEffect(() => {
    fetch(`${API}/api/settings`)
      .then((r) => r.json())
      .then((data) => {
        if (!usedParams?.model_weights) {
          setModelWeights(data.model_path || "");
        }
      })
      .catch(() => {});
  }, []);

  return (
    <div
      style={{
        position: "fixed", inset: 0,
        background: "rgba(0,0,0,0.65)",
        display: "flex", alignItems: "center", justifyContent: "center",
        zIndex: 1000,
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onCancel(); }}
    >
      <div style={{
        background: "#111827",
        border: "1px solid #374151",
        borderRadius: 12,
        padding: "1.5rem",
        width: "100%",
        maxWidth: 460,
        maxHeight: "90vh",
        overflowY: "auto",
        boxShadow: "0 25px 50px rgba(0,0,0,0.5)",
        margin: "0 1rem",
      }}>
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.25rem" }}>
          <span style={{ color: "#e5e7eb", fontSize: "1rem", fontWeight: 700 }}>Re-run with parameters</span>
          <button
            onClick={onCancel}
            style={{ background: "none", border: "none", color: "#6b7280", cursor: "pointer", fontSize: "1.1rem", padding: "0 4px", lineHeight: 1 }}
            aria-label="Close"
          >✕</button>
        </div>

        {/* Tracker radio */}
        <div style={{ marginBottom: "0.9rem" }}>
          <div style={labelStyle}>Tracker</div>
          <div style={{ display: "flex", gap: "1.25rem", alignItems: "center", paddingTop: "0.25rem" }}>
            <label style={radioLabelStyle}>
              <input
                type="radio"
                value="classical"
                checked={pipeline === "classical"}
                onChange={() => setPipeline("classical")}
              />
              Classical Tracker
            </label>
            <label style={radioLabelStyle}>
              <input
                type="radio"
                value="dl"
                checked={pipeline === "dl"}
                onChange={() => setPipeline("dl")}
              />
              YOLO Tracker
            </label>
          </div>
        </div>

        {/* Standard params */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem", marginBottom: pipeline === "dl" ? "0.75rem" : "1.25rem" }}>
          <div>
            <label style={labelStyle}>Keypoints per worm</label>
            <input
              className="input"
              type="number"
              value={keypoints}
              onChange={(e) => setKeypoints(Number(e.target.value))}
              min={1}
              max={200}
              style={{ width: "100%" }}
            />
          </div>
          <div>
            <label style={labelStyle}>Area threshold</label>
            <input
              className="input"
              type="number"
              value={area}
              onChange={(e) => setArea(Number(e.target.value))}
              min={0}
              max={100000}
              style={{ width: "100%" }}
            />
          </div>
          <div>
            <label style={labelStyle}>Max age</label>
            <input
              className="input"
              type="number"
              value={maxAge}
              onChange={(e) => setMaxAge(Number(e.target.value))}
              min={0}
              max={10000}
              style={{ width: "100%" }}
            />
          </div>
          <div>
            <label style={labelStyle}>Persistence</label>
            <input
              className="input"
              type="number"
              value={persistence}
              onChange={(e) => setPersistence(Number(e.target.value))}
              min={1}
              max={10000}
              style={{ width: "100%" }}
            />
          </div>
        </div>

        {/* YOLO-specific fields */}
        {pipeline === "dl" && (
          <div style={{
            marginBottom: "1.25rem",
            padding: "0.75rem",
            background: "#0f172a",
            borderRadius: 8,
            border: "1px solid #1e293b",
          }}>
            <div style={{ marginBottom: "0.75rem" }}>
              <label style={labelStyle}>Confidence threshold</label>
              <input
                className="input"
                type="number"
                value={confThreshold}
                onChange={(e) => setConfThreshold(Number(e.target.value))}
                min={0}
                max={1}
                step={0.05}
                style={{ width: "100%" }}
              />
            </div>
            <div>
              <label style={labelStyle}>Model weights path</label>
              <input
                type="text"
                value={modelWeights}
                readOnly
                className="input"
                style={{ width: "100%", opacity: 0.55, cursor: "default" }}
              />
              <div style={{ fontSize: "0.72rem", color: "#6b7280", marginTop: "0.2rem" }}>
                Change model weights in Settings (⚙).
              </div>
            </div>
          </div>
        )}

        {/* Error */}
        {submitError && (
          <div style={{ color: "#ef4444", fontSize: "0.8rem", marginBottom: "0.75rem", display: "flex", gap: 8, alignItems: "center" }}>
            <span>{submitError}</span>
            <button
              onClick={onClearError}
              style={{ background: "none", border: "none", color: "#ef4444", cursor: "pointer", padding: 0, fontSize: "0.85rem", lineHeight: 1 }}
            >✕</button>
          </div>
        )}

        {/* Actions */}
        <div style={{ display: "flex", gap: "0.5rem", justifyContent: "flex-end" }}>
          <button
            className="btn"
            onClick={() => onConfirm({
              keypoints_per_worm: keypoints,
              area_threshold: area,
              max_age: maxAge,
              persistence,
              pipeline,
              conf_threshold: confThreshold,
            })}
          >
            Confirm re-run
          </button>
          <button
            className="btn"
            onClick={onCancel}
            style={{ background: "none", border: "1px solid #374151", color: "#9ca3af" }}
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

const labelStyle = { fontSize: "0.82rem", color: "#9ca3af", marginBottom: "0.25rem", fontWeight: 500, display: "block" };
const radioLabelStyle = { display: "flex", alignItems: "center", gap: "0.4rem", cursor: "pointer", fontSize: "0.9rem", color: "#e5e7eb" };
