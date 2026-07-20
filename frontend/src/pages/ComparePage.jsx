import { useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, CartesianGrid, ReferenceLine,
} from "recharts";
import { useApi } from "../useApi.js";
import { api } from "../api.js";
import { Loading, ErrorBanner } from "../components/Status.jsx";

// Overlay return % over time for 2+ strategies.
//
// The backend already returns `series` in chart shape — one row per date with
// one key per strategy ([{date, "Momentum": 0.45, "Value Picks": 0.2}]) — so
// this component does zero reshaping. Putting that transform server-side keeps
// the "what shape does recharts want" knowledge in one place instead of
// duplicated across every chart in the UI.
const COLORS = ["#3b82f6", "#22c55e", "#eab308", "#a855f7", "#ec4899", "#14b8a6"];

export default function ComparePage() {
  const { data, loading, error, reload } = useApi(() => api.snapshots(), []);
  const [capturing, setCapturing] = useState(false);

  async function captureNow() {
    setCapturing(true);
    try {
      await api.captureSnapshot();
      reload();
    } finally {
      setCapturing(false);
    }
  }

  if (loading) return <Loading label="Loading history…" />;
  if (error) return <ErrorBanner error={error} onRetry={reload} />;

  const series = data?.series ?? [];
  const strategies = data?.strategies ?? [];

  return (
    <div className="page">
      <h1>Compare strategies</h1>
      <p className="muted">
        Return % over time, from daily portfolio snapshots. The background job records
        one point per strategy per day — use “snapshot now” to add a point immediately.
      </p>

      <div style={{ marginBottom: 16 }}>
        <button className="primary" onClick={captureNow} disabled={capturing}>
          {capturing ? "Capturing…" : "Snapshot now"}
        </button>
      </div>

      {series.length === 0 ? (
        <p className="muted">
          No snapshots recorded yet. Click “snapshot now” to capture the first data point.
        </p>
      ) : (
        <>
          <div className="card chart-card">
            <ResponsiveContainer width="100%" height={340}>
              <LineChart data={series} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#2a3346" />
                <XAxis dataKey="date" tick={{ fontSize: 12 }} />
                <YAxis tickFormatter={(v) => `${v}%`} tick={{ fontSize: 12 }} />
                <Tooltip
                  formatter={(v, n) => [`${v}%`, n]}
                  contentStyle={{ background: "#171d2b", border: "1px solid #2a3346", borderRadius: 8 }}
                />
                <Legend />
                <ReferenceLine y={0} stroke="#888" />
                {strategies.map((name, i) => (
                  <Line
                    key={name}
                    type="monotone"
                    dataKey={name}
                    stroke={COLORS[i % COLORS.length]}
                    strokeWidth={2}
                    dot={{ r: 3 }}
                    connectNulls  /* a strategy created later still draws cleanly */
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
          <p className="muted">
            {series.length} snapshot {series.length === 1 ? "day" : "days"} · {strategies.length}{" "}
            {strategies.length === 1 ? "strategy" : "strategies"}
            {series.length === 1 && " — one point can't show a trend yet; check back tomorrow."}
          </p>
        </>
      )}
    </div>
  );
}
