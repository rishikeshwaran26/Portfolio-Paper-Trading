import { useEffect, useState } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { useApi } from "../useApi.js";
import { api } from "../api.js";
import { Loading, ErrorBanner } from "../components/Status.jsx";
import HoldingsTable from "../components/HoldingsTable.jsx";
import TradeForm from "../components/TradeForm.jsx";
import TransactionList from "../components/TransactionList.jsx";
import PriceChart from "../components/PriceChart.jsx";
import { rupees, pnl, pct, signClass } from "../format.js";

// STRATEGY DETAIL owns ONE server object: the full strategy detail (summary +
// holdings + transactions), fetched by the :name in the URL. The trade form
// mutates it, then calls reload() — the single source of truth refetches and
// every child (summary, holdings, history) updates together. That's the core of
// the data flow: one fetch up here, props down, reload after writes.
export default function StrategyDetailPage() {
  const { name } = useParams();
  // refreshMs: P&L re-renders on its own as the background worker moves prices
  const { data, loading, error, reload } = useApi(() => api.getStrategy(name), [name], { refreshMs: 20_000 });
  const navigate = useNavigate();
  // Which holding's price chart to show. Defaults to the first holding once
  // data arrives; the user can switch by clicking a row.
  const [chartSymbol, setChartSymbol] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  async function removeStrategy() {
    setDeleting(true);
    try {
      await api.deleteStrategy(name);
      navigate("/"); // back to the dashboard; the deleted strategy is gone
    } catch {
      setDeleting(false); // an error banner shows on the next interaction
    }
  }

  useEffect(() => {
    if (!chartSymbol && data?.holdings?.length) setChartSymbol(data.holdings[0].symbol);
  }, [data, chartSymbol]);

  async function refreshLive() {
    setRefreshing(true);
    try {
      await api.refreshPrices();
      reload(); // pull the strategy again so P&L reflects the new prices
    } catch {
      /* the banner on the next load will surface any problem */
    } finally {
      setRefreshing(false);
    }
  }

  if (loading) return <Loading label={`Loading ${name}…`} />;
  if (error) return <ErrorBanner error={error} onRetry={reload} />;
  if (!data) return null;

  const selected = data.holdings.find((h) => h.symbol === chartSymbol);

  return (
    <div className="page">
      <div className="crumb"><Link className="link" to="/">← Dashboard</Link></div>
      <h1>
        {data.name}
        <button className="link" style={{ marginLeft: 12, fontSize: 14 }} onClick={refreshLive} disabled={refreshing}>
          {refreshing ? "refreshing…" : "↻ refresh live prices"}
        </button>
        {confirmDelete ? (
          <span style={{ marginLeft: 12, fontSize: 14 }}>
            <span className="muted">delete this strategy and all its trades?</span>
            <button className="link" style={{ color: "var(--neg)", marginLeft: 8 }} onClick={removeStrategy} disabled={deleting}>
              {deleting ? "deleting…" : "yes, delete"}
            </button>
            <button className="link" style={{ marginLeft: 8 }} onClick={() => setConfirmDelete(false)} disabled={deleting}>
              cancel
            </button>
          </span>
        ) : (
          <button className="link" style={{ marginLeft: 12, fontSize: 14, color: "var(--neg)" }} onClick={() => setConfirmDelete(true)}>
            delete strategy
          </button>
        )}
      </h1>

      <div className="summary-row">
        <Stat label="Total value" value={rupees(data.total_value)} />
        <Stat label="Return" value={pct(data.return_pct)} cls={signClass(data.return_pct)} />
        <Stat label="Cash" value={rupees(data.cash)} />
        <Stat label="Realized P&L" value={pnl(data.realized_pnl)} cls={signClass(data.realized_pnl)} />
        <Stat label="Unrealized P&L" value={pnl(data.unrealized_pnl)} cls={signClass(data.unrealized_pnl)} />
      </div>

      <div className="two-col">
        <section>
          {/* price chart for the selected holding, with your entry overlaid */}
          {selected && (
            <PriceChart symbol={selected.symbol} avgPrice={selected.avg_price} />
          )}

          <h2>Holdings {data.holdings.length > 1 && <span className="muted">— click a row to chart it</span>}</h2>
          <HoldingsTable
            holdings={data.holdings}
            selected={chartSymbol}
            onSelect={setChartSymbol}
          />
          <h2 style={{ marginTop: 24 }}>
            Transaction history <Link className="link" to={`/strategies/${encodeURIComponent(name)}/journal`}>open journal →</Link>
          </h2>
          <TransactionList transactions={data.transactions} />
        </section>

        <aside>
          <h2>Trade</h2>
          <TradeForm name={name} cash={data.cash} holdings={data.holdings} onDone={reload} />
        </aside>
      </div>
    </div>
  );
}

function Stat({ label, value, cls = "" }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className={`stat-value ${cls}`}>{value}</div>
    </div>
  );
}
