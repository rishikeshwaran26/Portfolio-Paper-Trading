import { useMemo, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useApi } from "../useApi.js";
import { api } from "../api.js";
import { Loading, ErrorBanner } from "../components/Status.jsx";
import ReviewForm from "../components/ReviewForm.jsx";
import { rupees, pnl, signClass, when } from "../format.js";

// JOURNAL PAGE fetches the strategy's transactions once, then does all filtering
// CLIENT-SIDE with useMemo. Why here and not the server? The dataset is small
// (your own trades) and filtering is cheap, so keeping filter state in the UI
// gives instant response with zero extra network calls. The filter selections
// are plain useState — they're view state, so they live in the view.
export default function JournalPage() {
  const { name } = useParams();
  const { data, loading, error, reload } = useApi(() => api.transactions(name), [name]);

  const [tag, setTag] = useState("");
  const [outcome, setOutcome] = useState("all"); // all | profit | loss
  const [confidence, setConfidence] = useState("all"); // all | 1..5

  const txns = data?.transactions ?? [];

  // Collect the set of tags that actually appear, to populate the dropdown.
  const allTags = useMemo(() => {
    const set = new Set();
    for (const t of txns) {
      (t.tags || []).forEach((x) => set.add(x));
      (t.closed_lots || []).forEach((l) => (l.tags || []).forEach((x) => set.add(x)));
    }
    return [...set].sort();
  }, [txns]);

  const filtered = useMemo(() => {
    return txns.filter((t) => {
      // tag: a buy with the tag, or a sell that closed a lot carrying the tag
      if (tag) {
        const inBuy = (t.tags || []).includes(tag);
        const inSell = (t.closed_lots || []).some((l) => (l.tags || []).includes(tag));
        if (!inBuy && !inSell) return false;
      }
      // outcome only applies to sells (a buy has no realized result yet)
      if (outcome !== "all") {
        if (t.type !== "SELL") return false;
        if (outcome === "profit" && !(t.realized_pnl > 0)) return false;
        if (outcome === "loss" && !(t.realized_pnl < 0)) return false;
      }
      // confidence: a buy at that level, or a sell that closed such a lot
      if (confidence !== "all") {
        const c = Number(confidence);
        const inBuy = t.type === "BUY" && t.confidence === c;
        const inSell = (t.closed_lots || []).some((l) => l.confidence === c);
        if (!inBuy && !inSell) return false;
      }
      return true;
    });
  }, [txns, tag, outcome, confidence]);

  if (loading) return <Loading label="Loading journal…" />;
  if (error) return <ErrorBanner error={error} onRetry={reload} />;

  return (
    <div className="page">
      <div className="crumb">
        <Link className="link" to={`/strategies/${encodeURIComponent(name)}`}>← {name}</Link>
      </div>
      <h1>
        Trade journal{" "}
        <Link className="link" style={{ fontSize: 15 }} to={`/strategies/${encodeURIComponent(name)}/analytics`}>
          view analytics →
        </Link>
      </h1>

      <div className="card filters">
        <label>Tag
          <select value={tag} onChange={(e) => setTag(e.target.value)}>
            <option value="">all</option>
            {allTags.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
        <label>Outcome
          <select value={outcome} onChange={(e) => setOutcome(e.target.value)}>
            <option value="all">all</option>
            <option value="profit">profit (sells)</option>
            <option value="loss">loss (sells)</option>
          </select>
        </label>
        <label>Confidence
          <select value={confidence} onChange={(e) => setConfidence(e.target.value)}>
            <option value="all">all</option>
            {[1, 2, 3, 4, 5].map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
        <span className="muted">{filtered.length} of {txns.length} entries</span>
      </div>

      {filtered.length === 0 && <p className="muted">No entries match these filters.</p>}

      <div className="journal">
        {[...filtered].reverse().map((t) => (
          <JournalEntry key={t.id} t={t} name={name} onReviewed={reload} />
        ))}
      </div>
    </div>
  );
}

function JournalEntry({ t, name, onReviewed }) {
  const isSell = t.type === "SELL";
  return (
    <article className={`card entry ${t.type.toLowerCase()}`}>
      <header className="entry-head">
        <span className={`tag ${isSell ? "sell" : "buy"}`}>{t.type}</span>
        <strong>{t.quantity} {t.symbol}</strong> @ {rupees(t.price)}
        <span className="muted"> · {when(t.timestamp)}</span>
        {isSell && (
          <span className={`entry-pnl ${signClass(t.realized_pnl)}`}>{pnl(t.realized_pnl)}</span>
        )}
      </header>

      <p className="reason">“{t.reason}”</p>

      {!isSell && (
        <div className="entry-meta">
          <span className="chip">confidence {t.confidence}/5</span>
          {(t.tags || []).map((x) => <span key={x} className="chip tagchip">{x}</span>)}
          {t.open_quantity > 0 && <span className="chip muted">{t.open_quantity} still open</span>}
        </div>
      )}

      {isSell && t.closed_lots?.length > 0 && (
        <div className="entry-meta">
          {t.closed_lots.map((l, i) => (
            <span key={i} className="chip">
              closed {l.quantity} @conf {l.confidence}, held {l.holding_days.toFixed(1)}d, {pnl(l.lot_pnl)}
            </span>
          ))}
        </div>
      )}

      {/* retrospective note lives on closed trades (sells) */}
      {isSell && (
        <div className="review">
          {t.review ? (
            <div className="review-note"><strong>Review:</strong> {t.review}</div>
          ) : (
            <ReviewForm name={name} txnId={t.id} onSaved={onReviewed} />
          )}
        </div>
      )}
    </article>
  );
}
