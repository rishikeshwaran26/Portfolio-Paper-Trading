import { rupees, pnl, signClass, when } from "../format.js";

// Presentational transaction history. Newest first. Buys are green-ish, sells
// carry their realized P&L. Data in via props.
export default function TransactionList({ transactions }) {
  if (!transactions || transactions.length === 0) {
    return <p className="muted">No transactions yet.</p>;
  }
  const rows = [...transactions].reverse(); // newest first
  return (
    <table className="table">
      <thead>
        <tr>
          <th>When</th><th>Type</th><th>Symbol</th><th className="num">Qty</th>
          <th className="num">Price</th><th className="num">Realized</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((t) => (
          <tr key={t.id}>
            <td className="muted">{when(t.timestamp)}</td>
            <td><span className={`tag ${t.type === "BUY" ? "buy" : "sell"}`}>{t.type}</span></td>
            <td>{t.symbol}</td>
            <td className="num">{t.quantity}</td>
            <td className="num">{rupees(t.price)}</td>
            <td className={`num ${signClass(t.realized_pnl)}`}>
              {t.realized_pnl == null ? "—" : pnl(t.realized_pnl)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
