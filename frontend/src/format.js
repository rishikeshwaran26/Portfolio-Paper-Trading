// Small display helpers, kept out of components so formatting is consistent
// everywhere and easy to change in one place.

// Indian number grouping (lakh/crore) via the en-IN locale: 1000000 -> 10,00,000.
export const rupees = (n) =>
  "₹" + Number(n || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// P&L values get an explicit + sign so gains and losses read at a glance.
export const pnl = (n) => (Number(n) >= 0 ? "+" : "") + rupees(n);

export const pct = (n) => (Number(n) >= 0 ? "+" : "") + Number(n || 0).toFixed(2) + "%";

// Returns a CSS class name for coloring positive/negative numbers.
export const signClass = (n) => (Number(n) > 0 ? "pos" : Number(n) < 0 ? "neg" : "");

// ISO timestamp -> "2026-07-20 09:13"
export const when = (iso) => (iso ? iso.slice(0, 16).replace("T", " ") : "");
