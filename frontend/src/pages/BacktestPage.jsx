import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { Loading, ErrorBanner } from "../components/Status.jsx";
import Sparkline from "../components/Sparkline.jsx";
import { rupees, pct, when } from "../format.js";

// BACKTEST PAGE — does the "20% spike reverts" idea actually hold up?
//
// Unlike the screener (which can only look at TODAY), a backtest replays a
// PAST calendar date: Yahoo Finance already has years of daily history, before
// and after any date, so there's nothing to wait for — we can test any date
// right now. The server still runs it on a background thread (same
// progress-polling pattern as the screener) because even a historical replay
// means real network calls across the whole exchange.
//
// The output is two things: an aggregate SUMMARY (reversion rate, average
// days to reverse — the actual answer to "does this work") and a per-stock
// TABLE with a sparkline tracing exactly what each mover did after its spike.

function todayMinusDays(days) {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

export default function BacktestPage() {
  const [targetDate, setTargetDate] = useState(todayMinusDays(90));
  const [direction, setDirection] = useState("up");
  const [thresholdPct, setThresholdPct] = useState(20);
  const [windowDays, setWindowDays] = useState(30);

  const [run, setRun] = useState(null);       // the loaded run detail: {run, movers}
  const [runs, setRuns] = useState([]);       // history list
  const [status, setStatus] = useState(null); // live progress of an in-flight run
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const pollRef = useRef(null);

  async function loadHistory() {
    try {
      const d = await api.listBacktestRuns();
      setRuns(d.runs ?? []);
      return d.runs ?? [];
    } catch {
      return [];
    }
  }

  async function loadRun(id) {
    setLoading(true);
    try {
      setRun(await api.getBacktestRun(id));
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    (async () => {
      const list = await loadHistory();
      const latestDone = list.find((r) => r.status === "done");
      if (latestDone) await loadRun(latestDone.id);
      else setLoading(false);
    })();
    return () => clearInterval(pollRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function startPolling() {
    clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const st = await api.backtestStatus();
        setStatus(st);
        if (st.status === "done" || st.status === "error") {
          clearInterval(pollRef.current);
          await loadHistory();
          if (st.status === "done" && st.run_id) await loadRun(st.run_id);
        }
      } catch {
        clearInterval(pollRef.current);
      }
    }, 1500);
  }

  async function runBacktest(e) {
    e.preventDefault();
    setError(null);
    try {
      const r = await api.runBacktest({
        target_date: targetDate,
        direction,
        threshold_pct: Number(thresholdPct),
        window_days: Number(windowDays),
      });
      setStatus(r.status);
      startPolling();
    } catch (e) {
      setError(e);
    }
  }

  const running = status?.status === "running";

  return (
    <div className="page">
      <h1>Backtest</h1>
      <p className="muted" style={{ marginTop: -12, marginBottom: 20 }}>
        Replays a past date's whole-market movers and checks what actually happened afterward —
        turning the mean-reversion idea into a real, measurable number.
      </p>

      <form className="card" onSubmit={runBacktest}>
        <div className="card-title">Run a backtest</div>
        <div className="row">
          <label>Date to replay
            <input type="date" value={targetDate} max={todayMinusDays(1)}
              onChange={(e) => setTargetDate(e.target.value)} />
          </label>
          <label>Direction
            <select value={direction} onChange={(e) => setDirection(e.target.value)}>
              <option value="up">Spikes up (short thesis)</option>
              <option value="down">Drops down (bounce thesis)</option>
            </select>
          </label>
          <label>Move threshold (%)
            <input type="number" min="1" max="100" value={thresholdPct}
              onChange={(e) => setThresholdPct(e.target.value)} />
          </label>
          <label>Tracking window (days)
            <input type="number" min="1" max="90" value={windowDays}
              onChange={(e) => setWindowDays(e.target.value)} />
          </label>
        </div>
        <button className="primary" disabled={running}>
          {running ? "Running…" : "Run backtest"}
        </button>

        {status && (running || status.status === "error") && (
          <div style={{ marginTop: 12 }}>
            {running ? (
              <>
                <div className="progress-track">
                  <div className="progress-fill" style={{ width: `${status.percent || 0}%` }} />
                </div>
                <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>
                  {status.message || "Working…"} ({status.percent || 0}%)
                </div>
              </>
            ) : (
              <div className="inline-error">Backtest failed: {status.error}</div>
            )}
          </div>
        )}
      </form>

      {runs.length > 0 && (
        <div className="card" style={{ padding: "12px 16px" }}>
          <div className="card-title" style={{ marginBottom: 8 }}>Past runs</div>
          <div className="row" style={{ gap: 8 }}>
            {runs.map((r) => (
              <button
                key={r.id}
                className={`small ${run?.run?.id === r.id ? "primary" : ""}`}
                onClick={() => loadRun(r.id)}
                title={r.status}
              >
                {r.target_date} {r.status === "done" ? `· ${r.reverted_pct ?? 0}%` : `(${r.status})`}
              </button>
            ))}
          </div>
        </div>
      )}

      {loading && <Loading label="Loading backtest…" />}
      <ErrorBanner error={error} onRetry={() => run?.run?.id && loadRun(run.run.id)} />

      {run && <BacktestResult detail={run} />}
    </div>
  );
}

function BacktestResult({ detail }) {
  const { run, movers } = detail;
  if (run.status === "error") {
    return <div className="card"><div className="inline-error">This run failed: {run.error}</div></div>;
  }
  if (!movers || movers.length === 0) {
    return (
      <div className="card">
        <p className="muted" style={{ margin: 0 }}>
          No stocks moved {run.threshold_pct}%+ on {run.target_date} — try a different date or a lower threshold.
        </p>
      </div>
    );
  }

  const revertedPct = run.reverted_pct ?? 0;
  const avgDays = movers.filter((m) => m.reverted).map((m) => m.round_trip_offset_days);
  const avgDaysToRevert = avgDays.length ? (avgDays.reduce((a, b) => a + b, 0) / avgDays.length).toFixed(1) : "—";

  return (
    <>
      <div className="summary-row">
        <Stat label="Movers found" value={run.mover_count} />
        <Stat label="Reverted" value={`${revertedPct}%`} cls={revertedPct >= 50 ? "pos" : "neg"} />
        <Stat label="Avg days to revert" value={avgDaysToRevert} />
        <Stat label="Window" value={`${run.window_days}d`} />
      </div>

      <section className="card">
        <div className="card-title">
          {run.target_date} — {run.direction === "up" ? "gainers" : "losers"} of {run.threshold_pct}%+
        </div>
        <table className="table">
          <thead>
            <tr>
              <th>Symbol</th><th>Path</th><th className="num">Spike</th>
              <th className="num">Peak</th><th className="num">First red</th>
              <th className="num">Round trip</th><th className="num">RSI</th>
              <th className="num">Vol×</th><th>Outcome</th>
            </tr>
          </thead>
          <tbody>
            {movers.map((m) => (
              <tr key={m.symbol}>
                <td>
                  <strong>{m.symbol}</strong>
                  <div className="muted" style={{ fontSize: 12 }}>{m.name}</div>
                </td>
                <td><Sparkline values={m.spark} /></td>
                <td className={`num ${m.direction === "up" ? "pos" : "neg"}`}>{pct(m.spike_pct)}</td>
                <td className="num">
                  {rupees(m.peak_price)}
                  {m.peak_offset_days > 0 && <span className="muted"> (+{m.peak_offset_days}d)</span>}
                </td>
                <td className="num">{m.first_red_offset_days != null ? `${m.first_red_offset_days}d` : "—"}</td>
                <td className="num">{m.round_trip_offset_days != null ? `${m.round_trip_offset_days}d` : "—"}</td>
                <td className="num">{m.rsi != null ? m.rsi : "—"}</td>
                <td className="num">{m.vol_ratio ? `${m.vol_ratio}×` : "—"}</td>
                <td>
                  <span className={`tag ${m.reverted ? "buy" : "sell"}`}>
                    {m.reverted ? "reverted" : "held / kept going"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}

function Stat({ label, value, cls = "" }) {
  return (
    <div className={`stat ${cls}`}>
      <div className="stat-label">{label}</div>
      <div className={`stat-value ${cls}`}>{value}</div>
    </div>
  );
}
