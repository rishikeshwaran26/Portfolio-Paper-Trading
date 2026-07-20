import { useMemo, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useApi } from "../useApi.js";
import { api } from "../api.js";
import { Loading, ErrorBanner } from "../components/Status.jsx";
import ReviewForm from "../components/ReviewForm.jsx";
import { rupees, pnl, signClass, when } from "../format.js";

// OPENING trades (BUY, SHORT) carry the thesis — reason/confidence/tags.
// CLOSING trades (SELL, COVER) carry the outcome — realized P&L + closed lots
// inherited from whichever opening trade they closed via FIFO. Mirrors
// engine.models.OPENING_TYPES / CLOSING_TYPES on the backend.
const OPENING = new Set(["BUY", "SHORT"]);
const CLOSING = new Set(["SELL", "COVER"]);

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
  const [side, setSide] = useState("all"); // all | long | short

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
      // tag: an opening trade with the tag, or a closing trade whose closed
      // lot carries the tag
      if (tag) {
        const inOpen = (t.tags || []).includes(tag);
        const inClose = (t.closed_lots || []).some((l) => (l.tags || []).includes(tag));
        if (!inOpen && !inClose) return false;
      }
      // outcome only applies to closing trades (an open position has no
      // realized result yet)
      if (outcome !== "all") {
        if (!CLOSING.has(t.type)) return false;
        if (outcome === "profit" && !(t.realized_pnl > 0)) return false;
        if (outcome === "loss" && !(t.realized_pnl < 0)) return false;
      }
      // confidence: an opening trade at that level, or a closing trade whose
      // closed lot came from such an opening trade
      if (confidence !== "all") {
        const c = Number(confidence);
        const inOpen = OPENING.has(t.type) && t.confidence === c;
        const inClose = (t.closed_lots || []).some((l) => l.confidence === c);
        if (!inOpen && !inClose) return false;
      }
      // side: long trades are BUY/SELL, short trades are SHORT/COVER
      if (side !== "all") {
        const isShortTxn = t.type === "SHORT" || t.type === "COVER";
        if (side === "short" && !isShortTxn) return false;
        if (side === "long" && isShortTxn) return false;
      }
      return true;
    });
  }, [txns, tag, outcome, confidence, side]);

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
        <label>Side
          <select value={side} onChange={(e) => setSide(e.target.value)}>
            <option value="all">all</option>
            <option value="long">long</option>
            <option value="short">short</option>
          </select>
        </label>
        <label>Tag
          <select value={tag} onChange={(e) => setTag(e.target.value)}>
            <option value="">all</option>
            {allTags.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
        <label>Outcome
          <select value={outcome} onChange={(e) => setOutcome(e.target.value)}>
            <option value="all">all</option>
            <option value="profit">profit (closed)</option>
            <option value="loss">loss (closed)</option>
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
  const isClosing = CLOSING.has(t.type);
  const isShort = t.type === "SHORT" || t.type === "COVER";
  return (
    <article className={`card entry ${t.type.toLowerCase()}`}>
      <header className="entry-head">
        <span className={`tag ${t.type.toLowerCase()}`}>{t.type}</span>
        <strong>{t.quantity} {t.symbol}</strong> @ {rupees(t.price)}
        <span className="muted"> · {when(t.timestamp)}</span>
        {isClosing && (
          <span className={`entry-pnl ${signClass(t.realized_pnl)}`}>{pnl(t.realized_pnl)}</span>
        )}
      </header>

      <p className="reason">
        {isShort && <span className="chip muted" style={{ marginRight: 6 }}>short</span>}
        “{t.reason}”
      </p>

      {!isClosing && (
        <div className="entry-meta">
          <span className="chip">confidence {t.confidence}/5</span>
          {(t.tags || []).map((x) => <span key={x} className="chip tagchip">{x}</span>)}
          {t.open_quantity > 0 && <span className="chip muted">{t.open_quantity} still open</span>}
        </div>
      )}

      {isClosing && t.closed_lots?.length > 0 && (
        <div className="entry-meta">
          {t.closed_lots.map((l, i) => (
            <span key={i} className="chip">
              closed {l.quantity} @conf {l.confidence}, held {l.holding_days.toFixed(1)}d, {pnl(l.lot_pnl)}
            </span>
          ))}
        </div>
      )}

      {/* retrospective note lives on closed trades (sells and covers) */}
      {isClosing && (
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
