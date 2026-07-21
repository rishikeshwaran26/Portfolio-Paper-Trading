import { useState } from "react";
import { useApi } from "../useApi.js";
import { api } from "../api.js";
import { Loading, ErrorBanner } from "../components/Status.jsx";
import SymbolSearch from "../components/SymbolSearch.jsx";
import PriceChart from "../components/PriceChart.jsx";
import { rupees, signClass } from "../format.js";

// Multiple NAMED watchlists (e.g. "Swing", "Intraday"), each tracking its own
// set of symbols — the same stock can sit in more than one list at once, since
// what you're watching it FOR differs per list. Quotes auto-refresh every 15s
// (the page-level poll). This is the page that makes the app feel like
// Groww's watch screen, just with your own groupings on top.
export default function WatchlistPage() {
  const { data, loading, error, reload } = useApi(() => api.listWatchlists(), [], { refreshMs: 15_000 });
  const [chartSymbol, setChartSymbol] = useState(null);

  const lists = data?.watchlists ?? [];

  return (
    <div className="page">
      <h1>
        Watchlists{" "}
        {data && (
          <span className="source-chip">
            <span className={`live-dot ${data.market_open ? "" : "closed"}`} />
            {data.market_open ? "market open · auto-updating" : "market closed · showing last close"}
          </span>
        )}
      </h1>

      <NewWatchlistForm onCreated={reload} />

      {loading && <Loading label="Loading watchlists…" />}
      <ErrorBanner error={error} onRetry={reload} />

      {data && lists.length === 0 && (
        <p className="muted">
          No watchlists yet — create one above (e.g. “Swing”, “Intraday”) to start tracking stocks.
        </p>
      )}

      {lists.map((wl) => (
        <WatchlistCard
          key={wl.id}
          watchlist={wl}
          onChanged={reload}
          chartSymbol={chartSymbol}
          onChartSymbol={setChartSymbol}
        />
      ))}

      {chartSymbol && (
        <div style={{ marginTop: 16 }}>
          <PriceChart symbol={chartSymbol} />
        </div>
      )}
    </div>
  );
}

// Owns ONLY its own name-input state. Calls onCreated() so the parent
// refetches the (now longer) list of watchlists — same pattern as
// CreateStrategyForm.
function NewWatchlistForm({ onCreated }) {
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  async function submit(e) {
    e.preventDefault();
    if (!name.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await api.createWatchlist(name.trim());
      setName("");
      onCreated?.();
    } catch (err) {
      setError(err);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="card" onSubmit={submit}>
      <div className="card-title">New watchlist</div>
      <div className="row" style={{ alignItems: "end" }}>
        <label style={{ flex: 1 }}>
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Swing, Intraday" />
        </label>
        <button className="primary" disabled={!name.trim() || submitting}>
          {submitting ? "Creating…" : "Create watchlist"}
        </button>
      </div>
      {error && <div className="inline-error">{error.message}</div>}
    </form>
  );
}

// One named watchlist: its own "add stock" search box, its own table of
// quotes, and a delete-this-list action. Owns only its local add/query state —
// the actual data lives in the parent and flows down as the `watchlist` prop,
// so any change here triggers onChanged() to refetch the whole page.
function WatchlistCard({ watchlist, onChanged, chartSymbol, onChartSymbol }) {
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  async function add(symbol) {
    if (!symbol.trim()) return;
    setAdding(true);
    try {
      await api.addToWatchlist(watchlist.id, symbol.trim());
      setQuery("");
      onChanged?.();
    } catch {
      /* row simply won't appear; a persistent failure would show elsewhere */
    } finally {
      setAdding(false);
    }
  }

  async function removeSymbol(symbol) {
    await api.removeFromWatchlist(watchlist.id, symbol).catch(() => {});
    if (chartSymbol === symbol) onChartSymbol(null);
    onChanged?.();
  }

  async function deleteList() {
    await api.deleteWatchlist(watchlist.id).catch(() => {});
    onChanged?.();
  }

  const stocks = watchlist.stocks ?? [];

  return (
    <section className="card">
      <div className="card-title">
        <span>{watchlist.name}</span>
        {confirmDelete ? (
          <span>
            <span className="muted" style={{ fontSize: 13, marginRight: 6 }}>delete this list?</span>
            <button className="link" onClick={deleteList} style={{ color: "var(--neg)" }}>yes, delete</button>
            <button className="link" onClick={() => setConfirmDelete(false)} style={{ marginLeft: 8 }}>cancel</button>
          </span>
        ) : (
          <button className="link" onClick={() => setConfirmDelete(true)}>delete list</button>
        )}
      </div>

      <div className="row" style={{ alignItems: "end", marginBottom: 12 }}>
        <label style={{ flex: 1 }}>
          Add a stock
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

      {stocks.length === 0 ? (
        <p className="muted">Nothing in this list yet — search above to add stocks.</p>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>Symbol</th><th>Company</th><th className="num">LTP</th>
              <th className="num">Day change</th><th></th>
            </tr>
          </thead>
          <tbody>
            {stocks.map((r) => (
              <tr
                key={r.symbol}
                className={`clickable ${chartSymbol === r.symbol ? "selected" : ""}`}
                onClick={() => onChartSymbol(r.symbol)}
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
                  <button className="link" onClick={(e) => { e.stopPropagation(); removeSymbol(r.symbol); }}>
                    remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
