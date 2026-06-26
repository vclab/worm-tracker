import { useState, useEffect, useMemo } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, Cell, ErrorBar,
} from "recharts";
import { API } from "./api";

const HEAD_COLOR  = "#e74c3c";
const MID_COLOR   = "#3498db";
const TAIL_COLOR  = "#2ecc71";
const CLASS_COLOR = "#5dade2";
const YOLO_COLOR  = "#e59866";

function shorten(name, maxLen = 22) {
  const dot = name.lastIndexOf(".");
  const stem = dot > 0 ? name.slice(0, dot) : name;
  return stem.length > maxLen ? stem.slice(0, maxLen) + "…" : stem;
}

function pipelineOpacity(pipeline) { return pipeline === "dl" ? 0.40 : 0.85; }
function pipelineStroke(pipeline)  { return pipeline === "dl" ? 1.5  : 0;    }

const TOOLTIP_STYLE = {
  contentStyle: { background: "#1c1f23", border: "0.5px solid #2c3036", borderRadius: 8, fontSize: 11 },
  labelStyle:   { color: "#e8eaed" },
  itemStyle:    { color: "#9aa0a6" },
};

// ── Single-video drill-down ───────────────────────────────────────────────────
const PIPELINE_LABEL = { classical: "Classical", dl: "YOLO" };
const PIPELINE_COLOR = { classical: CLASS_COLOR, dl: YOLO_COLOR };

function SingleVideoChart({ perWorm, perVideo }) {
  // Derive which pipelines actually have data so we never default to an empty one.
  const availablePipelines = useMemo(
    () => new Set(perVideo.map(r => r.pipeline)),
    [perVideo],
  );

  const [selectedPipeline, setSelectedPipeline] = useState(() =>
    availablePipelines.has("dl") ? "dl" : "classical"
  );

  const filteredVideos = useMemo(() => {
    const seen = new Set();
    return perVideo
      .filter(r => r.pipeline === selectedPipeline)
      .filter(r => { const k = r.filename; if (seen.has(k)) return false; seen.add(k); return true; })
      .map(r => r.filename);
  }, [perVideo, selectedPipeline]);

  const [selected, setSelected] = useState(() => filteredVideos[0] ?? "");

  // When pipeline changes, filteredVideos changes — reset selected to first in new list.
  useEffect(() => {
    if (filteredVideos.length && !filteredVideos.includes(selected)) {
      setSelected(filteredVideos[0]);
    } else if (!filteredVideos.length) {
      setSelected("");
    }
  }, [filteredVideos]); // eslint-disable-line react-hooks/exhaustive-deps

  const drillData = useMemo(() => {
    if (!selected) return [];
    return perWorm
      .filter(w => w.filename === selected && w.pipeline === selectedPipeline)
      .sort((a, b) => a.worm_id - b.worm_id)
      .map(w => ({
        worm:    `W${Math.round(w.worm_id)}`,
        head:    w.head,
        midbody: w.midbody,
        tail:    w.tail,
      }));
  }, [perWorm, selected, selectedPipeline]);

  const accentColor = PIPELINE_COLOR[selectedPipeline] ?? CLASS_COLOR;

  console.log("[SingleVideoChart] selectedPipeline:", selectedPipeline, "| filteredVideos.length:", filteredVideos.length);

  return (
    <div style={{ width: "100%" }}>
      {/* Pipeline toggle */}
      <div style={{ display: "flex", gap: 6, marginBottom: 12 }}>
        {["classical", "dl"].map(pl => {
          const active = pl === selectedPipeline;
          const color  = PIPELINE_COLOR[pl];
          return (
            <button
              key={pl}
              onClick={() => setSelectedPipeline(pl)}
              style={{
                padding: "4px 14px", fontSize: 12, borderRadius: 6, cursor: "pointer",
                border: `0.5px solid ${active ? color : "var(--border)"}`,
                background: active ? `${color}26` : "transparent",
                color: active ? color : "var(--text-muted)",
              }}
            >
              {PIPELINE_LABEL[pl]}
            </button>
          );
        })}
      </div>

      {filteredVideos.length === 0 ? (
        <div style={{ color: "#6b7280", fontSize: 12 }}>No videos for this pipeline.</div>
      ) : (
        <>
          <div style={{ marginBottom: 10 }}>
            <select
              value={selected}
              onChange={e => setSelected(e.target.value)}
              style={{
                background: "var(--bg)", color: "var(--text-primary)",
                border: `0.5px solid ${accentColor}`, borderRadius: 8,
                padding: "6px 10px", fontSize: 12, cursor: "pointer",
              }}
            >
              {filteredVideos.map(v => <option key={v} value={v}>{shorten(v, 40)}</option>)}
            </select>
          </div>
          {drillData.length === 0 ? (
            <div style={{ color: "#6b7280", fontSize: 12 }}>No worm data for this video.</div>
          ) : (
            <ResponsiveContainer width="100%" height={380}>
              <BarChart data={drillData} margin={{ top: 50, right: 20, left: 60, bottom: 50 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#2c3036" />
                <XAxis
                  dataKey="worm"
                  tick={{ fill: "#9ca3af", fontSize: 13 }}
                  label={{ value: "Worm ID", position: "insideBottom", fill: "#6b7280", fontSize: 14, dy: 18 }}
                />
                <YAxis
                  tick={{ fill: "#9ca3af", fontSize: 13 }}
                  label={{ value: "Motion (px/frame)", angle: -90, position: "insideLeft", fill: "#6b7280", fontSize: 14, dx: -2 }}
                />
                <Tooltip {...TOOLTIP_STYLE} />
                <Legend verticalAlign="top" wrapperStyle={{ fontSize: 11, paddingBottom: 6 }} />
                <Bar dataKey="head"    name="Head"    fill={HEAD_COLOR}  fillOpacity={0.85} />
                <Bar dataKey="midbody" name="Midbody" fill={MID_COLOR}   fillOpacity={0.85} />
                <Bar dataKey="tail"    name="Tail"    fill={TAIL_COLOR}  fillOpacity={0.85} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </>
      )}
    </div>
  );
}

// ── Comparison chart ──────────────────────────────────────────────────────────
function ComparisonChart({ results }) {
  const pipelines = new Set(results.map(r => r.pipeline));
  const hasMulti  = pipelines.size > 1;

  const data = results.map(r => ({
    label:    `${r.group}${hasMulti ? ` (${r.pipeline === "dl" ? "YOLO" : "Classical"})` : ""} (n=${r.n})`,
    pipeline: r.pipeline,
    n:        r.n,
    head:     r.head_mean,
    head_err: r.head_std,
    mid:      r.midbody_mean,
    mid_err:  r.midbody_std,
    tail:     r.tail_mean,
    tail_err: r.tail_std,
  }));

  const makeCells = (color) => data.map((entry, i) => (
    <Cell
      key={i}
      fill={color}
      fillOpacity={pipelineOpacity(entry.pipeline)}
      stroke={color}
      strokeWidth={pipelineStroke(entry.pipeline)}
    />
  ));

  return (
    <ResponsiveContainer width="100%" height={380}>
      <BarChart data={data} margin={{ top: 50, right: 20, left: 60, bottom: 20 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#2c3036" />
        <XAxis
          dataKey="label"
          tick={{ fill: "#9ca3af", fontSize: 13 }}
          tickFormatter={(v) => v.length > 18 ? v.slice(0, 17) + "…" : v}
          angle={-30}
          textAnchor="end"
          interval={0}
          height={100}
        />
        <YAxis
          tick={{ fill: "#9ca3af", fontSize: 13 }}
          label={{ value: "Mean motion (px/frame)", angle: -90, position: "insideLeft", fill: "#6b7280", fontSize: 14, dx: -2 }}
        />
        <Tooltip {...TOOLTIP_STYLE} />
        <Legend verticalAlign="top" wrapperStyle={{ fontSize: 11, paddingBottom: 6 }} />
        <Bar dataKey="head" name="Head" fill={HEAD_COLOR}>
          {makeCells(HEAD_COLOR)}
          <ErrorBar dataKey="head_err" width={4} strokeWidth={1} stroke={HEAD_COLOR} direction="y" />
        </Bar>
        <Bar dataKey="mid" name="Midbody" fill={MID_COLOR}>
          {makeCells(MID_COLOR)}
          <ErrorBar dataKey="mid_err" width={4} strokeWidth={1} stroke={MID_COLOR} direction="y" />
        </Bar>
        <Bar dataKey="tail" name="Tail" fill={TAIL_COLOR}>
          {makeCells(TAIL_COLOR)}
          <ErrorBar dataKey="tail_err" width={4} strokeWidth={1} stroke={TAIL_COLOR} direction="y" />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

// ── Main MetricsPage ──────────────────────────────────────────────────────────
export default function MetricsPage() {
  const [data,         setData]         = useState(null);
  const [loading,      setLoading]      = useState(true);
  const [fetchError,   setFetchError]   = useState(null);

  // Comparison state
  const [keyword,      setKeyword]      = useState("");
  const [checkedIds,   setCheckedIds]   = useState(new Set());
  const [groupLabel,   setGroupLabel]   = useState("");
  const [groups,       setGroups]       = useState([]);
  const [cmpResult,    setCmpResult]    = useState(null);
  const [comparing,    setComparing]    = useState(false);
  const [cmpError,     setCmpError]     = useState(null);

  useEffect(() => {
    fetch(`${API}/api/aggregate`)
      .then(r => r.ok ? r.json() : Promise.reject(new Error(r.statusText)))
      .then(d  => { setData(d);   setLoading(false); })
      .catch(e => { setFetchError(e.message); setLoading(false); });
  }, []);

  // Keyword-filtered per_video rows for the checklist
  const matchedRows = useMemo(() => {
    if (!data) return [];
    const tokens = keyword.trim().toLowerCase().split(/\s+/).filter(Boolean);
    return data.per_video.filter(row => {
      if (!tokens.length) return true;
      const fn = row.filename.toLowerCase();
      return tokens.every(t => fn.includes(t));
    });
  }, [keyword, data]);

  // Reset all checkboxes to checked when the filter changes
  useEffect(() => {
    setCheckedIds(new Set(matchedRows.map(r => r.job_id)));
  }, [matchedRows]);

  const matchedPipelines  = useMemo(() => new Set(matchedRows.map(r => r.pipeline)), [matchedRows]);
  const hasMixedPipelines = matchedPipelines.size > 1;

  const toggleCheck = (jobId) => setCheckedIds(prev => {
    const next = new Set(prev);
    next.has(jobId) ? next.delete(jobId) : next.add(jobId);
    return next;
  });

  const addGroup = () => {
    const label    = groupLabel.trim();
    const job_ids  = [...checkedIds];
    if (!label || !job_ids.length) return;
    setGroups(prev => [...prev, { label, job_ids }]);
    setGroupLabel("");
    setKeyword("");
    setCmpResult(null);
  };

  const removeGroup = (i) => {
    setGroups(prev => prev.filter((_, j) => j !== i));
    setCmpResult(null);
  };

  const compute = async () => {
    if (!groups.length) return;
    setComparing(true);
    setCmpError(null);
    try {
      const res = await fetch(`${API}/api/compare`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ groups }),
      });
      if (!res.ok) throw new Error(await res.text());
      setCmpResult(await res.json());
    } catch (e) {
      setCmpError(e.message);
    } finally {
      setComparing(false);
    }
  };

  if (loading) {
    return <div className="card" style={{ color: "var(--text-secondary)", fontSize: "0.875rem" }}>Loading metrics…</div>;
  }
  if (fetchError) {
    return <div className="card" style={{ color: "#ef4444", fontSize: "0.875rem" }}>Error: {fetchError}</div>;
  }
  if (!data || (!data.per_video.length && !data.per_worm.length)) {
    return (
      <div className="card">
        <p style={{ color: "var(--text-secondary)", fontSize: "0.875rem", margin: 0 }}>
          No completed jobs found. Process some videos first, then reload this page.
        </p>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>

      {/* ── Section 1: Condition comparison ── */}
      <div className="card card--wide">
        <h2 style={{ margin: "0 0 4px", fontSize: 16, fontWeight: 600, color: "#e5e7eb" }}>
          Condition comparison
        </h2>
        <p style={{ margin: "0 0 16px", fontSize: 12, color: "#6b7280" }}>
          Group your videos by experimental condition to compare worm motion across groups.
          Type a keyword to find matching videos, confirm which ones belong in the group, label it,
          then add more groups and compute. The chart shows each group's average head, midbody, and
          tail motion. The error bars show how much individual worms varied within the group — short
          bars mean the worms moved similarly, long bars mean they were spread out — and n is the
          number of worms in each group.
        </p>

        {/* Keyword filter */}
        <div style={{ marginBottom: 10 }}>
          <input
            type="text"
            placeholder="Filter videos by keyword (space-separated tokens, all must match)…"
            value={keyword}
            onChange={e => setKeyword(e.target.value)}
            style={{
              width: "100%", background: "var(--bg)", color: "var(--text-primary)",
              border: "0.5px solid var(--border)", borderRadius: 8, padding: "8px 12px",
              fontSize: 13, outline: "none", boxSizing: "border-box",
            }}
          />
        </div>

        {/* Mixed-pipeline warning */}
        {hasMixedPipelines && matchedRows.length > 0 && (
          <div style={{
            background: "#1c1108", border: "1px solid #d97706", borderRadius: 8,
            padding: "8px 12px", marginBottom: 10, fontSize: 12, color: "#fbbf24",
            display: "flex", gap: 8, alignItems: "flex-start",
          }}>
            <span style={{ flexShrink: 0 }}>⚠</span>
            <span>
              Matched set spans both pipelines (Classical + YOLO).
              Stats will be reported per pipeline — they are never blended.
            </span>
          </div>
        )}

        {/* Checklist */}
        {matchedRows.length > 0 ? (
          <div style={{
            background: "var(--bg)", border: "0.5px solid var(--border)", borderRadius: 8,
            marginBottom: 12, maxHeight: 220, overflowY: "auto",
          }}>
            {matchedRows.map(row => (
              <label
                key={row.job_id}
                style={{
                  display: "flex", alignItems: "center", gap: 10,
                  padding: "7px 12px", cursor: "pointer",
                  borderBottom: "0.5px solid var(--border)", fontSize: 12,
                }}
              >
                <input
                  type="checkbox"
                  checked={checkedIds.has(row.job_id)}
                  onChange={() => toggleCheck(row.job_id)}
                  style={{ cursor: "pointer", flexShrink: 0 }}
                />
                <span style={{ flex: 1, color: "var(--text-primary)", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {shorten(row.filename, 50)}
                </span>
                <span style={{
                  background: row.pipeline === "dl" ? "rgba(229,152,102,0.15)" : "rgba(93,173,226,0.15)",
                  color:      row.pipeline === "dl" ? YOLO_COLOR               : CLASS_COLOR,
                  padding: "2px 7px", borderRadius: 4, fontSize: 10, flexShrink: 0,
                }}>
                  {row.pipeline === "dl" ? "YOLO" : "Classical"}
                </span>
                <span style={{ color: "var(--text-muted)", flexShrink: 0 }}>{row.worm_count} worms</span>
              </label>
            ))}
          </div>
        ) : (
          <div style={{ color: "var(--text-muted)", fontSize: 12, marginBottom: 12 }}>
            {keyword.trim() ? "No videos match this keyword." : "No completed videos available."}
          </div>
        )}

        {/* Group label + add */}
        <div style={{ display: "flex", gap: 8, marginBottom: 16, alignItems: "center" }}>
          <input
            type="text"
            placeholder="Group label…"
            value={groupLabel}
            onChange={e => setGroupLabel(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter") addGroup(); }}
            style={{
              flex: 1, background: "var(--bg)", color: "var(--text-primary)",
              border: "0.5px solid var(--border)", borderRadius: 8, padding: "8px 12px",
              fontSize: 13, outline: "none",
            }}
          />
          <button
            className="btn"
            onClick={addGroup}
            disabled={!groupLabel.trim() || checkedIds.size === 0}
            style={(!groupLabel.trim() || checkedIds.size === 0) ? { opacity: 0.38, cursor: "not-allowed" } : {}}
          >
            Add group ({checkedIds.size})
          </button>
        </div>

        {/* Groups list + compute */}
        {groups.length > 0 && (
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.05em" }}>
              Comparison groups
            </div>
            {groups.map((g, i) => (
              <div
                key={i}
                style={{
                  display: "flex", alignItems: "center", gap: 8,
                  padding: "6px 10px", marginBottom: 4,
                  background: "var(--bg)", border: "0.5px solid var(--border)",
                  borderRadius: 6, fontSize: 12,
                }}
              >
                <span style={{ flex: 1, color: "var(--text-primary)" }}>
                  <strong>{g.label}</strong>
                  <span style={{ color: "var(--text-muted)", marginLeft: 8 }}>
                    {g.job_ids.length} job{g.job_ids.length !== 1 ? "s" : ""}
                  </span>
                </span>
                <button
                  onClick={() => removeGroup(i)}
                  style={{
                    background: "none", border: "none", color: "var(--text-muted)",
                    cursor: "pointer", fontSize: 14, padding: "0 4px", lineHeight: 1,
                  }}
                >✕</button>
              </div>
            ))}
            <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
              <button
                className="btn"
                onClick={compute}
                disabled={comparing}
                style={comparing ? { opacity: 0.5 } : {}}
              >
                {comparing ? "Computing…" : "Compute comparison"}
              </button>
              <button
                className="btn"
                onClick={() => { setGroups([]); setCmpResult(null); setCmpError(null); }}
                style={{ background: "rgba(239,68,68,0.1)", borderColor: "rgba(239,68,68,0.3)", color: "#fca5a5" }}
              >
                Clear all
              </button>
            </div>
          </div>
        )}

        {cmpError && (
          <div style={{ color: "#ef4444", fontSize: 12, marginTop: 8 }}>{cmpError}</div>
        )}

        {cmpResult && cmpResult.results.length > 0 && (
          <div style={{ marginTop: 16, width: "100%" }}>
            <h3 style={{ margin: "0 0 12px", fontSize: 13, fontWeight: 600, color: "#d1d5db" }}>
              Comparison results
            </h3>
            <ComparisonChart results={cmpResult.results} />
          </div>
        )}

        {cmpResult && cmpResult.results.length === 0 && (
          <div style={{ color: "#9ca3af", fontSize: 12, marginTop: 8 }}>
            No matching data found for the selected groups.
          </div>
        )}
      </div>

      {/* ── Section 2: Single video analysis ── */}
      <div className="card card--wide">
        <h2 style={{ margin: "0 0 4px", fontSize: 16, fontWeight: 600, color: "#e5e7eb" }}>
          Single video analysis
        </h2>
        <p style={{ margin: "0 0 16px", fontSize: 12, color: "#6b7280" }}>
          Pick one video to see its worms' motion broken down by body region. Each group of bars is one worm,
          showing how much its head, midbody, and tail moved on average (in pixels per frame).
        </p>
        <SingleVideoChart perWorm={data.per_worm} perVideo={data.per_video} />
      </div>

    </div>
  );
}
