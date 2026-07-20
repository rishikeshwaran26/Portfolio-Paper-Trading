import { Link } from "react-router-dom";
import { useApi } from "../useApi.js";
import { api } from "../api.js";
import { Loading, ErrorBanner } from "../components/Status.jsx";
import StrategyCard from "../components/StrategyCard.jsx";
import CreateStrategyForm from "../components/CreateStrategyForm.jsx";
import { pct, signClass } from "../format.js";

// DASHBOARD owns two pieces of server data: the list of strategies and the
// leaderboard. Because this page is where that data is needed and refetched, the
// data lives here (via useApi) and flows DOWN as props to the cards. When the
// create form or anything else mutates data, we call reload() to refetch.
export default function DashboardPage() {
  const strategies = useApi(() => api.listStrategies(), [], { refreshMs: 20_000 });
  const board = useApi(() => api.leaderboard(), [], { refreshMs: 20_000 });

  function refresh() {
    strategies.reload();
    board.reload();
  }

  return (
    <div className="page">
      <h1>Your strategies</h1>

      <CreateStrategyForm onCreated={refresh} />

      {/* Each API read renders its own loading / error / data states. */}
      {strategies.loading && <Loading label="Loading strategies…" />}
      <ErrorBanner error={strategies.error} onRetry={strategies.reload} />

      {strategies.data && strategies.data.strategies.length === 0 && (
        <p className="muted">No strategies yet — create one above to start trading.</p>
      )}

      {strategies.data && strategies.data.strategies.length > 0 && (
        <div className="grid">
          {strategies.data.strategies.map((s) => (
            <StrategyCard key={s.name} s={s} />
          ))}
        </div>
      )}

      <section className="mini-board card">
        <div className="card-title">
          Mini leaderboard <Link className="link" to="/leaderboard">full →</Link>
        </div>
        {board.loading && <Loading label="Ranking…" />}
        <ErrorBanner error={board.error} onRetry={board.reload} />
        {board.data && (
          <ol className="rank-list">
            {board.data.leaderboard.slice(0, 3).map((r) => (
              <li key={r.strategy}>
                <span className="rank">#{r.rank}</span>
                <Link className="link" to={`/strategies/${encodeURIComponent(r.strategy)}`}>
                  {r.strategy}
                </Link>
                <span className={`return ${signClass(r.return_pct)}`}>{pct(r.return_pct)}</span>
              </li>
            ))}
            {board.data.leaderboard.length === 0 && <li className="muted">nothing ranked yet</li>}
          </ol>
        )}
      </section>
    </div>
  );
}
