import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Cell,
} from "recharts";

function MotionCharts({ data }) {
  if (!data) return null;

  // Prepare per-worm data for bar charts (use actual worm IDs)
  const wormData = data.per_worm_motion.map((motion, i) => ({
    worm: `${data.worm_ids ? data.worm_ids[i] : i + 1}`,
    motion: motion,
  }));

  const headData = data.per_worm_head_motion?.map((motion, i) => ({
    worm: `${data.worm_ids ? data.worm_ids[i] : i + 1}`,
    motion: motion,
  })) || [];

  const tailData = data.per_worm_tail_motion?.map((motion, i) => ({
    worm: `${data.worm_ids ? data.worm_ids[i] : i + 1}`,
    motion: motion,
  })) || [];

  const mean = data.mean_motion;
  const std = data.std_motion;
  const headMean = data.head_mean_motion || 0;
  const headStd = data.head_std_motion || 0;
  const headMin = data.head_min_motion || 0;
  const headMax = data.head_max_motion || 0;
  const tailMean = data.tail_mean_motion || 0;
  const tailStd = data.tail_std_motion || 0;
  const tailMin = data.tail_min_motion || 0;
  const tailMax = data.tail_max_motion || 0;

  const renderBarChart = (chartData, chartMean, chartStd, chartMin, chartMax, color, title) => (
    <div className="chart-panel">
      <h4>{title}</h4>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={chartData} margin={{ top: 20, right: 30, left: 20, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
          <XAxis
            dataKey="worm"
            stroke="#9ca3af"
            tick={{ fontSize: 10 }}
          />
          <YAxis
            stroke="#9ca3af"
            tick={{ fontSize: 10 }}
            label={{
              value: "px/frame",
              angle: -90,
              position: "insideLeft",
              fill: "#9ca3af",
              fontSize: 10,
            }}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "#1f2937",
              border: "1px solid #374151",
            }}
            formatter={(value) => [value.toFixed(3), "Motion"]}
          />
          <ReferenceLine
            y={chartMean}
            stroke="#10b981"
            strokeWidth={2}
            strokeDasharray="5 5"
            label={{ value: "Mean", fill: "#10b981", fontSize: 10 }}
          />
          <ReferenceLine
            y={chartMean + chartStd}
            stroke="#f59e0b"
            strokeWidth={1}
            strokeDasharray="3 3"
            label={{ value: "+1σ", fill: "#f59e0b", fontSize: 9 }}
          />
          <ReferenceLine
            y={Math.max(0, chartMean - chartStd)}
            stroke="#f59e0b"
            strokeWidth={1}
            strokeDasharray="3 3"
            label={{ value: "-1σ", fill: "#f59e0b", fontSize: 9 }}
          />
          <Bar dataKey="motion" radius={[4, 4, 0, 0]}>
            {chartData.map((entry, index) => (
              <Cell key={`cell-${index}`} fill={color} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <div className="summary-stats" style={{ marginTop: 8, display: "flex", gap: 16, justifyContent: "center", flexWrap: "wrap", fontSize: 12 }}>
        <span>Mean: <strong>{chartMean.toFixed(3)}</strong></span>
        <span>Std: <strong>{chartStd.toFixed(3)}</strong></span>
        <span>Min: <strong>{chartMin.toFixed(3)}</strong></span>
        <span>Max: <strong>{chartMax.toFixed(3)}</strong></span>
      </div>
    </div>
  );

  return (
    <div className="charts-container">
      <h3 className="charts-title">Motion Analysis</h3>
      <p className="charts-subtitle">
        Movement analysis across {data.num_worms} worm(s)
      </p>

      {/* Overall motion */}
      <div className="chart-panel" style={{ marginBottom: 24 }}>
        <h4>Overall Motion (all keypoints)</h4>
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={wormData} margin={{ top: 20, right: 30, left: 20, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
            <XAxis dataKey="worm" stroke="#9ca3af" tick={{ fontSize: 10 }} />
            <YAxis
              stroke="#9ca3af"
              tick={{ fontSize: 10 }}
              label={{ value: "px/frame", angle: -90, position: "insideLeft", fill: "#9ca3af", fontSize: 10 }}
            />
            <Tooltip
              contentStyle={{ backgroundColor: "#1f2937", border: "1px solid #374151" }}
              formatter={(value) => [value.toFixed(3), "Motion"]}
            />
            <ReferenceLine y={mean} stroke="#10b981" strokeWidth={2} strokeDasharray="5 5" label={{ value: "Mean", fill: "#10b981", fontSize: 10 }} />
            <ReferenceLine y={mean + std} stroke="#f59e0b" strokeWidth={1} strokeDasharray="3 3" label={{ value: "+1σ", fill: "#f59e0b", fontSize: 9 }} />
            <ReferenceLine y={Math.max(0, mean - std)} stroke="#f59e0b" strokeWidth={1} strokeDasharray="3 3" label={{ value: "-1σ", fill: "#f59e0b", fontSize: 9 }} />
            <Bar dataKey="motion" radius={[4, 4, 0, 0]}>
              {wormData.map((entry, index) => (
                <Cell key={`cell-${index}`} fill="#6366f1" />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
        <div className="summary-stats" style={{ marginTop: 8, display: "flex", gap: 16, justifyContent: "center", flexWrap: "wrap", fontSize: 12 }}>
          <span>Mean: <strong>{mean.toFixed(3)}</strong></span>
          <span>Std: <strong>{std.toFixed(3)}</strong></span>
          <span>Min: <strong>{data.min_motion.toFixed(3)}</strong></span>
          <span>Max: <strong>{data.max_motion.toFixed(3)}</strong></span>
        </div>
      </div>

      {/* Head and Tail motion - full width, stacked */}
      {headData.length > 0 && tailData.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
          {renderBarChart(headData, headMean, headStd, headMin, headMax, "#ef4444", "Head Motion")}
          {renderBarChart(tailData, tailMean, tailStd, tailMin, tailMax, "#3b82f6", "Tail Motion")}
        </div>
      )}
    </div>
  );
}

export default MotionCharts;
