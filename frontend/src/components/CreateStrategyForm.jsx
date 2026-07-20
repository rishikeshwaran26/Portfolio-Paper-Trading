import { useState } from "react";
import { api } from "../api.js";

// A small self-contained form. It owns ONLY its own input state and its own
// submit loading/error — that's the rule of thumb: form state lives in the form.
// When the create succeeds it calls onCreated() so the PARENT can refetch the
// list. The form doesn't own the list, so it just signals "something changed".
export default function CreateStrategyForm({ onCreated }) {
  const [name, setName] = useState("");
  const [cash, setCash] = useState("1000000");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const valid = name.trim().length > 0 && Number(cash) > 0;

  async function submit(e) {
    e.preventDefault();
    if (!valid) return;
    setSubmitting(true);
    setError(null);
    try {
      await api.createStrategy(name.trim(), Number(cash));
      setName("");
      setCash("1000000");
      onCreated?.();
    } catch (err) {
      setError(err);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="card create-form" onSubmit={submit}>
      <div className="card-title">New strategy</div>
      <div className="row">
        <label>
          Name
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Momentum Strategy"
          />
        </label>
        <label>
          Starting cash (₹)
          <input type="number" min="1" value={cash} onChange={(e) => setCash(e.target.value)} />
        </label>
      </div>
      {error && <div className="inline-error">{error.message}</div>}
      <button className="primary" disabled={!valid || submitting}>
        {submitting ? "Creating…" : "Create strategy"}
      </button>
    </form>
  );
}
