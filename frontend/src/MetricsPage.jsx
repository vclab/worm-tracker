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

// ── Chart 1: Per-video grouped bar ────────────────────────────────────────────
function Chart1({ perVideo }) {
  const pipelines = useMemo(() => new Set(perVideo.map(r => r.pipeline)), [perVideo]);
  const hasMulti  = pipelines.size > 1;

  const data = useMemo(() => perVideo.map(r => ({
    label:    r.filename + (hasMulti ? ` (${r.pipeline === "dl" ? "YOLO" : "Classical"})` : ""),
    head:     r.head,
    midbody:  r.midbody,
    tail:     r.tail,
    pipeline: r.pipeline,
  })), [perVideo, hasMulti]);

  const makeCells = (color) => data.map((entry, i) => (
    <Cell
      key={i}
      fill={color}
      fillOpacity={pipelineOpacity(entry.pipeline)}
      stroke={color}
      strokeWidth={pipelineStroke(entry.pipeline)}
    />
  ));

  const legendPayload = [
    { value: "Head",    color: HEAD_COLOR,  type: "square" },
    { value: "Midbody", color: MID_COLOR,   type: "square" },
    { value: "Tail",    color: TAIL_COLOR,  type: "square" },
    ...(hasMulti ? [
      { value: "Classical (solid)", color: "#9ca3af", type: "square" },
      { value: "YOLO (light)",      color: "#9ca3af", type: "square" },
    ] : []),
  ];

  if (!data.length) return <div style={{ color: "#6b7280", fontSize: 12 }}>No data.</div>;

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
          label={{ value: "Avg motion (px/frame)", angle: -90, position: "insideLeft", fill: "#6b7280", fontSize: 14, dx: -2 }}
        />
        <Tooltip {...TOOLTIP_STYLE} />
        <Legend payload={legendPayload} verticalAlign="top" wrapperStyle={{ fontSize: 11, paddingBottom: 6 }} />
        <Bar dataKey="head"    name="Head"    fill={HEAD_COLOR}>{makeCells(HEAD_COLOR)}</Bar>
        <Bar dataKey="midbody" name="Midbody" fill={MID_COLOR}> {makeCells(MID_COLOR)}</Bar>
        <Bar dataKey="tail"    name="Tail"    fill={TAIL_COLOR}>{makeCells(TAIL_COLOR)}</Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

// ── Chart 2: Box + strip (custom SVG) ─────────────────────────────────────────
function boxStats(vals) {
  if (!vals.length) return null;
  const s = [...vals].sort((a, b) => a - b);
  const n = s.length;
  const q1  = s[Math.max(0, Math.floor(n * 0.25))];
  const q3  = s[Math.min(n - 1, Math.floor(n * 0.75))];
  const med = n % 2 === 1 ? s[Math.floor(n / 2)] : (s[n / 2 - 1] + s[n / 2]) / 2;
  const iqr = q3 - q1;
  const lo  = Math.max(s[0],     q1 - 1.5 * iqr);
  const hi  = Math.min(s[n - 1], q3 + 1.5 * iqr);
  return { q1, q3, med, lo, hi };
}

function jitter(seed, range) {
  const x = Math.abs(Math.sin(seed * 9301 + 49297) * 233280);
  return (x % 1 - 0.5) * range;
}

function Chart2({ perWorm, perVideo }) {
  const videoOrder = useMemo(() => {
    const seen = new Set();
    const out  = [];
    for (const r of perVideo) {
      if (!seen.has(r.filename)) { seen.add(r.filename); out.push(r.filename); }
    }
    return out;
  }, [perVideo]);

  const groups = useMemo(() => {
    const g = {};
    for (const w of perWorm) {
      const key = `${w.filename}|||${w.pipeline}`;
      if (!g[key]) g[key] = { filename: w.filename, pipeline: w.pipeline, values: [] };
      g[key].values.push(w.overall);
    }
    return g;
  }, [perWorm]);

  const perFilenameCount = useMemo(() => {
    const c = {};
    for (const { filename } of Object.values(groups)) c[filename] = (c[filename] || 0) + 1;
    return c;
  }, [groups]);

  const n   = videoOrder.length;
  const SVW = Math.max(540, n * 100);
  const SVH = 360;
  const ML = 60, MR = 24, MT = 16, MB = 110;
  const IW  = SVW - ML - MR;
  const IH  = SVH - MT - MB;

  const allY   = perWorm.map(w => w.overall);
  const dMin   = Math.min(...allY);
  const dMax   = Math.max(...allY);
  const pad    = Math.max((dMax - dMin) * 0.15, 1);
  const yLo    = dMin - pad;
  const yHi    = dMax + pad;
  const xStep  = IW / n;
  const xPos   = (i)  => ML + xStep * i + xStep / 2;
  const yPos   = (v)  => MT + IH * (1 - (v - yLo) / (yHi - yLo));

  const yTickVals = Array.from({ length: 6 }, (_, i) => yLo + (yHi - yLo) * i / 5);

  const boxes = Object.entries(groups).map(([key, grp]) => {
    const vi  = videoOrder.indexOf(grp.filename);
    if (vi === -1) return null;
    const isMixed = perFilenameCount[grp.filename] > 1;
    const off  = isMixed ? (grp.pipeline === "dl" ? 14 : -14) : 0;
    const cx   = xPos(vi) + off;
    const col  = grp.pipeline === "dl" ? YOLO_COLOR : CLASS_COLOR;
    const st   = boxStats(grp.values);
    const bw   = 18;
    return (
      <g key={key}>
        <line x1={cx} y1={yPos(st.hi)} x2={cx}      y2={yPos(st.lo)} stroke={col} strokeWidth={1.2} opacity={0.55} />
        <line x1={cx - 4} y1={yPos(st.hi)} x2={cx + 4} y2={yPos(st.hi)} stroke={col} strokeWidth={1.2} opacity={0.55} />
        <line x1={cx - 4} y1={yPos(st.lo)} x2={cx + 4} y2={yPos(st.lo)} stroke={col} strokeWidth={1.2} opacity={0.55} />
        <rect
          x={cx - bw / 2} y={yPos(st.q3)}
          width={bw} height={Math.max(1, yPos(st.q1) - yPos(st.q3))}
          fill={col} fillOpacity={0.2} stroke={col} strokeWidth={1}
        />
        <line x1={cx - bw / 2} y1={yPos(st.med)} x2={cx + bw / 2} y2={yPos(st.med)} stroke={col} strokeWidth={2} />
        {grp.values.map((v, i) => (
          <circle
            key={i}
            cx={cx + jitter(i + vi * 37 + (grp.pipeline === "dl" ? 999 : 0), 11)}
            cy={yPos(v)}
            r={3}
            fill={col}
            opacity={0.55}
          />
        ))}
      </g>
    );
  }).filter(Boolean);

  if (!perWorm.length) return <div style={{ color: "#6b7280", fontSize: 12 }}>No data.</div>;

  return (
    <div style={{ overflowX: "auto" }}>
      <svg width={SVW} height={SVH} style={{ fontFamily: "inherit", display: "block" }}>
        {/* grid + y-axis */}
        <line x1={ML} y1={MT} x2={ML} y2={MT + IH} stroke="#2c3036" />
        {yTickVals.map((v, i) => (
          <g key={i}>
            <line x1={ML - 4} y1={yPos(v)} x2={ML}       y2={yPos(v)} stroke="#2c3036" />
            <line x1={ML}     y1={yPos(v)} x2={ML + IW}   y2={yPos(v)} stroke="#2c3036" />
            <text x={ML - 8} y={yPos(v)} textAnchor="end" dominantBaseline="middle" fill="#9aa0a6" fontSize={13}>
              {v.toFixed(1)}
            </text>
          </g>
        ))}
        {/* x-axis */}
        <line x1={ML} y1={MT + IH} x2={ML + IW} y2={MT + IH} stroke="#2c3036" />
        {videoOrder.map((vid, i) => (
          <g key={i} transform={`translate(${xPos(i)},${MT + IH + 4})`}>
            <title>{vid}</title>
            <text transform="rotate(-30)" textAnchor="end" fill="#9aa0a6" fontSize={13}>
              {shorten(vid, 18)}
            </text>
          </g>
        ))}
        {/* axis label */}
        <text
          transform={`translate(14,${MT + IH / 2}) rotate(-90)`}
          textAnchor="middle" fill="#6b7178" fontSize={14}
        >
          Overall motion (px/frame)
        </text>
        {/* boxes + strips */}
        {boxes}
        {/* legend */}
        <g transform={`translate(${ML + IW - 106},${MT + 4})`}>
          <rect x={0} y={0}  width={10} height={10} fill={CLASS_COLOR} opacity={0.85} />
          <text x={14} y={9}  fill="#9aa0a6" fontSize={10}>Classical</text>
          <rect x={0} y={16} width={10} height={10} fill={YOLO_COLOR}  opacity={0.85} />
          <text x={14} y={25} fill="#9aa0a6" fontSize={10}>YOLO (dl)</text>
        </g>
      </svg>
    </div>
  );
}

// ── Chart 3: Single-video drill-down ─────────────────────────────────────────
function Chart3({ perWorm, perVideo }) {
  const videos = useMemo(() => {
    const seen = new Set();
    return perVideo.filter(r => { const k = r.filename; if (seen.has(k)) return false; seen.add(k); return true; }).map(r => r.filename);
  }, [perVideo]);

  const [selected, setSelected] = useState(() => videos[0] ?? "");

  useEffect(() => {
    if (videos.length && !videos.includes(selected)) setSelected(videos[0]);
  }, [videos]);  // eslint-disable-line react-hooks/exhaustive-deps

  const drillData = useMemo(() => {
    return perWorm
      .filter(w => w.filename === selected)
      .sort((a, b) => a.worm_id - b.worm_id)
      .map(w => ({
        worm:     `W${Math.round(w.worm_id)}`,
        head:     w.head,
        midbody:  w.midbody,
        tail:     w.tail,
        pipeline: w.pipeline,
      }));
  }, [perWorm, selected]);

  const pipeline = drillData[0]?.pipeline ?? "";

  return (
    <div style={{ width: "100%" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
        <select
          value={selected}
          onChange={e => setSelected(e.target.value)}
          style={{
            background: "var(--bg)", color: "var(--text-primary)",
            border: "0.5px solid var(--border)", borderRadius: 8,
            padding: "6px 10px", fontSize: 12, cursor: "pointer",
          }}
        >
          {videos.map(v => <option key={v} value={v}>{shorten(v, 40)}</option>)}
        </select>
        {pipeline && (
          <span style={{ fontSize: 11, color: "#6b7280" }}>
            pipeline: {pipeline === "dl" ? "YOLO" : "Classical"}
          </span>
        )}
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

      {/* ── Section 1: Per-video charts ── */}
      <div className="card card--wide">
        <h2 style={{ margin: "0 0 4px", fontSize: 16, fontWeight: 600, color: "#e5e7eb" }}>
          Per-video analysis
        </h2>
        <p style={{ margin: "0 0 22px", fontSize: 12, color: "#6b7280" }}>
          Solid bars = Classical pipeline · Semi-transparent with border = YOLO (dl) pipeline
        </p>

        {/* Chart 1 */}
        <div style={{ marginBottom: 28 }}>
          <h3 style={{ margin: "0 0 6px", fontSize: 13, fontWeight: 600, color: "#d1d5db" }}>
            Average motion by body region
          </h3>
          <Chart1 perVideo={data.per_video} />
        </div>

        {/* Chart 2 */}
        <div style={{ marginBottom: 28 }}>
          <h3 style={{ margin: "0 0 6px", fontSize: 13, fontWeight: 600, color: "#d1d5db" }}>
            Per-worm overall motion distribution (box + strip)
          </h3>
          <Chart2 perWorm={data.per_worm} perVideo={data.per_video} />
        </div>

        {/* Chart 3 */}
        <div style={{ width: "100%" }}>
          <h3 style={{ margin: "0 0 6px", fontSize: 13, fontWeight: 600, color: "#d1d5db" }}>
            Single-video drill-down
          </h3>
          <Chart3 perWorm={data.per_worm} perVideo={data.per_video} />
        </div>
      </div>

      {/* ── Section 2: Condition comparison ── */}
      <div className="card card--wide">
        <h2 style={{ margin: "0 0 4px", fontSize: 16, fontWeight: 600, color: "#e5e7eb" }}>
          Condition comparison
        </h2>
        <p style={{ margin: "0 0 16px", fontSize: 12, color: "#6b7280" }}>
          Filter by keyword to build a checked list, label the group, and add it.
          Repeat for each condition, then compute. Pipelines are never blended.
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
            <h3 style={{ margin: "0 0 4px", fontSize: 13, fontWeight: 600, color: "#d1d5db" }}>
              Comparison results
            </h3>
            <p style={{ margin: "0 0 12px", fontSize: 11, color: "#6b7280" }}>
              Error bars = ±1 std across worms · n = worm count per group/pipeline
              {new Set(cmpResult.results.map(r => r.pipeline)).size > 1 &&
                " · Solid = Classical · Semi-transparent = YOLO"}
            </p>
            <ComparisonChart results={cmpResult.results} />
          </div>
        )}

        {cmpResult && cmpResult.results.length === 0 && (
          <div style={{ color: "#9ca3af", fontSize: 12, marginTop: 8 }}>
            No matching data found for the selected groups.
          </div>
        )}
      </div>
    </div>
  );
}
