// Two tiny presentational components used by every page so loading and error
// states look the same everywhere. Requirement: every API call must show both.

export function Loading({ label = "Loading…" }) {
  return <div className="status loading">{label}</div>;
}

export function ErrorBanner({ error, onRetry }) {
  if (!error) return null;
  return (
    <div className="status error">
      <strong>{error.type || "Error"}:</strong> {error.message}
      {onRetry && (
        <button className="link" onClick={onRetry} style={{ marginLeft: 8 }}>
          retry
        </button>
      )}
    </div>
  );
}
