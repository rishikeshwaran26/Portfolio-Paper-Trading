import { useState } from "react";
import { useApi } from "../useApi.js";
import { api } from "../api.js";
import { Loading, ErrorBanner } from "../components/Status.jsx";
import SymbolSearch from "../components/SymbolSearch.jsx";
import PriceChart from "../components/PriceChart.jsx";
import { rupees, signClass } from "../format.js";

// The watchlist — symbols you're tracking without holding. Quotes auto-refresh
// every 15s (the page-level poll), each row shows the day's change vs previous
// close, and clicking a row opens its price chart below. This is the page that
// makes the app feel like Groww's watch screen.
export default function WatchlistPage() {
  const { data, loading, error, reload } = useApi(() => api.watchlist(), [], { refreshMs: 15_000 });
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState(false);
  const [chartSymbol, setChartSymbol] = useState(null);

  async function add(symbol) {
    if (!symbol.trim()) return;
    setAdding(true);
    try {
      await api.addToWatchlist(symbol.trim());
      setQuery("");
      reload();
    } catch {
      /* row simply won't appear; the banner covers persistent failures */
    } finally {
      setAdding(false);
    }
  }

  async function remove(symbol) {
    await api.removeFromWatchlist(symbol).catch(() => {});
    if (chartSymbol === symbol) setChartSymbol(null);
    reload();
  }

  const rows = data?.watchlist ?? [];

  return (
    <div className="page">
      <h1>
        Watchlist{" "}
        {data && (
          <span className="source-chip">
            <span className={`live-dot ${data.market_open ? "" : "closed"}`} />
            {data.market_open ? "market open · auto-updating" : "market closed · showing last close"}
          </span>
        )}
      </h1>

      <div className="card">
        <div className="card-title">Add a stock</div>
        <div className="row" style={{ alignItems: "end" }}>
          <label style={{ flex: 1 }}>
            Search by symbol or company name
            <SymbolSearch
              value={query}
              onChange={setQuery}
              onSelect={(r) => add(r.symbol)}
              placeholder="e.g. tata, INFY, bank…"
            />
          </label>
          <button className="primary" disabled={!query.trim() || adding} onClick={() => add(query)}>
            {adding ? "Adding…" : "Add"}
          </button>
        </div>
      </div>

      {loading && <Loading label="Loading watchlist…" />}
      <ErrorBanner error={error} onRetry={reload} />

      {data && rows.length === 0 && (
        <p className="muted">Nothing watched yet — search above to add stocks.</p>
      )}

      {rows.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Symbol</th><th>Company</th><th className="num">LTP</th>
              <th className="num">Day change</th><th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.symbol}
                className={`clickable ${chartSymbol === r.symbol ? "selected" : ""}`}
                onClick={() => setChartSymbol(r.symbol)}
              >
                <td><strong>{r.symbol}</strong></td>
                <td className="muted">{r.name ?? "—"}</td>
                <td className="num">{r.price != null ? rupees(r.price) : "—"}</td>
                <td className={`num ${signClass(r.change)}`}>
                  {r.change != null
                    ? `${r.change >= 0 ? "+" : ""}${r.change.toFixed(2)} (${r.change_pct >= 0 ? "+" : ""}${r.change_pct}%)`
                    : "—"}
                </td>
                <td>
                  <button
                    className="link"
                    onClick={(e) => { e.stopPropagation(); remove(r.symbol); }}
                  >
                    remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {chartSymbol && (
        <div style={{ marginTop: 16 }}>
          <PriceChart symbol={chartSymbol} />
        </div>
      )}
    </div>
  );
}
