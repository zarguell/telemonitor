import React, { useState } from "react";
import { api, ApiError } from "../api";
import { useAuth } from "../App";

export default function Login() {
  const { setUser } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api.login(username, password);
      setUser(r.user);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Login failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-wrap">
      <form className="card login-card" onSubmit={submit}>
        <h1>Telemonitor</h1>
        <p className="page-sub">Authorized Telegram monitoring console</p>
        {error && <div className="error-box">{error}</div>}
        <label>Username</label>
        <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
        <label>Password</label>
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        <div style={{ marginTop: 16 }}>
          <button className="btn" disabled={busy || !username || !password}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </div>
        <p className="muted" style={{ marginTop: 16, fontSize: 12 }}>
          Credentials are provisioned by your administrator; no default accounts exist.
        </p>
      </form>
    </div>
  );
}
