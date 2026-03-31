import { useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";

function InfoTooltip({ text }) {
  return (
    <span className="info-tooltip-wrapper">
      <span className="info-icon">ⓘ</span>
      <span className="info-tooltip-text">{text}</span>
    </span>
  );
}

function MotionCharts({ data }) {
  const [selectedWorm, setSelectedWorm] = useState(null);
  const [hoveredMotion, setHoveredMotion] = useState(null);
  const [hoveredRolling, setHoveredRolling] = useState(null);

  if (!data || !data.worm_ids || data.worm_ids.length === 0) return null;

  // Initialize selected worm to first one
  const activeWorm = selectedWorm !== null ? selectedWorm : data.worm_ids[0];

  // Get max values for heatmap scaling
  const maxOverall = Math.max(...data.per_worm_motion);
  const maxHead = Math.max(...data.per_worm_head_motion);
  const maxTail = Math.max(...data.per_worm_tail_motion);
  const maxMid = Math.max(...(data.per_worm_mid_motion || [0]));
  const globalMax = Math.max(maxOverall, maxHead, maxTail, maxMid);

  // Color scale function (0 to 1) -> color
  const getColor = (value, max) => {
    const intensity = max > 0 ? value / max : 0;
    // Dark blue to bright cyan gradient
    const r = Math.round(20 + intensity * 30);
    const g = Math.round(40 + intensity * 180);
    const b = Math.round(80 + intensity * 175);
    return `rgb(${r}, ${g}, ${b})`;
  };

  // Prepare time series data for selected worm
  const getTimeSeriesData = () => {
    if (!data.per_frame_motion || !data.per_frame_motion[activeWorm]) {
      return [];
    }
    const wormData = data.per_frame_motion[activeWorm];
    const headData = wormData.head || [];
    const tailData = wormData.tail || [];
    const midData = wormData.mid || [];
    const windowSize = wormData.window_size || 1;

    return headData.map((head, i) => ({
      frame: i * windowSize,
      head: head,
      tail: tailData[i] || 0,
      mid: midData[i] || 0,
    }));
  };

  const timeSeriesData = getTimeSeriesData();

  // Compute rolling average with window size 10
  const getRollingAverageData = () => {
    if (timeSeriesData.length === 0) return [];
    const w = 10;
    return timeSeriesData.map((d, i) => {
      const start = Math.max(0, i - w + 1);
      const slice = timeSeriesData.slice(start, i + 1);
      const avgHead = slice.reduce((s, p) => s + p.head, 0) / slice.length;
      const avgTail = slice.reduce((s, p) => s + p.tail, 0) / slice.length;
      const avgMid = slice.reduce((s, p) => s + p.mid, 0) / slice.length;
      return { frame: d.frame, head: avgHead, tail: avgTail, mid: avgMid };
    });
  };

  const rollingData = getRollingAverageData();

  return (
    <div className="motion-analysis">
      <h3 className="motion-title">Motion Analysis</h3>
      <p className="motion-subtitle">
        Click a row to view timeline. {data.num_worms} worm(s) tracked.
      </p>

      {/* Heatmap */}
      <div className="heatmap-container">
        <div className="heatmap">
          {/* Header row */}
          <div className="heatmap-row heatmap-header">
            <div className="heatmap-label"></div>
            <div className="heatmap-cell-header">
              Overall
              <InfoTooltip text="Average displacement per keypoint per frame (px/frame). For each frame transition, the distance traveled by all 15 skeleton points is summed, then divided by (15 × number of frame transitions). Higher = more active worm." />
            </div>
            <div className="heatmap-cell-header">
              Head
              <InfoTooltip text="Average displacement of the head keypoint (keypoint 0, the wider end) per frame transition (px/frame). This is the mean of all frame-to-frame distances for the head point only." />
            </div>
            <div className="heatmap-cell-header">
              Mid
              <InfoTooltip text="Average displacement of the 3 middle keypoints per frame transition (px/frame). Represents midbody motion, smoothed by averaging across 3 adjacent skeleton points around the center." />
            </div>
            <div className="heatmap-cell-header">
              Tail
              <InfoTooltip text="Average displacement of the tail keypoint (last keypoint, the narrower end) per frame transition (px/frame). Same calculation as head but for the opposite end." />
            </div>
          </div>

          {/* Data rows */}
          {data.worm_ids.map((wormId, i) => (
            <div
              key={wormId}
              className={`heatmap-row ${activeWorm === wormId ? "selected" : ""}`}
              onClick={() => setSelectedWorm(wormId)}
            >
              <div className="heatmap-label">Worm {wormId}</div>
              <div
                className="heatmap-cell"
                style={{ backgroundColor: getColor(data.per_worm_motion[i], globalMax) }}
                title={`${data.per_worm_motion[i].toFixed(3)} px/frame`}
              >
                {data.per_worm_motion[i].toFixed(2)}
              </div>
              <div
                className="heatmap-cell"
                style={{ backgroundColor: getColor(data.per_worm_head_motion[i], globalMax) }}
                title={`${data.per_worm_head_motion[i].toFixed(3)} px/frame`}
              >
                {data.per_worm_head_motion[i].toFixed(2)}
              </div>
              <div
                className="heatmap-cell"
                style={{ backgroundColor: getColor((data.per_worm_mid_motion || [])[i] || 0, globalMax) }}
                title={`${((data.per_worm_mid_motion || [])[i] || 0).toFixed(3)} px/frame`}
              >
                {((data.per_worm_mid_motion || [])[i] || 0).toFixed(2)}
              </div>
              <div
                className="heatmap-cell"
                style={{ backgroundColor: getColor(data.per_worm_tail_motion[i], globalMax) }}
                title={`${data.per_worm_tail_motion[i].toFixed(3)} px/frame`}
              >
                {data.per_worm_tail_motion[i].toFixed(2)}
              </div>
            </div>
          ))}

          {/* Summary row */}
          <div className="heatmap-row heatmap-summary">
            <div className="heatmap-label">
              Mean
              <InfoTooltip text="Average and standard deviation across all tracked worms. Shows how similar or different the worms' activity levels are from each other — not an average across frames." />
            </div>
            <div className="heatmap-cell summary-cell">
              {data.mean_motion.toFixed(2)} <span className="std">±{data.std_motion.toFixed(2)}</span>
            </div>
            <div className="heatmap-cell summary-cell">
              {data.head_mean_motion.toFixed(2)} <span className="std">±{data.head_std_motion.toFixed(2)}</span>
            </div>
            <div className="heatmap-cell summary-cell">
              {(data.mid_mean_motion || 0).toFixed(2)} <span className="std">±{(data.mid_std_motion || 0).toFixed(2)}</span>
            </div>
            <div className="heatmap-cell summary-cell">
              {data.tail_mean_motion.toFixed(2)} <span className="std">±{data.tail_std_motion.toFixed(2)}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Time Series */}
      {timeSeriesData.length > 0 && (
        <>
          <div className="timeline-container">
            <h4 className="timeline-title">
              Worm {activeWorm} — Motion Over Time
              <InfoTooltip text="Frame-by-frame displacement of the head and tail keypoints. Each point represents the Euclidean distance that keypoint moved in one frame transition (or a windowed average if the video has many frames). Spikes indicate bursts of movement." />
            </h4>
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={timeSeriesData} margin={{ top: 10, right: 30, left: 10, bottom: 45 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                <XAxis
                  dataKey="frame"
                  stroke="#9ca3af"
                  tick={{ fontSize: 10 }}
                  label={{ value: "Frame", position: "insideBottom", offset: -5, fill: "#9ca3af", fontSize: 10 }}
                />
                <YAxis
                  stroke="#9ca3af"
                  tick={{ fontSize: 10 }}
                  label={{ value: "px/frame", angle: -90, position: "insideLeft", fill: "#9ca3af", fontSize: 10 }}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#1f2937",
                    border: "1px solid #374151",
                    borderRadius: "8px",
                  }}
                  formatter={(value) => [value.toFixed(3), ""]}
                  labelFormatter={(label) => `Frame ${label}`}
                />
                <Legend
                  wrapperStyle={{ fontSize: "12px", paddingTop: 16 }}
                  iconType="line"
                  onMouseEnter={(e) => setHoveredMotion(e.dataKey)}
                  onMouseLeave={() => setHoveredMotion(null)}
                />
                <Line
                  type="monotone"
                  dataKey="head"
                  stroke="#ef4444"
                  strokeWidth={1.5}
                  dot={false}
                  name="Head"
                  strokeOpacity={hoveredMotion && hoveredMotion !== "head" ? 0.1 : 1}
                />
                <Line
                  type="monotone"
                  dataKey="mid"
                  stroke="#10b981"
                  strokeWidth={1.5}
                  dot={false}
                  name="Mid"
                  strokeOpacity={hoveredMotion && hoveredMotion !== "mid" ? 0.1 : 1}
                />
                <Line
                  type="monotone"
                  dataKey="tail"
                  stroke="#3b82f6"
                  strokeWidth={1.5}
                  dot={false}
                  name="Tail"
                  strokeOpacity={hoveredMotion && hoveredMotion !== "tail" ? 0.1 : 1}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <div className="timeline-container">
            <h4 className="timeline-title">
              Worm {activeWorm} — Motion Trend (Rolling Average)
              <InfoTooltip text="Smoothed version of the timeline above using a rolling average (window of 10). Reduces noise to reveal overall activity trends over time." />
            </h4>
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={rollingData} margin={{ top: 10, right: 30, left: 10, bottom: 45 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                <XAxis
                  dataKey="frame"
                  stroke="#9ca3af"
                  tick={{ fontSize: 10 }}
                  label={{ value: "Frame", position: "insideBottom", offset: -5, fill: "#9ca3af", fontSize: 10 }}
                />
                <YAxis
                  stroke="#9ca3af"
                  tick={{ fontSize: 10 }}
                  label={{ value: "px/frame", angle: -90, position: "insideLeft", fill: "#9ca3af", fontSize: 10 }}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#1f2937",
                    border: "1px solid #374151",
                    borderRadius: "8px",
                  }}
                  formatter={(value) => [value.toFixed(3), ""]}
                  labelFormatter={(label) => `Frame ${label}`}
                />
                <Legend
                  wrapperStyle={{ fontSize: "12px", paddingTop: 16 }}
                  iconType="line"
                  onMouseEnter={(e) => setHoveredRolling(e.dataKey)}
                  onMouseLeave={() => setHoveredRolling(null)}
                />
                <Line
                  type="monotone"
                  dataKey="head"
                  stroke="#ef4444"
                  strokeWidth={1.5}
                  dot={false}
                  name="Head"
                  strokeOpacity={hoveredRolling && hoveredRolling !== "head" ? 0.1 : 1}
                />
                <Line
                  type="monotone"
                  dataKey="mid"
                  stroke="#10b981"
                  strokeWidth={1.5}
                  dot={false}
                  name="Mid"
                  strokeOpacity={hoveredRolling && hoveredRolling !== "mid" ? 0.1 : 1}
                />
                <Line
                  type="monotone"
                  dataKey="tail"
                  stroke="#3b82f6"
                  strokeWidth={1.5}
                  dot={false}
                  name="Tail"
                  strokeOpacity={hoveredRolling && hoveredRolling !== "tail" ? 0.1 : 1}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </div>
  );
}

export default MotionCharts;
