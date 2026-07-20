import { useState } from "react";
import { api } from "../api.js";
import { rupees } from "../format.js";
import SymbolSearch from "./SymbolSearch.jsx";

// The trade form. Four actions, two directions:
//   long  side:  BUY   (open)  ->  SELL  (close)
//   short side:  SHORT (open)  ->  COVER (close)
//
// OPENING trades (buy/short) capture the journal fields — reason, confidence,
// tags — because capturing WHY is the whole point of this project. CLOSING
// trades (sell/cover) only need a reason, since confidence/tags are inherited
// from the opening trade they close via FIFO matching on the backend.
//
// State placement: every input here is local component state. The parent passes
// down what the form needs to VALIDATE against (cash, holdings) but does NOT
// own the keystrokes. On a successful trade the form calls onDone() so the
// parent refetches the (now changed) strategy.

// One table drives labels, validation and the API call — adding a mode means
// adding a row here, not scattering `if (side === ...)` through the component.
const ACTIONS = {
  buy:   { label: "Buy",   verb: "Bought",  opening: true,  cls: "primary", api: "buy" },
  sell:  { label: "Sell",  verb: "Sold",    opening: false, cls: "danger",  api: "sell" },
  short: { label: "Short", verb: "Shorted", opening: true,  cls: "danger",  api: "short" },
  cover: { label: "Cover", verb: "Covered", opening: false, cls: "primary", api: "cover" },
};

export default function TradeForm({ name, cash, holdings, onDone }) {
  const [side, setSide] = useState("buy");
  const [symbol, setSymbol] = useState("");
  const [quantity, setQuantity] = useState("");
  const [price, setPrice] = useState("");
  const [reason, setReason] = useState("");
  const [confidence, setConfidence] = useState(3);
  const [tags, setTags] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [ok, setOk] = useState(null);
  const [fetchingQuote, setFetchingQuote] = useState(false);
  const [quoteNote, setQuoteNote] = useState(null);

  const action = ACTIONS[side];

  // Groww-style market prefill: picking a symbol (or clicking "live") fetches
  // the current quote and fills the price field. The field stays editable — you
  // can still trade at any price you want; this just saves the lookup.
  async function fillLivePrice(sym) {
    if (!sym) return;
    setFetchingQuote(true);
    setQuoteNote(null);
    try {
      const q = await api.quote(sym);
      setPrice(String(q.price));
      setQuoteNote(q.live ? `live: ${rupees(q.price)}` : `last known: ${rupees(q.price)}`);
    } catch {
      setQuoteNote("no quote found — enter a price manually");
    } finally {
      setFetchingQuote(false);
    }
  }

  const qty = Number(quantity);
  const px = Number(price);
  const cost = qty > 0 && px > 0 ? qty * px : 0;

  // The existing position in this symbol, if any. quantity is signed: positive
  // for a long, negative for a short (matching the engine).
  const pos = holdings?.find((h) => h.symbol === symbol.trim().toUpperCase());
  const posQty = pos?.quantity ?? 0;
  const heldLong = posQty > 0 ? posQty : 0;
  const heldShort = posQty < 0 ? -posQty : 0;

  // --- client-side validation (mirrors the server's rules for instant feedback).
  // The server re-validates too — this is UX, not security.
  const errors = [];
  if (!symbol.trim()) errors.push("symbol required");
  if (!Number.isInteger(qty) || qty <= 0) errors.push("quantity must be a whole number > 0");
  if (!(px > 0)) errors.push("price must be > 0");
  if (!reason.trim()) {
    errors.push(action.opening ? "reason / thesis required" : `reason for ${side}ing required`);
  }
  if (side === "buy") {
    if (cost > cash) errors.push(`not enough cash: need ${rupees(cost)}, have ${rupees(cash)}`);
    if (heldShort) errors.push(`you're short ${heldShort} ${symbol} — use Cover to close it`);
  }
  if (side === "sell") {
    if (heldShort) errors.push(`you're short ${heldShort} ${symbol} — use Cover, not Sell`);
    else if (qty > heldLong) errors.push(`only ${heldLong} shares held`);
  }
  if (side === "short" && heldLong) {
    errors.push(`you hold ${heldLong} ${symbol} long — sell that first`);
  }
  if (side === "cover") {
    if (heldLong) errors.push(`you hold ${symbol} long — use Sell, not Cover`);
    else if (qty > heldShort) errors.push(`only ${heldShort} shares shorted`);
  }
  const valid = errors.length === 0;

  function reset() {
    setSymbol(""); setQuantity(""); setPrice(""); setReason(""); setConfidence(3); setTags("");
  }

  async function submit(e) {
    e.preventDefault();
    if (!valid) return;
    setSubmitting(true);
    setError(null);
    setOk(null);
    try {
      const sym = symbol.trim().toUpperCase();
      const payload = { symbol: sym, quantity: qty, price: px, reason: reason.trim() };
      if (action.opening) {
        payload.confidence = Number(confidence);
        payload.tags = tags.split(",").map((t) => t.trim()).filter(Boolean);
      }
      const res = await api[action.api](name, payload);
      setOk(
        action.opening
          ? `${action.verb} ${qty} ${sym}. Cash now ${rupees(res.cash)}.`
          : `${action.verb} ${qty} ${sym}. Realized ${rupees(res.realized_pnl)}.`
      );
      reset();
      onDone?.();
    } catch (err) {
      setError(err); // server-side rejection (e.g. race on funds) shows here
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="card trade-form" onSubmit={submit}>
      <div className="seg">
        {Object.entries(ACTIONS).map(([key, a]) => (
          <button
            key={key}
            type="button"
            className={side === key ? "on" : ""}
            onClick={() => { setSide(key); setError(null); setOk(null); }}
          >
            {a.label}
          </button>
        ))}
      </div>

      {side === "short" && (
        <p className="muted" style={{ fontSize: 12, margin: "0 0 8px" }}>
          Selling borrowed shares — you profit if the price <strong>falls</strong>.
          No borrow fee or same-day square-off is modeled.
        </p>
      )}

      <div className="row">
        <label>Symbol
          <SymbolSearch
            value={symbol}
            onChange={setSymbol}
            onSelect={(r) => {
              setSymbol(r.symbol);
              fillLivePrice(r.symbol); // picking a stock prefills its market price
            }}
          />
        </label>
        <label>Quantity
          <input type="number" min="1" step="1" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
        </label>
        <label>
          Price (₹)
          <button
            type="button"
            className="link"
            style={{ marginLeft: 6, fontSize: 12 }}
            disabled={!symbol.trim() || fetchingQuote}
            onClick={() => fillLivePrice(symbol.trim())}
          >
            {fetchingQuote ? "…" : "↻ live"}
          </button>
          <input type="number" min="0" step="0.05" value={price} onChange={(e) => setPrice(e.target.value)} />
          {quoteNote && <span className="muted" style={{ fontSize: 12 }}>{quoteNote}</span>}
        </label>
      </div>

      <label>Reason {action.opening ? "/ thesis" : `for ${side}ing`}
        <textarea
          rows={2}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder={
            action.opening
              ? "Why this trade? What's the thesis?"
              : "Target hit? Stop loss? Thesis changed? Panic?"
          }
        />
      </label>

      {/* Journal fields only on OPENING trades — closes inherit them via FIFO. */}
      {action.opening && (
        <div className="row">
          <label>Confidence: <strong>{confidence}</strong>/5
            <input type="range" min="1" max="5" value={confidence} onChange={(e) => setConfidence(e.target.value)} />
          </label>
          <label>Tags (comma-separated)
            <input
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder={side === "short" ? "mean reversion, gap fade" : "earnings play, breakout"}
            />
          </label>
        </div>
      )}

      <div className="trade-meta">
        <span>Order value: <strong>{rupees(cost)}</strong></span>
        {side === "buy" && <span className="muted"> · cash after: {rupees(cash - cost)}</span>}
        {side === "short" && <span className="muted"> · proceeds credited: {rupees(cost)}</span>}
        {side === "sell" && symbol.trim() && <span className="muted"> · held: {heldLong}</span>}
        {side === "cover" && symbol.trim() && <span className="muted"> · shorted: {heldShort}</span>}
      </div>

      {/* live validation feedback before submit */}
      {!valid && (quantity || price || symbol) && (
        <ul className="hints">{errors.map((e) => <li key={e}>{e}</li>)}</ul>
      )}
      {error && <div className="inline-error"><strong>{error.type}:</strong> {error.message}</div>}
      {ok && <div className="inline-ok">{ok}</div>}

      <button className={action.cls} disabled={!valid || submitting}>
        {submitting ? "Submitting…" : action.label}
      </button>
    </form>
  );
}
