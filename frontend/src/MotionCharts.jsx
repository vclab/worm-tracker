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

function MotionCharts({ data }) {
  const [selectedWorm, setSelectedWorm] = useState(null);

  useEffect(() => {
    setSelectedWorm(null);
  }, [data]);

  if (!data || !data.worm_ids || data.worm_ids.length === 0) return null;

  // Initialize selected worm to first one
  const activeWorm = selectedWorm !== null ? selectedWorm : data.worm_ids[0];

  // Get max values for heatmap scaling
  const maxOverall = data.per_worm_motion?.length ? Math.max(...data.per_worm_motion) : 0;
  const maxHead = data.per_worm_head_motion?.length ? Math.max(...data.per_worm_head_motion) : 0;
  const maxTail = data.per_worm_tail_motion?.length ? Math.max(...data.per_worm_tail_motion) : 0;
  const globalMax = Math.max(maxOverall, maxHead, maxTail, 0);

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
    const windowSize = wormData.window_size || 1;

    return headData.map((head, i) => ({
      frame: i * windowSize,
      head: head,
      tail: tailData[i] || 0,
    }));
  };

  const timeSeriesData = getTimeSeriesData();

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
            <div className="heatmap-cell-header">Overall</div>
            <div className="heatmap-cell-header">Head</div>
            <div className="heatmap-cell-header">Tail</div>
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
                style={{ backgroundColor: getColor(data.per_worm_tail_motion[i], globalMax) }}
                title={`${data.per_worm_tail_motion[i].toFixed(3)} px/frame`}
              >
                {data.per_worm_tail_motion[i].toFixed(2)}
              </div>
            </div>
          ))}

          {/* Summary row */}
          <div className="heatmap-row heatmap-summary">
            <div className="heatmap-label">Mean</div>
            <div className="heatmap-cell summary-cell">
              {data.mean_motion.toFixed(2)} <span className="std">±{data.std_motion.toFixed(2)}</span>
            </div>
            <div className="heatmap-cell summary-cell">
              {data.head_mean_motion.toFixed(2)} <span className="std">±{data.head_std_motion.toFixed(2)}</span>
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
            Worm {activeWorm} — Motion Over Time
          </h4>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={timeSeriesData} margin={{ top: 10, right: 30, left: 10, bottom: 5 }}>
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
                wrapperStyle={{ fontSize: "12px" }}
                iconType="line"
              />
              <Line
                type="monotone"
                dataKey="head"
                stroke="#ef4444"
                strokeWidth={1.5}
                dot={false}
                name="Head"
              />
              <Line
                type="monotone"
                dataKey="tail"
                stroke="#3b82f6"
                strokeWidth={1.5}
                dot={false}
                name="Tail"
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

export default MotionCharts;
