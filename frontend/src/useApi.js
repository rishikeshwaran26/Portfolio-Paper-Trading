import { useEffect, useRef, useState } from "react";

// The loading/error/data pattern, written once and reused by every page that
// reads from the API. A page calls useApi(...) and gets back exactly the three
// states the UI has to render — loading, error, or data — plus reload().
//
// `fn`   : a function returning a promise (e.g. () => api.getStrategy(name))
// `deps` : re-run the fetch when these change (like useEffect deps)
// `opts.refreshMs` : poll silently every N ms — this is what makes prices and
//   P&L update on their own like a real trading app. Background refreshes only
//   swap in NEW DATA on success; they never flip `loading` (no flicker) and
//   never surface transient errors (a single failed poll shouldn't paint the
//   screen red — the next one usually succeeds). Polling pauses while the tab
//   is hidden: no point hammering the API for a page nobody is looking at.
export function useApi(fn, deps = [], { refreshMs } = {}) {
  const [state, setState] = useState({ data: null, loading: true, error: null });
  const [nonce, setNonce] = useState(0); // bump to force a full (visible) refetch
  const fnRef = useRef(fn);
  fnRef.current = fn; // always call the latest closure without re-running effects

  useEffect(() => {
    let alive = true; // guard against setting state after unmount
    setState((s) => ({ ...s, loading: true, error: null }));
    fnRef.current()
      .then((data) => alive && setState({ data, loading: false, error: null }))
      .catch((error) => alive && setState({ data: null, loading: false, error }));
    return () => {
      alive = false;
    };
    // Keyed on caller-provided deps + nonce, not on `fn` (a new closure every
    // render) — deliberate, standard for this hook shape.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  useEffect(() => {
    if (!refreshMs) return;
    let alive = true;
    const id = setInterval(() => {
      if (document.hidden) return; // tab in background -> skip this tick
      fnRef.current()
        .then((data) => alive && setState((s) => ({ ...s, data, error: null })))
        .catch(() => {}); // silent — see note above
    }, refreshMs);
    return () => {
      alive = false;
      clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshMs, ...deps]);

  return { ...state, reload: () => setNonce((n) => n + 1) };
}
