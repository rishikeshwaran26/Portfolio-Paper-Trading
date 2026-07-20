import { rupees, pnl, signClass } from "../format.js";

// Presentational table of open positions — long and short. The engine stores a
// short as a negative quantity; here we display abs(qty) plus a SHORT badge,
// because "-10 shares" reads like a bug to a person. Data in via props.
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
            <td>
              {h.symbol}
              {h.side === "short" && <span className="tag short" title="Short position — profits if the price falls">SHORT</span>}
            </td>
            <td className="num">{Math.abs(h.quantity)}</td>
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
