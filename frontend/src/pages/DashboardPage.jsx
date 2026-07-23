import { useApi } from "../useApi.js";
import { api } from "../api.js";
import { Loading, ErrorBanner } from "../components/Status.jsx";
import StrategyCard from "../components/StrategyCard.jsx";
import CreateStrategyForm from "../components/CreateStrategyForm.jsx";

// DASHBOARD owns one piece of server data: the list of strategies. Because this
// page is where that data is needed and refetched, it lives here (via useApi)
// and flows DOWN as props to the cards. When the create form or anything else
// mutates data, we call reload() to refetch.
export default function DashboardPage() {
  const strategies = useApi(() => api.listStrategies(), [], { refreshMs: 20_000 });

  return (
    <div className="page">
      <h1>Your strategies</h1>

      <CreateStrategyForm onCreated={strategies.reload} />

      {/* Each API read renders its own loading / error / data states. */}
      {strategies.loading && <Loading label="Loading strategies…" />}
      <ErrorBanner error={strategies.error} onRetry={strategies.reload} />

      {strategies.data && strategies.data.strategies.length === 0 && (
        <p className="muted">No strategies yet — create one above to start trading.</p>
      )}

      {strategies.data && strategies.data.strategies.length > 0 && (
        <div className="grid">
          {strategies.data.strategies.map((s) => (
            <StrategyCard key={s.name} s={s} />
          ))}
        </div>
      )}
    </div>
  );
}
