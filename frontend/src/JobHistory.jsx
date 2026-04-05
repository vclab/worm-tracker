import { useState, useEffect, useRef } from "react";
import { API } from "./api";

const STATUS_STYLES = {
  done:       { color: "#10b981", label: "Done" },
  processing: { color: "#6366f1", label: "Processing" },
  pending:    { color: "#f59e0b", label: "Pending" },
  error:      { color: "#ef4444", label: "Error" },
  cancelled:  { color: "#6b7280", label: "Cancelled" },
};

const STAGE_LABELS = {
  processing: "Analyzing frames",
  generating: "Generating video",
  finalizing: "Finalizing",
  done:       "Done",
};

function formatDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

export default function JobHistory({ refreshKey = 0, onLoad }) {
  const [jobs, setJobs] = useState([]);
  const [open, setOpen] = useState(false);
  const pollRef = useRef(null);

  async function fetchJobs() {
    try {
      const res = await fetch(`${API}/jobs`);
      if (res.ok) setJobs(await res.json());
    } catch (err) {
      console.error("Failed to fetch jobs:", err);
    }
  }

  // Initial fetch + re-fetch when refreshKey changes
  useEffect(() => {
    if (refreshKey > 0) {
      fetchJobs().then(() => setOpen(true));
    } else {
      fetchJobs();
    }
  }, [refreshKey]);

  // Poll every 2s while any job is pending or processing
  useEffect(() => {
    const hasActive = jobs.some((j) => j.status === "pending" || j.status === "processing");
    if (hasActive && !pollRef.current) {
      pollRef.current = setInterval(fetchJobs, 2000);
    } else if (!hasActive && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    };
  }, [jobs]);

  async function handleCancel(jobId) {
    await fetch(`${API}/cancel/${jobId}`, { method: "POST" });
    fetchJobs();
  }

  async function handleDelete(jobId) {
    if (!confirm("Delete this job and all its output files?")) return;
    await fetch(`${API}/jobs/${jobId}`, { method: "DELETE" });
    fetchJobs();
  }

  if (jobs.length === 0) return null;

  return (
    <div style={{ marginTop: "2rem" }}>
      <details open={open} onToggle={(e) => setOpen(e.target.open)}>
        <summary style={summaryStyle}>
          <span style={{ fontSize: "0.85rem", color: "#9ca3af" }}>{open ? "▾" : "▸"}</span>
          Job History
          <span style={badgeStyle}>{jobs.length}</span>
        </summary>

        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem", color: "#e5e7eb" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #1f2937", color: "#9ca3af", textAlign: "left" }}>
                <th style={th}>Date</th>
                <th style={th}>File</th>
                <th style={th}>Status</th>
                <th style={th}>Downloads</th>
                <th style={th}></th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => {
                const s = STATUS_STYLES[job.status] || STATUS_STYLES.cancelled;
                const isActive = job.status === "pending" || job.status === "processing";
                return (
                  <tr key={job.job_id} style={{ borderBottom: "1px solid #1f2937" }}>
                    <td style={{ ...td, whiteSpace: "nowrap", color: "#9ca3af" }}>
                      {formatDate(job.created_at)}
                    </td>
                    <td style={{ ...td, maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                        title={job.original_filename || ""}>
                      {job.original_filename || "—"}
                    </td>
                    <td style={td}>
                      <span style={{ color: s.color, fontWeight: 600, fontSize: "0.8rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                        {s.label}
                      </span>
                      {job.status === "processing" && (
                        <div style={{ marginTop: 4 }}>
                          <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.72rem", color: "#9ca3af", marginBottom: 2 }}>
                            <span>{STAGE_LABELS[job.progress_stage] || job.progress_stage || ""}</span>
                            <span>{job.progress ?? 0}%</span>
                          </div>
                          <div style={{ background: "#1f2937", borderRadius: 3, height: 4, width: 140 }}>
                            <div style={{ background: "#6366f1", borderRadius: 3, height: 4, width: `${job.progress ?? 0}%`, transition: "width 0.5s" }} />
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
                        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                          {onLoad && (
                            <button onClick={() => onLoad(job)} style={btnPrimary}>View</button>
                          )}
                          {job.video_path && (
                            <a href={`${API}${job.video_path}`} download style={linkStyle}>Video</a>
                          )}
                          {job.package_path && (
                            <a href={`${API}${job.package_path}`} download style={linkStyle}>ZIP</a>
                          )}
                          {job.data_csv_path && (
                            <a href={`${API}${job.data_csv_path}`} download style={linkStyle}>CSV</a>
                          )}
                        </div>
                      )}
                    </td>
                    <td style={td}>
                      {isActive ? (
                        <button onClick={() => handleCancel(job.job_id)} style={btnCancel}>
                          Cancel
                        </button>
                      ) : (
                        <button onClick={() => handleDelete(job.job_id)} style={btnDelete}>
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
      </details>
    </div>
  );
}

const summaryStyle = {
  cursor: "pointer", fontWeight: 600, fontSize: "1rem", color: "#e5e7eb",
  userSelect: "none", marginBottom: "1rem", listStyle: "none",
  display: "flex", alignItems: "center", gap: "0.5rem",
};
const badgeStyle = {
  background: "#1f2937", borderRadius: "999px", padding: "1px 8px",
  fontSize: "0.75rem", color: "#9ca3af",
};
const th = { padding: "6px 10px" };
const td = { padding: "8px 10px" };

const linkStyle = {
  color: "#6366f1", textDecoration: "none", border: "1px solid #4f46e5",
  borderRadius: 5, padding: "2px 7px", fontSize: "0.8rem",
};
const btnPrimary = {
  background: "#6366f1", color: "#fff", border: "none", borderRadius: 5,
  padding: "2px 10px", fontSize: "0.8rem", cursor: "pointer", fontWeight: 600,
};
const btnCancel = {
  background: "none", border: "1px solid #ef4444", borderRadius: 6,
  color: "#ef4444", cursor: "pointer", padding: "3px 8px", fontSize: "0.8rem",
};
const btnDelete = {
  background: "none", border: "1px solid #374151", borderRadius: 6,
  color: "#9ca3af", cursor: "pointer", padding: "3px 8px", fontSize: "0.8rem",
};
