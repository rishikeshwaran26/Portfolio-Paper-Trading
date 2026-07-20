import { rupees, pnl, signClass } from "../format.js";

// Presentational table of open positions. Data in via props; nothing else.
export default function HoldingsTable({ holdings, selected, onSelect }) {
  if (!holdings || holdings.length === 0) {
    return <p className="muted">No open holdings.</p>;
  }
  return (
    <table className="table">
      <thead>
        <tr>
          <th>Symbol</th><th className="num">Qty</th><th className="num">Avg</th>
          <th className="num">LTP</th><th className="num">Mkt value</th><th className="num">Unrealized</th>
        </tr>
      </thead>
      <tbody>
        {holdings.map((h) => (
          <tr
            key={h.symbol}
            onClick={() => onSelect?.(h.symbol)}
            className={`${onSelect ? "clickable" : ""} ${selected === h.symbol ? "selected" : ""}`}
          >
            <td>{h.symbol}</td>
            <td className="num">{h.quantity}</td>
            <td className="num">{rupees(h.avg_price)}</td>
            <td className="num">
              {rupees(h.last_price)}
              {!h.priced && <span className="tag warn" title="No live price set — valued at cost">@cost</span>}
            </td>
            <td className="num">{rupees(h.market_value)}</td>
            <td className={`num ${signClass(h.unrealized_pnl)}`}>{pnl(h.unrealized_pnl)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
