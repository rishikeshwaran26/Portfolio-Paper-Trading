import { NavLink } from "react-router-dom";
import { useApi } from "../useApi.js";
import { api } from "../api.js";

// The frame around every page: top nav + the routed page content (children).
// It fetches one small thing of its own — the price-source status — because the
// indicator lives in the chrome, not in any single page.
export default function Layout({ children, user, onLogout }) {
  const { data: src } = useApi(() => api.priceSources(), []);
  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          📈 Paper Trading <span className="muted">NSE/BSE</span>
          {src && (
            <span className="source-chip" style={{ marginLeft: 10 }} title={`source: ${src.mode}${src.nse.reachable ? " · NSE live" : " · NSE unreachable, using fallback"}`}>
              <span className={`live-dot ${src.market_open ? "" : "closed"}`} />
              {src.market_open ? "market open" : "market closed"}
              {" · "}
              {src.nse.reachable ? "NSE live" : "delayed"}
            </span>
          )}
        </div>
        <nav>
          <NavLink to="/" end>Dashboard</NavLink>
          <NavLink to="/watchlist">Watchlist</NavLink>
          <NavLink to="/screener">Screener</NavLink>
          <NavLink to="/leaderboard">Leaderboard</NavLink>
          <NavLink to="/compare">Compare</NavLink>
          <NavLink to="/alerts">Alerts</NavLink>
          {user && (
            <span className="user-chip">
              {user.username}
              <button className="link" onClick={onLogout} style={{ marginLeft: 8 }}>log out</button>
            </span>
          )}
        </nav>
      </header>
      <main className="content">{children}</main>
      <footer className="foot muted">
        Virtual money only · prices are manual until Phase 4 wires up live NSE data
      </footer>
    </div>
  );
}
