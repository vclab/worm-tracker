import { useState, useEffect } from "react";
import { API } from "./api";

function Settings({ onClose }) {
  const [outputsDir, setOutputsDir] = useState("");
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API}/api/settings`)
      .then((r) => r.json())
      .then((data) => {
        setOutputsDir(data.outputs_dir);
        setDraft(data.outputs_dir);
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
      if (!res.ok) throw new Error();
      const data = await res.json();
      setOutputsDir(data.outputs_dir);
      setDraft(data.outputs_dir);
      setEditing(false);
      setSaved(true);
    } catch {
      setError("Failed to save settings.");
    }
  };

  const handleCancel = () => {
    setDraft(outputsDir);
    setEditing(false);
  };

  return (
    <div className="settings-panel">
      <div className="settings-header">
        <span className="settings-title">Settings</span>
        <button className="settings-close" onClick={onClose}>✕</button>
      </div>

      {loading ? (
        <div className="settings-loading">Loading…</div>
      ) : (
        <>
          <div className="settings-row">
            <div className="settings-label">Outputs folder</div>
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
          </div>

          {error && <div className="settings-error">{error}</div>}

          {saved && (
            <div className="settings-note">
              Restart the app for changes to take effect.
            </div>
          )}

          <div className="settings-hint">
            Each outputs folder has its own job history. The database
            (<code>jobs.db</code>) lives inside the outputs folder.
          </div>
        </>
      )}
    </div>
  );
}

export default Settings;
