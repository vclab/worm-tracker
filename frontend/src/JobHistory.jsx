import { useState, useEffect, useRef } from "react";

const API = "http://127.0.0.1:8000";

const STATUS_STYLES = {
  done: { color: "#10b981", label: "Done" },
  running: { color: "#6366f1", label: "Running" },
  error: { color: "#ef4444", label: "Error" },
  cancelled: { color: "#9ca3af", label: "Cancelled" },
};

function formatDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString();
}

export default function JobHistory({ refreshKey = 0 }) {
  const [jobs, setJobs] = useState([]);
  const [open, setOpen] = useState(false);
  const pollRef = useRef(null);

  async function fetchJobs() {
    try {
      const res = await fetch(`${API}/jobs`);
      if (res.ok) setJobs(await res.json());
    } catch {
      // Server offline — ignore
    }
  }

  useEffect(() => {
    if (refreshKey > 0) {
      fetchJobs().then(() => setOpen(true));
    } else {
      fetchJobs();
    }
  }, [refreshKey]);

  // Poll while any job is running
  useEffect(() => {
    const hasRunning = jobs.some((j) => j.status === "running");
    if (hasRunning && !pollRef.current) {
      pollRef.current = setInterval(fetchJobs, 10000);
    } else if (!hasRunning && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [jobs]);

  async function handleDelete(jobId) {
    if (!confirm("Delete this job and all its output files?")) return;
    await fetch(`${API}/jobs/${jobId}`, { method: "DELETE" });
    fetchJobs();
  }

  if (jobs.length === 0) return null;

  return (
    <div style={{ marginTop: "2rem" }}>
      <details open={open} onToggle={(e) => setOpen(e.target.open)}>
        <summary
          style={{
            cursor: "pointer",
            fontWeight: 600,
            fontSize: "1rem",
            color: "#e5e7eb",
            userSelect: "none",
            marginBottom: "1rem",
            listStyle: "none",
            display: "flex",
            alignItems: "center",
            gap: "0.5rem",
          }}
        >
          <span style={{ fontSize: "0.85rem", color: "#9ca3af" }}>{open ? "▾" : "▸"}</span>
          Job History
          <span
            style={{
              background: "#1f2937",
              borderRadius: "999px",
              padding: "1px 8px",
              fontSize: "0.75rem",
              color: "#9ca3af",
            }}
          >
            {jobs.length}
          </span>
        </summary>

        <div style={{ overflowX: "auto" }}>
          <table
            style={{
              width: "100%",
              borderCollapse: "collapse",
              fontSize: "0.85rem",
              color: "#e5e7eb",
            }}
          >
            <thead>
              <tr style={{ borderBottom: "1px solid #1f2937", color: "#9ca3af", textAlign: "left" }}>
                <th style={{ padding: "6px 10px" }}>Date</th>
                <th style={{ padding: "6px 10px" }}>File</th>
                <th style={{ padding: "6px 10px" }}>Name</th>
                <th style={{ padding: "6px 10px" }}>Status</th>
                <th style={{ padding: "6px 10px" }}>Downloads</th>
                <th style={{ padding: "6px 10px" }}></th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => {
                const s = STATUS_STYLES[job.status] || STATUS_STYLES.cancelled;
                return (
                  <tr key={job.job_id} style={{ borderBottom: "1px solid #1f2937" }}>
                    <td style={{ padding: "8px 10px", whiteSpace: "nowrap", color: "#9ca3af" }}>
                      {formatDate(job.created_at)}
                    </td>
                    <td style={{ padding: "8px 10px", maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {job.original_filename || "—"}
                    </td>
                    <td style={{ padding: "8px 10px" }}>{job.output_name || "—"}</td>
                    <td style={{ padding: "8px 10px" }}>
                      <span
                        style={{
                          color: s.color,
                          fontWeight: 600,
                          fontSize: "0.8rem",
                          textTransform: "uppercase",
                          letterSpacing: "0.05em",
                        }}
                      >
                        {s.label}
                      </span>
                      {job.error_msg && (
                        <div style={{ color: "#ef4444", fontSize: "0.75rem", marginTop: 2 }}>
                          {job.error_msg}
                        </div>
                      )}
                    </td>
                    <td style={{ padding: "8px 10px" }}>
                      {job.status === "done" && (
                        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                          {job.video_path && (
                            <a href={`${API}${job.video_path}`} download style={linkStyle}>
                              Video
                            </a>
                          )}
                          {job.package_path && (
                            <a href={`${API}${job.package_path}`} download style={linkStyle}>
                              ZIP
                            </a>
                          )}
                          {job.data_csv_path && (
                            <a href={`${API}${job.data_csv_path}`} download style={linkStyle}>
                              CSV
                            </a>
                          )}
                        </div>
                      )}
                    </td>
                    <td style={{ padding: "8px 10px" }}>
                      {job.status !== "running" && (
                        <button
                          onClick={() => handleDelete(job.job_id)}
                          style={{
                            background: "none",
                            border: "1px solid #374151",
                            borderRadius: 6,
                            color: "#9ca3af",
                            cursor: "pointer",
                            padding: "3px 8px",
                            fontSize: "0.8rem",
                          }}
                        >
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

const linkStyle = {
  color: "#6366f1",
  textDecoration: "none",
  border: "1px solid #4f46e5",
  borderRadius: 5,
  padding: "2px 7px",
  fontSize: "0.8rem",
};
