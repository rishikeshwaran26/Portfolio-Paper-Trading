import { Link } from "react-router-dom";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, ReferenceLine,
} from "recharts";
import { useApi } from "../useApi.js";
import { api } from "../api.js";
import { Loading, ErrorBanner } from "../components/Status.jsx";
import { rupees, pnl, pct, signClass } from "../format.js";

// LEADERBOARD owns one server object (the ranked rows) and passes it to both a
// recharts bar chart and a table. The chart is a pure function of that data —
// no separate state — so there is nothing to keep in sync.
export default function LeaderboardPage() {
  const { data, loading, error, reload } = useApi(() => api.leaderboard(), []);

  if (loading) return <Loading label="Ranking strategies…" />;
  if (error) return <ErrorBanner error={error} onRetry={reload} />;

  const rows = data?.leaderboard ?? [];
  if (rows.length === 0) {
    return (
      <div className="page">
        <h1>Leaderboard</h1>
        <p className="muted">No strategies yet. <Link className="link" to="/">Create one →</Link></p>
      </div>
    );
  }

  // recharts wants a flat array of plain objects.
  const chartData = rows.map((r) => ({ name: r.strategy, return_pct: r.return_pct }));

  return (
    <div className="page">
      <h1>Leaderboard <span className="muted">— your strategies, ranked by return %</span></h1>

      <div className="card chart-card">
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={chartData} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
            <XAxis dataKey="name" tick={{ fontSize: 12 }} />
            <YAxis tickFormatter={(v) => `${v}%`} tick={{ fontSize: 12 }} />
            <Tooltip formatter={(v) => [`${v}%`, "return"]} />
            <ReferenceLine y={0} stroke="#888" />
            <Bar dataKey="return_pct" radius={[4, 4, 0, 0]}>
              {chartData.map((d, i) => (
                // green for gains, red for losses
                <Cell key={i} fill={d.return_pct >= 0 ? "#16a34a" : "#dc2626"} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <table className="table">
        <thead>
          <tr>
            <th className="num">#</th><th>Strategy</th><th className="num">Total value</th>
            <th className="num">Return</th><th className="num">Realized</th><th className="num">Unrealized</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.strategy}>
              <td className="num">{r.rank}</td>
              <td><Link className="link" to={`/strategies/${encodeURIComponent(r.strategy)}`}>{r.strategy}</Link></td>
              <td className="num">{rupees(r.total_value)}</td>
              <td className={`num ${signClass(r.return_pct)}`}>{pct(r.return_pct)}</td>
              <td className={`num ${signClass(r.realized_pnl)}`}>{pnl(r.realized_pnl)}</td>
              <td className={`num ${signClass(r.unrealized_pnl)}`}>{pnl(r.unrealized_pnl)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
