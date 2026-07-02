import { useState } from "react";
import { API } from "./api";

const STATUS_STYLES = {
  done: { color: "#10b981", label: "Done" },
  processing: { color: "#6366f1", label: "Processing" },
  pending: { color: "#f59e0b", label: "Pending" },
  error: { color: "#ef4444", label: "Error" },
  cancelled: { color: "#6b7280", label: "Cancelled" },
};

const STAGE_LABELS = {
  processing: "Analyzing frames",
  generating: "Generating video",
  finalizing: "Finalizing",
  done: "Done",
};

function formatDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

export default function JobHistory({ jobs, onRefetch, onLoad, currentJobId = null, onDeleteCurrent }) {
  const [actionError, setActionError] = useState(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState(null);

  function showError(msg) {
    setActionError(msg);
  }

  async function handleCancel(jobId) {
    try {
      setActionError(null);
      await fetch(`${API}/cancel/${jobId}`, { method: "POST" });
      onRefetch();
    } catch {
      showError("Failed to cancel job");
    }
  }

  async function handleDelete(jobId) {
    try {
      setActionError(null);
      await fetch(`${API}/jobs/${jobId}`, { method: "DELETE" });
      if (jobId === currentJobId && onDeleteCurrent) onDeleteCurrent();
      setConfirmDeleteId(null);
      onRefetch();
    } catch {
      showError("Failed to delete job");
      setConfirmDeleteId(null);
    }
  }

  if (!jobs || jobs.length === 0) return null;

  return (
    <div>
      <div style={summaryStyle}>
        Job History
        <span style={badgeStyle}>{jobs.length}</span>
      </div>

      {actionError && (
        <div style={{ color: "#ef4444", fontSize: "0.8rem", marginBottom: 8, display: "flex", alignItems: "center", gap: 8 }}>
          <span>{actionError}</span>
          <button
            onClick={() => setActionError(null)}
            style={{ background: "none", border: "none", color: "#ef4444", cursor: "pointer", fontSize: "0.85rem", padding: 0, lineHeight: 1 }}
          >
            ✕
          </button>
        </div>
      )}
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem", color: "var(--text-primary)" }}>
          <thead>
            <tr style={{ borderBottom: "0.5px solid var(--border)", color: "var(--text-secondary)", textAlign: "left" }}>
              <th style={th}>Date</th>
              <th style={th}>File</th>
              <th style={th}>Tracker</th>
              <th style={th}>Status</th>
              <th style={th}>Downloads</th>
              <th style={th}></th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => {
              const s = STATUS_STYLES[job.status] || STATUS_STYLES.cancelled;
              const isActive = job.status === "pending" || job.status === "processing";
              const isCurrent = job.job_id === currentJobId;
              let trackerLabel = "—";
              try {
                const p = job.params_json ? JSON.parse(job.params_json) : null;
                if (p) trackerLabel = p.pipeline === "dl" ? "YOLO" : "Classical";
              } catch { }
              return (
                <tr key={job.job_id} style={{ borderBottom: "0.5px solid var(--border)", background: isCurrent ? "rgba(29,158,117,0.07)" : "transparent" }}>
                  <td style={{ ...td, whiteSpace: "nowrap", color: "var(--text-secondary)", borderLeft: isCurrent ? "3px solid var(--accent)" : "3px solid transparent" }}>
                    {formatDate(job.created_at)}
                  </td>
                  <td style={td} title={job.original_filename || undefined}>
                    {job.original_filename
                      ? job.original_filename.length > 22
                        ? job.original_filename.slice(0, 22) + "…"
                        : job.original_filename
                      : "—"}
                  </td>
                  <td style={{ ...td, color: "var(--text-secondary)" }}>{trackerLabel}</td>
                  <td style={td}>
                    <span style={{ color: s.color, fontWeight: 600, fontSize: "0.8rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                      {s.label}
                    </span>
                    {job.status === "processing" && (
                      <div style={{ marginTop: 4 }}>
                        <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.72rem", color: "var(--text-secondary)", marginBottom: 2 }}>
                          <span>{STAGE_LABELS[job.progress_stage] || job.progress_stage || ""}</span>
                          <span>{job.progress ?? 0}%</span>
                        </div>
                        <div style={{ background: "var(--border)", borderRadius: 3, height: 4, width: 140 }}>
                          <div style={{ background: "var(--accent)", borderRadius: 3, height: 4, width: `${job.progress ?? 0}%`, transition: "width 0.5s" }} />
                        </div>
                      </div>
                    )}
                    {job.error_msg && (
                      <div style={{ color: "#ef4444", fontSize: "0.75rem", marginTop: 2 }}>
                        {job.error_msg}
                      </div>
                    )}
                  </td>
                  <td style={td}>
                    {job.status === "done" && (
                      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center" }}>
                        {onLoad && (
                          <button onClick={() => onLoad(job)} style={btnPrimary}>View</button>
                        )}
                        {job.regen_pending ? (
                          <span style={{ fontSize: "0.75rem", color: "var(--accent-text)", fontStyle: "italic" }}>Regenerating…</span>
                        ) : (
                          <>
                            {job.video_path && (
                              <a href={`${API}${job.video_path}`} download style={linkStyle}>Video</a>
                            )}
                            {job.package_path && (
                              <a href={`${API}${job.package_path}`} download style={linkStyle}>ZIP</a>
                            )}
                            {job.data_csv_path && (
                              <a href={`${API}${job.data_csv_path}`} download style={linkStyle}>CSV</a>
                            )}
                          </>
                        )}
                      </div>
                    )}
                  </td>
                  <td style={td}>
                    {isActive ? (
                      <button onClick={() => handleCancel(job.job_id)} style={btnCancel}>
                        Cancel
                      </button>
                    ) : confirmDeleteId === job.job_id ? (
                      <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
                        <button onClick={() => handleDelete(job.job_id)} style={btnDeleteConfirm}>
                          Confirm
                        </button>
                        <button onClick={() => setConfirmDeleteId(null)} style={btnDelete}>
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <button onClick={() => setConfirmDeleteId(job.job_id)} style={btnDelete}>
                        Delete
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const summaryStyle = {
  fontWeight: 600, fontSize: "1rem", color: "var(--text-primary)",
  marginBottom: "1rem",
  display: "flex", alignItems: "center", gap: "0.5rem",
};
const badgeStyle = {
  background: "var(--surface)", borderRadius: "999px", padding: "1px 8px",
  fontSize: "0.75rem", color: "var(--text-secondary)",
  border: "0.5px solid var(--border)",
};
const th = { padding: "6px 10px" };
const td = { padding: "8px 10px" };

const linkStyle = {
  color: "var(--accent-text)", textDecoration: "none",
  border: "0.5px solid var(--accent)",
  borderRadius: 5, padding: "2px 7px", fontSize: "0.8rem",
};
const btnPrimary = {
  background: "var(--accent)", color: "var(--accent-btn-text)", border: "none",
  borderRadius: 5, padding: "2px 10px", fontSize: "0.8rem", cursor: "pointer", fontWeight: 600,
};
const btnCancel = {
  background: "none", border: "0.5px solid #ef4444", borderRadius: 6,
  color: "#ef4444", cursor: "pointer", padding: "3px 8px", fontSize: "0.8rem",
};
const btnDelete = {
  background: "none", border: "0.5px solid var(--border)", borderRadius: 6,
  color: "var(--text-secondary)", cursor: "pointer", padding: "3px 8px", fontSize: "0.8rem",
};
const btnDeleteConfirm = {
  background: "none", border: "0.5px solid #ef4444", borderRadius: 6,
  color: "#ef4444", cursor: "pointer", padding: "3px 8px", fontSize: "0.8rem",
};
