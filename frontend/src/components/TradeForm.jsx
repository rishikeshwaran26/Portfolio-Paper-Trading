import { useState } from "react";
import { api } from "../api.js";
import { rupees } from "../format.js";
import SymbolSearch from "./SymbolSearch.jsx";

// The buy/sell form. It carries the trade journal fields (reason, confidence,
// tags) because capturing WHY is the whole point of this project — not just
// quantity/price.
//
// State placement: every input here is local component state. The parent passes
// down what the form needs to VALIDATE against (cash for buys, holdings for
// sells) but the parent does NOT own the keystrokes. On a successful trade the
// form calls onDone() so the parent refetches the (now changed) strategy.
export default function TradeForm({ name, cash, holdings, onDone }) {
  const [side, setSide] = useState("buy"); // "buy" | "sell"
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

  // How many shares of this symbol we currently hold (for sell validation).
  const held = holdings?.find((h) => h.symbol === symbol.trim().toUpperCase())?.quantity ?? 0;

  // --- client-side validation (mirrors the server's rules for instant feedback).
  // The server re-validates too — this is UX, not security.
  const errors = [];
  if (!symbol.trim()) errors.push("symbol required");
  if (!Number.isInteger(qty) || qty <= 0) errors.push("quantity must be a whole number > 0");
  if (!(px > 0)) errors.push("price must be > 0");
  if (!reason.trim()) errors.push(side === "buy" ? "reason / thesis required" : "reason for selling required");
  if (side === "buy" && cost > cash) errors.push(`not enough cash: need ${rupees(cost)}, have ${rupees(cash)}`);
  if (side === "sell" && qty > held) errors.push(`only ${held} shares held`);
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
      if (side === "buy") {
        const tagList = tags.split(",").map((t) => t.trim()).filter(Boolean);
        const res = await api.buy(name, {
          symbol: sym, quantity: qty, price: px, reason: reason.trim(),
          confidence: Number(confidence), tags: tagList,
        });
        setOk(`Bought ${qty} ${sym}. Cash left ${rupees(res.cash)}.`);
      } else {
        const res = await api.sell(name, { symbol: sym, quantity: qty, price: px, reason: reason.trim() });
        setOk(`Sold ${qty} ${sym}. Realized ${rupees(res.realized_pnl)}.`);
      }
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
        <button type="button" className={side === "buy" ? "on" : ""} onClick={() => setSide("buy")}>Buy</button>
        <button type="button" className={side === "sell" ? "on" : ""} onClick={() => setSide("sell")}>Sell</button>
      </div>

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

      <label>Reason {side === "buy" ? "/ thesis" : "for selling"}
        <textarea
          rows={2}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder={side === "buy" ? "Why this trade? What's the thesis?" : "Target hit? Stop loss? Thesis changed? Panic?"}
        />
      </label>

      {side === "buy" && (
        <div className="row">
          <label>Confidence: <strong>{confidence}</strong>/5
            <input type="range" min="1" max="5" value={confidence} onChange={(e) => setConfidence(e.target.value)} />
          </label>
          <label>Tags (comma-separated)
            <input value={tags} onChange={(e) => setTags(e.target.value)} placeholder="earnings play, breakout" />
          </label>
        </div>
      )}

      <div className="trade-meta">
        <span>Order value: <strong>{rupees(cost)}</strong></span>
        {side === "buy" && <span className="muted"> · cash after: {rupees(cash - cost)}</span>}
        {side === "sell" && symbol.trim() && <span className="muted"> · held: {held}</span>}
      </div>

      {/* live validation feedback before submit */}
      {!valid && (quantity || price || symbol) && (
        <ul className="hints">{errors.map((e) => <li key={e}>{e}</li>)}</ul>
      )}
      {error && <div className="inline-error"><strong>{error.type}:</strong> {error.message}</div>}
      {ok && <div className="inline-ok">{ok}</div>}

      <button className={side === "buy" ? "primary" : "danger"} disabled={!valid || submitting}>
        {submitting ? "Submitting…" : side === "buy" ? "Buy" : "Sell"}
      </button>
    </form>
  );
}
