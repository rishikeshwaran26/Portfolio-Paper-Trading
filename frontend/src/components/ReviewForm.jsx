import { useState } from "react";
import { api } from "../api.js";

// Inline "add a retrospective note" form, shown on closed trades (sells).
// Owns its own text + submit state; calls onSaved() so the journal refetches.
export default function ReviewForm({ name, txnId, onSaved }) {
  const [open, setOpen] = useState(false);
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  if (!open) {
    return <button className="link" onClick={() => setOpen(true)}>+ add retrospective note</button>;
  }

  async function submit(e) {
    e.preventDefault();
    if (!notes.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await api.review(name, txnId, notes.trim());
      onSaved?.();
    } catch (err) {
      setError(err);
      setSubmitting(false);
    }
  }

  return (
    <form className="review-form" onSubmit={submit}>
      <textarea
        rows={2}
        autoFocus
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        placeholder="e.g. sold too early — thesis was right, timing was off"
      />
      {error && <div className="inline-error">{error.message}</div>}
      <div className="row">
        <button className="primary small" disabled={submitting || !notes.trim()}>
          {submitting ? "Saving…" : "Save note"}
        </button>
        <button type="button" className="link" onClick={() => setOpen(false)}>cancel</button>
      </div>
    </form>
  );
}
