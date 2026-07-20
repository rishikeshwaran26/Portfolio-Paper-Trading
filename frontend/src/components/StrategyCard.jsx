import { Link } from "react-router-dom";
import { rupees, pnl, pct, signClass } from "../format.js";

// Presentational: given one strategy summary object, render a card. No fetching,
// no state — data comes in as a prop, which makes it trivial to reuse and test.
export default function StrategyCard({ s }) {
  return (
    <Link to={`/strategies/${encodeURIComponent(s.name)}`} className="card strategy-card">
      <div className="card-title">{s.name}</div>
      <div className="big">{rupees(s.total_value)}</div>
      <div className={`return ${signClass(s.return_pct)}`}>{pct(s.return_pct)}</div>
      <dl className="kv">
        <div><dt>Cash</dt><dd>{rupees(s.cash)}</dd></div>
        <div><dt>Holdings</dt><dd>{s.num_holdings}</dd></div>
        <div><dt>Realized</dt><dd className={signClass(s.realized_pnl)}>{pnl(s.realized_pnl)}</dd></div>
        <div><dt>Unrealized</dt><dd className={signClass(s.unrealized_pnl)}>{pnl(s.unrealized_pnl)}</dd></div>
      </dl>
    </Link>
  );
}
