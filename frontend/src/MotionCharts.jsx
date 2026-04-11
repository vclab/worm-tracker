import { useState, useEffect } from "react";
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

const TOOLTIPS = {
  overall:
    "Average displacement per keypoint per frame (px/frame). For each frame transition, the distance traveled by all skeleton points is summed, then divided by (num_keypoints × num_transitions). Higher = more active worm.",
  head: "Average displacement of the head keypoint (wider end) per frame transition (px/frame). Mean of all frame-to-frame distances for the head point only.",
  mid: "Average displacement of the 3 middle keypoints per frame transition (px/frame). Averages across 3 adjacent skeleton points around the center to reduce noise from body deformation.",
  tail: "Average displacement of the tail keypoint (narrower end) per frame transition (px/frame). Same calculation as head but for the opposite end.",
  mean: "Average and standard deviation across all tracked worms. Shows how similar or different the worms' activity levels are — not an average across frames.",
  motionOverTime:
    "Frame-by-frame displacement of head, mid-body, and tail keypoints. Each point is the Euclidean distance that keypoint moved in one frame transition (or a windowed average if the video has many frames). Spikes indicate bursts of movement.",
  motionTrend:
    "Smoothed version of the timeline above using a rolling average (window of 10). Reduces noise to reveal overall activity trends over time.",
};

function InfoTooltip({ text, placement = "right" }) {
  const [visible, setVisible] = useState(false);
  return (
    <span
      className="info-tooltip-wrap"
      onMouseEnter={() => setVisible(true)}
      onMouseLeave={() => setVisible(false)}
    >
      <span className="info-icon">ⓘ</span>
      {visible && (
        <span className={`info-tooltip${placement === "above" ? " info-tooltip--above" : ""}`}>
          {text}
        </span>
      )}
    </span>
  );
}

function MotionCharts({ data }) {
  const [selectedWorm, setSelectedWorm] = useState(null);
  const [hoveredTimeKey, setHoveredTimeKey] = useState(null);
  const [hoveredRollKey, setHoveredRollKey] = useState(null);

  useEffect(() => {
    setSelectedWorm((prev) => {
      if (prev !== null && data?.worm_ids?.includes(prev)) return prev;
      return null;
    });
  }, [data]);

  if (!data || !data.worm_ids || data.worm_ids.length === 0) return null;

  // Initialize selected worm to first one
  const activeWorm = selectedWorm !== null ? selectedWorm : data.worm_ids[0];

  // Get max values for heatmap scaling
  const maxOverall = data.per_worm_motion?.length ? Math.max(...data.per_worm_motion) : 0;
  const maxHead = data.per_worm_head_motion?.length ? Math.max(...data.per_worm_head_motion) : 0;
  const maxMid  = data.per_worm_mid_motion?.length  ? Math.max(...data.per_worm_mid_motion)  : 0;
  const maxTail = data.per_worm_tail_motion?.length ? Math.max(...data.per_worm_tail_motion) : 0;
  const globalMax = Math.max(maxOverall, maxHead, maxMid, maxTail, 0);

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
    const midData  = wormData.mid  || [];
    const tailData = wormData.tail || [];
    const windowSize = wormData.window_size || 1;
    const len = Math.min(
      headData.length,
      tailData.length,
      midData.length > 0 ? midData.length : Infinity,
    );

    return Array.from({ length: len }, (_, i) => ({
      frame: i * windowSize,
      head: headData[i] ?? null,
      mid:  midData[i]  ?? null,
      tail: tailData[i] ?? null,
    }));
  };

  const timeSeriesData = getTimeSeriesData();

  // Compute rolling average with window size 10
  const ROLLING_WINDOW = 10;
  const rollingAvgData = (() => {
    if (timeSeriesData.length === 0) return [];
    const keys = ["head", "mid", "tail"];
    return timeSeriesData.map((point, i) => {
      const start = Math.max(0, i - ROLLING_WINDOW + 1);
      const result = { frame: point.frame };
      for (const key of keys) {
        const slice = timeSeriesData.slice(start, i + 1).map((p) => p[key]).filter((v) => v != null);
        result[key] = slice.length > 0 ? slice.reduce((a, b) => a + b, 0) / slice.length : null;
      }
      return result;
    });
  })();

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
            <div className="heatmap-cell-header">Overall<InfoTooltip text={TOOLTIPS.overall} /></div>
            <div className="heatmap-cell-header">Head<InfoTooltip text={TOOLTIPS.head} /></div>
            <div className="heatmap-cell-header">Mid-body<InfoTooltip text={TOOLTIPS.mid} /></div>
            <div className="heatmap-cell-header">Tail<InfoTooltip text={TOOLTIPS.tail} /></div>
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
                style={{ backgroundColor: getColor((data.per_worm_mid_motion ?? [])[i] ?? 0, globalMax) }}
                title={`${((data.per_worm_mid_motion ?? [])[i] ?? 0).toFixed(3)} px/frame`}
              >
                {((data.per_worm_mid_motion ?? [])[i] ?? 0).toFixed(2)}
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
            <div className="heatmap-label">Mean<InfoTooltip text={TOOLTIPS.mean} /></div>
            <div className="heatmap-cell summary-cell">
              {data.mean_motion.toFixed(2)} <span className="std">±{data.std_motion.toFixed(2)}</span>
            </div>
            <div className="heatmap-cell summary-cell">
              {data.head_mean_motion.toFixed(2)} <span className="std">±{data.head_std_motion.toFixed(2)}</span>
            </div>
            <div className="heatmap-cell summary-cell">
              {(data.mid_mean_motion ?? 0).toFixed(2)} <span className="std">±{(data.mid_std_motion ?? 0).toFixed(2)}</span>
            </div>
            <div className="heatmap-cell summary-cell">
              {data.tail_mean_motion.toFixed(2)} <span className="std">±{data.tail_std_motion.toFixed(2)}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Time Series */}
      {timeSeriesData.length > 0 && (
        <div className="timeline-container">
          <h4 className="timeline-title">
            Worm {activeWorm} — Motion Over Time<InfoTooltip text={TOOLTIPS.motionOverTime} placement="above" />
          </h4>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={timeSeriesData} margin={{ top: 10, right: 30, left: 10, bottom: 25 }}>
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
                formatter={(value) => [value != null ? value.toFixed(3) : "—", ""]}
                labelFormatter={(label) => `Frame ${label}`}
              />
              <Legend
                wrapperStyle={{ paddingTop: 16, fontSize: "12px" }}
                iconType="line"
                onMouseEnter={(e) => setHoveredTimeKey(e.dataKey)}
                onMouseLeave={() => setHoveredTimeKey(null)}
              />
              <Line
                type="monotone"
                dataKey="head"
                stroke="#ef4444"
                strokeWidth={1.5}
                dot={false}
                name="Head"
                strokeOpacity={hoveredTimeKey && hoveredTimeKey !== "head" ? 0.1 : 1}
              />
              <Line
                type="monotone"
                dataKey="mid"
                stroke="#a855f7"
                strokeWidth={1.5}
                dot={false}
                name="Mid-body"
                connectNulls={false}
                strokeOpacity={hoveredTimeKey && hoveredTimeKey !== "mid" ? 0.1 : 1}
              />
              <Line
                type="monotone"
                dataKey="tail"
                stroke="#3b82f6"
                strokeWidth={1.5}
                dot={false}
                name="Tail"
                strokeOpacity={hoveredTimeKey && hoveredTimeKey !== "tail" ? 0.1 : 1}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Rolling Average Chart */}
      {rollingAvgData.length > 0 && (
        <div className="timeline-container">
          <h4 className="timeline-title">
            Worm {activeWorm} — Motion Trend (Rolling Average)<InfoTooltip text={TOOLTIPS.motionTrend} placement="above" />
          </h4>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={rollingAvgData} margin={{ top: 10, right: 30, left: 10, bottom: 25 }}>
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
                formatter={(value) => [value != null ? value.toFixed(3) : "—", ""]}
                labelFormatter={(label) => `Frame ${label}`}
              />
              <Legend
                wrapperStyle={{ paddingTop: 16, fontSize: "12px" }}
                iconType="line"
                onMouseEnter={(e) => setHoveredRollKey(e.dataKey)}
                onMouseLeave={() => setHoveredRollKey(null)}
              />
              <Line
                type="monotone"
                dataKey="head"
                stroke="#ef4444"
                strokeWidth={1.5}
                dot={false}
                name="Head"
                strokeOpacity={hoveredRollKey && hoveredRollKey !== "head" ? 0.1 : 1}
              />
              <Line
                type="monotone"
                dataKey="mid"
                stroke="#a855f7"
                strokeWidth={1.5}
                dot={false}
                name="Mid-body"
                connectNulls={false}
                strokeOpacity={hoveredRollKey && hoveredRollKey !== "mid" ? 0.1 : 1}
              />
              <Line
                type="monotone"
                dataKey="tail"
                stroke="#3b82f6"
                strokeWidth={1.5}
                dot={false}
                name="Tail"
                strokeOpacity={hoveredRollKey && hoveredRollKey !== "tail" ? 0.1 : 1}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

export default MotionCharts;
