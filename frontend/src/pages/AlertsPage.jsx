import { useState } from "react";
import { useApi } from "../useApi.js";
import { api } from "../api.js";
import { Loading, ErrorBanner } from "../components/Status.jsx";
import { rupees, when } from "../format.js";

// Manage price alerts: create, see status, delete.
export default function AlertsPage() {
  const { data, loading, error, reload } = useApi(() => api.alerts(), []);
  const prices = useApi(() => api.prices(), []);

  const [symbol, setSymbol] = useState("");
  const [target, setTarget] = useState("");
  const [direction, setDirection] = useState("above");
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState(null);

  const valid = symbol.trim() && Number(target) > 0;

  async function submit(e) {
    e.preventDefault();
    if (!valid) return;
    setSubmitting(true);
    setFormError(null);
    try {
      await api.createAlert({
        symbol: symbol.trim().toUpperCase(),
        target_price: Number(target),
        direction,
        note: note.trim(),
      });
      setSymbol(""); setTarget(""); setNote("");
      reload();
    } catch (err) {
      setFormError(err);
    } finally {
      setSubmitting(false);
    }
  }

  async function remove(id) {
    await api.deleteAlert(id).catch(() => {});
    reload();
  }

  return (
    <div className="page">
      <h1>Price alerts</h1>
      <p className="muted">
        The backend checks these against the latest known price every 15 seconds,
        and instantly whenever a price is updated.
      </p>

      <form className="card" onSubmit={submit}>
        <div className="card-title">New alert</div>
        <div className="row">
          <label>Symbol
            <input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} placeholder="RELIANCE" />
          </label>
          <label>Direction
            <select value={direction} onChange={(e) => setDirection(e.target.value)}>
              <option value="above">goes above</option>
              <option value="below">drops below</option>
            </select>
          </label>
          <label>Target price (₹)
            <input type="number" min="0" step="0.05" value={target} onChange={(e) => setTarget(e.target.value)} />
          </label>
        </div>
        <label>Note (optional)
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="why are you watching this level?" />
        </label>
        {formError && <div className="inline-error">{formError.message}</div>}
        <button className="primary" disabled={!valid || submitting}>
          {submitting ? "Adding…" : "Add alert"}
        </button>
      </form>

      {loading && <Loading label="Loading alerts…" />}
      <ErrorBanner error={error} onRetry={reload} />

      {data && data.alerts.length === 0 && <p className="muted">No alerts set.</p>}

      {data && data.alerts.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Symbol</th><th>Condition</th><th className="num">Latest</th>
              <th>Status</th><th>Note</th><th></th>
            </tr>
          </thead>
          <tbody>
            {data.alerts.map((a) => {
              const latest = prices.data?.prices?.[a.symbol];
              return (
                <tr key={a.id}>
                  <td>{a.symbol}</td>
                  <td>{a.direction} {rupees(a.target_price)}</td>
                  <td className="num">{latest != null ? rupees(latest) : "—"}</td>
                  <td>
                    <span className={`tag ${a.status === "triggered" ? "sell" : a.status === "active" ? "buy" : ""}`}>
                      {a.status}
                    </span>
                    {a.triggered_at && (
                      <div className="muted" style={{ fontSize: 12 }}>{when(a.triggered_at)}</div>
                    )}
                  </td>
                  <td className="muted">{a.note || "—"}</td>
                  <td><button className="link" onClick={() => remove(a.id)}>delete</button></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
