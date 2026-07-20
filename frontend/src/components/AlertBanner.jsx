import { useEffect, useState } from "react";
import { api } from "../api.js";
import { rupees } from "../format.js";

// The in-app notification. Polls /alerts on an interval and shows a banner for
// any alert that has FIRED but not yet been acknowledged.
//
// Why poll from the client at all, when a background thread already checks
// prices server-side? Because the server has no way to push to the browser over
// plain REST. The server decides WHEN an alert fires (authoritative, and it
// keeps working while the tab is closed); the client just asks "anything for me?"
// every few seconds. A WebSocket / SSE would replace this polling later — the
// server-side logic wouldn't change.
export default function AlertBanner() {
  const [triggered, setTriggered] = useState([]);

  useEffect(() => {
    let alive = true;
    const poll = () =>
      api
        .alerts()
        .then((d) => alive && setTriggered(d.triggered))
        .catch(() => {}); // stay silent: a banner poll failing shouldn't shout
    poll();
    const id = setInterval(poll, 10_000);
    return () => {
      alive = false;
      clearInterval(id); // always clear the interval on unmount
    };
  }, []);

  async function dismiss(id) {
    setTriggered((list) => list.filter((a) => a.id !== id)); // optimistic
    try {
      await api.dismissAlert(id);
    } catch {
      /* if it fails the next poll restores it */
    }
  }

  if (triggered.length === 0) return null;

  return (
    <div className="alert-stack">
      {triggered.map((a) => (
        <div key={a.id} className="alert-banner">
          <span className="bell">🔔</span>
          <div>
            <strong>{a.symbol}</strong> went {a.direction} {rupees(a.target_price)} — now{" "}
            <strong>{rupees(a.triggered_price)}</strong>
            {a.note && <div className="muted">{a.note}</div>}
          </div>
          <button className="link" onClick={() => dismiss(a.id)}>dismiss</button>
        </div>
      ))}
    </div>
  );
}
