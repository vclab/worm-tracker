import { useState, useEffect } from "react";
import { API } from "./api";

function Settings({ pipeline, hideTitle = false }) {
  const [outputsDir, setOutputsDir] = useState("");
  const [configDir, setConfigDir] = useState("");
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const [configDraft, setConfigDraft] = useState("");
  const [editingConfig, setEditingConfig] = useState(false);
  const [savedConfig, setSavedConfig] = useState(false);
  const [configError, setConfigError] = useState(null);

  const [modelPath, setModelPath] = useState("");
  const [modelPathDraft, setModelPathDraft] = useState("");
  const [editingModel, setEditingModel] = useState(false);
  const [savedModel, setSavedModel] = useState(false);
  const [modelError, setModelError] = useState(null);

  useEffect(() => {
    fetch(`${API}/api/settings`)
      .then((r) => r.json())
      .then((data) => {
        setOutputsDir(data.outputs_dir);
        setDraft(data.outputs_dir);
        setConfigDir(data.config_dir || "");
        setConfigDraft(data.config_dir || "");
        setModelPath(data.model_path || "");
        setModelPathDraft(data.model_path || "");
        setLoading(false);
      })
      .catch(() => {
        setError("Could not load settings.");
        setLoading(false);
      });
  }, []);

  const handleSave = async () => {
    setError(null);
    try {
      const res = await fetch(`${API}/api/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ outputs_dir: draft }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Server error ${res.status}`);
      }
      const data = await res.json();
      setOutputsDir(data.outputs_dir);
      setDraft(data.outputs_dir);
      setEditing(false);
      setSaved(true);
    } catch (e) {
      setError(e.message || "Failed to save settings.");
    }
  };

  const handleCancel = () => {
    setDraft(outputsDir);
    setEditing(false);
  };

  const handleConfigSave = async () => {
    setConfigError(null);
    try {
      const res = await fetch(`${API}/api/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config_dir: configDraft }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Server error ${res.status}`);
      }
      const data = await res.json();
      setConfigDir(data.config_dir || configDraft);
      setConfigDraft(data.config_dir || configDraft);
      setEditingConfig(false);
      setSavedConfig(true);
    } catch (e) {
      setConfigError(e.message || "Failed to save config path.");
    }
  };

  const handleConfigCancel = () => {
    setConfigDraft(configDir);
    setEditingConfig(false);
  };

  const handleModelSave = async () => {
    setModelError(null);
    try {
      const res = await fetch(`${API}/api/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model_path: modelPathDraft }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Server error ${res.status}`);
      }
      const data = await res.json();
      setModelPath(data.model_path || "");
      setModelPathDraft(data.model_path || "");
      setEditingModel(false);
      setSavedModel(true);
    } catch (e) {
      setModelError(e.message || "Failed to save model path.");
    }
  };

  const handleModelCancel = () => {
    setModelPathDraft(modelPath);
    setEditingModel(false);
  };

  if (loading) {
    return <div className="settings-loading">Loading…</div>;
  }

  return (
    <>
      {!hideTitle && <h2 className="settings-page-title">Settings</h2>}

      {/* 1. CONFIG FOLDER */}
      <div className="settings-section">
        <div className="settings-label">CONFIG FOLDER</div>
        {editingConfig ? (
          <div className="settings-edit">
            <input
              className="settings-input"
              value={configDraft}
              onChange={(e) => setConfigDraft(e.target.value)}
              spellCheck={false}
            />
            <div className="settings-actions">
              <button className="btn" onClick={handleConfigSave}>Save</button>
              <button className="btn" onClick={handleConfigCancel}>Cancel</button>
            </div>
          </div>
        ) : (
          <div className="settings-value-row">
            <span className="settings-value">{configDir || "—"}</span>
            <button className="btn" onClick={() => { setSavedConfig(false); setEditingConfig(true); }}>
              Edit
            </button>
          </div>
        )}
        {configError && <div className="settings-error">{configError}</div>}
        {savedConfig && <div className="settings-note">Config path saved.</div>}
      </div>

      {/* 2. OUTPUTS FOLDER */}
      <div className="settings-section">
        <div className="settings-label">OUTPUTS FOLDER</div>
        {editing ? (
          <div className="settings-edit">
            <input
              className="settings-input"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              spellCheck={false}
            />
            <div className="settings-actions">
              <button className="btn" onClick={handleSave}>Save</button>
              <button className="btn" onClick={handleCancel}>Cancel</button>
            </div>
          </div>
        ) : (
          <div className="settings-value-row">
            <span className="settings-value">{outputsDir}</span>
            <button className="btn" onClick={() => { setSaved(false); setEditing(true); }}>
              Edit
            </button>
          </div>
        )}
        {error && <div className="settings-error">{error}</div>}
        {saved && <div className="settings-note">Restart the app for changes to take effect.</div>}
        <div className="settings-hint">
          Each outputs folder has its own job history. The database (<code>jobs.db</code>) lives inside the outputs folder.
        </div>
      </div>

      {/* 3. TRACKER CONFIGURATION */}
      <div className="settings-section">
        <div className="settings-label">TRACKER CONFIGURATION</div>
        {pipeline === "classical" ? (
          <div style={{ fontSize: "0.82rem", fontStyle: "italic", color: "var(--text-muted)", marginTop: "16px" }}>
            No additional configuration required for the Classical Tracker.
          </div>
        ) : (
          <>
            <div className="settings-label" style={{ marginTop: "16px" }}>MODEL WEIGHTS</div>
            {editingModel ? (
              <div className="settings-edit">
                <input
                  className="settings-input"
                  value={modelPathDraft}
                  onChange={(e) => setModelPathDraft(e.target.value)}
                  spellCheck={false}
                  placeholder="/path/to/best.pt"
                />
                <div className="settings-actions">
                  <button className="btn" onClick={handleModelSave}>Save</button>
                  <button className="btn" onClick={handleModelCancel}>Cancel</button>
                </div>
              </div>
            ) : (
              <div className="settings-value-row">
                <span className="settings-value" style={{ opacity: modelPath ? 1 : 0.4 }}>
                  {modelPath || "Not configured"}
                </span>
                <button className="btn" onClick={() => { setSavedModel(false); setEditingModel(true); }}>
                  Edit
                </button>
              </div>
            )}
            {modelError && <div className="settings-error">{modelError}</div>}
            {savedModel && <div className="settings-note">Model path saved.</div>}
            <div className="settings-hint">Path to YOLOv8-seg .pt weights file.</div>
          </>
        )}
      </div>
    </>
  );
}

export default Settings;
