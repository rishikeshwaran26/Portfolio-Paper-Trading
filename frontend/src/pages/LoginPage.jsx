import { useEffect, useState } from "react";
import { api } from "../api.js";
import { setToken } from "../auth.js";

// Login / first-run registration. We ask the backend whether ANY account exists
// (/auth/status) so a fresh install shows "create your account" instead of a
// login form for an account that doesn't exist yet.
export default function LoginPage({ onAuthed }) {
  const [hasUsers, setHasUsers] = useState(null); // null = still checking
  const [mode, setMode] = useState("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .authStatus()
      .then((s) => {
        setHasUsers(s.has_users);
        setMode(s.has_users ? "login" : "register");
      })
      .catch((e) => setError(e));
  }, []);

  const valid =
    username.trim().length >= 3 && password.length >= (mode === "register" ? 8 : 1);

  async function submit(e) {
    e.preventDefault();
    if (!valid) return;
    setSubmitting(true);
    setError(null);
    try {
      const res =
        mode === "register"
          ? await api.register(username.trim(), password)
          : await api.login(username.trim(), password);
      setToken(res.token);
      onAuthed(res.user);
    } catch (err) {
      setError(err);
      setSubmitting(false);
    }
  }

  return (
    <div className="login-wrap">
      <form className="card login-card" onSubmit={submit}>
        <div className="brand" style={{ marginBottom: 4 }}>📈 Paper Trading</div>
        <p className="muted" style={{ marginTop: 0 }}>
          {hasUsers === null
            ? "Connecting…"
            : mode === "register"
            ? "First run — create your account."
            : "Welcome back."}
        </p>

        <label>Username
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
        </label>
        <label>Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={mode === "register" ? "new-password" : "current-password"}
          />
        </label>
        {mode === "register" && (
          <div className="muted" style={{ fontSize: 13 }}>Minimum 8 characters.</div>
        )}

        {error && <div className="inline-error"><strong>{error.type}:</strong> {error.message}</div>}

        <button className="primary" disabled={!valid || submitting} style={{ width: "100%" }}>
          {submitting ? "…" : mode === "register" ? "Create account" : "Log in"}
        </button>

        {/* Once an account exists you can still register another — the backend
            is multi-user ready, so the UI doesn't pretend otherwise. */}
        {hasUsers && (
          <button
            type="button"
            className="link"
            style={{ marginTop: 10 }}
            onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(null); }}
          >
            {mode === "login" ? "create a new account" : "back to log in"}
          </button>
        )}
      </form>
    </div>
  );
}
