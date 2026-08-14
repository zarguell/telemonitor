import React, { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api";
import type { TgStatus } from "../types";

const STEPS = ["Acknowledge", "Credentials", "Phone", "Code", "2FA", "Connected"];

function stepIndex(state: string): number {
  switch (state) {
    case "not_configured":
    case "initialization_required":
      return 0;
    case "waiting_phone":
      return 2;
    case "waiting_code":
      return 3;
    case "waiting_2fa":
      return 4;
    case "authorized":
      return 5;
    case "disconnected":
    case "reconnecting":
    case "error":
      return 0;
    default:
      return 0;
  }
}

export default function TelegramConfig() {
  const [status, setStatus] = useState<TgStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [ack, setAck] = useState(false);
  const [apiId, setApiId] = useState("");
  const [apiHash, setApiHash] = useState("");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setStatus(await api.tgStatus());
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
    }
  }, []);

  useEffect(() => {
    void refresh();
    const t = setInterval(() => void refresh(), 5000);
    return () => clearInterval(t);
  }, [refresh]);

  const run = async (fn: () => Promise<TgStatus>) => {
    setBusy(true);
    setError(null);
    try {
      setStatus(await fn());
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
    } finally {
      setBusy(false);
    }
  };

  const state = status?.state ?? "not_configured";
  const idx = stepIndex(state);

  return (
    <div>
      <h1>Telegram Configuration</h1>
      <p className="page-sub">
        Configure the dedicated monitoring account. Secrets (API hash, codes, passwords) are handled
        in memory only and never stored or displayed.
      </p>

      <div className="steps">
        {STEPS.map((s, i) => (
          <span key={s} className={`step ${i < idx ? "done" : i === idx ? "current" : ""}`}>
            {i < idx ? "✓ " : ""}
            {s}
          </span>
        ))}
      </div>

      {status?.simulated && (
        <div className="ok-box">Simulated Telegram mode is active (TM_SIMULATE_TELEGRAM=1). No real account needed.</div>
      )}
      {error && <div className="error-box">{error}</div>}

      <div className="card">
        {state === "authorized" && (
          <>
            <h2>Connected</h2>
            <div className="detail-row">
              <span className="k">Account</span>
              <span>{status?.connected_account || "configured account"}</span>
            </div>
            <div className="detail-row">
              <span className="k">State</span>
              <span>{status?.detail || "connected"}</span>
            </div>
            <div className="detail-row">
              <span className="k">Last update</span>
              <span className="mono">{status?.last_update ?? "—"}</span>
            </div>
            <div className="detail-row">
              <span className="k">Encryption key ref</span>
              <span className="mono">{status?.encryption_key_fingerprint ?? "—"}</span>
            </div>
            <div className="btn-row" style={{ marginTop: 14 }}>
              <button className="btn btn-ghost" disabled={busy} onClick={() => run(() => api.tgTest())}>
                Test status
              </button>
              {confirmDisconnect ? (
                <>
                  <span className="muted">Revoke the local session? This stops collection.</span>
                  <button
                    className="btn btn-danger"
                    disabled={busy}
                    onClick={() => {
                      void run(() => api.tgDisconnect(true));
                      setConfirmDisconnect(false);
                    }}
                  >
                    Confirm disconnect
                  </button>
                  <button className="btn btn-ghost" onClick={() => setConfirmDisconnect(false)}>
                    Cancel
                  </button>
                </>
              ) : (
                <button className="btn btn-danger" onClick={() => setConfirmDisconnect(true)}>
                  Disconnect / revoke session
                </button>
              )}
            </div>
          </>
        )}

        {(state === "not_configured" || state === "initialization_required" || state === "disconnected" || state === "error") && (
          <>
            <h2>Authorization & acceptable use</h2>
            <label className="checkline">
              <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} style={{ width: "auto", marginRight: 8 }} />
              I am authorized to use this Telegram account on behalf of my organization, and I have
              reviewed applicable platform, privacy, and organizational requirements before enabling
              monitoring.
            </label>

            <div className="form-row">
              <div>
                <label>API ID</label>
                <input value={apiId} onChange={(e) => setApiId(e.target.value)} placeholder="1234567" disabled={busy} />
              </div>
              <div>
                <label>API hash</label>
                <input type="password" value={apiHash} onChange={(e) => setApiHash(e.target.value)} placeholder="32 hex chars" disabled={busy} />
              </div>
            </div>
            <div style={{ marginTop: 14 }}>
              <button
                className="btn"
                disabled={busy || !ack || !apiId || !apiHash}
                onClick={() => run(() => api.tgInitialize(apiId, apiHash, ack))}
              >
                {busy ? "Connecting…" : "Connect"}
              </button>
            </div>
          </>
        )}

        {state === "waiting_phone" && (
          <>
            <h2>Enter phone number</h2>
            <label>Phone (E.164)</label>
            <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+15551234567" disabled={busy} />
            <div style={{ marginTop: 14 }}>
              <button className="btn" disabled={busy || !phone} onClick={() => run(() => api.tgPhone(phone))}>
                {busy ? "Sending…" : "Request code"}
              </button>
            </div>
          </>
        )}

        {state === "waiting_code" && (
          <>
            <h2>One-time code</h2>
            <p className="muted">Enter the code Telegram sent. It is used in memory only and never stored.</p>
            <label>Code</label>
            <input value={code} onChange={(e) => setCode(e.target.value)} disabled={busy} />
            <div style={{ marginTop: 14 }}>
              <button className="btn" disabled={busy || !code} onClick={() => run(() => api.tgCode(code))}>
                {busy ? "Submitting…" : "Submit code"}
              </button>
            </div>
          </>
        )}

        {state === "waiting_2fa" && (
          <>
            <h2>Two-factor password</h2>
            <p className="muted">Telegram requested the account's 2FA password. It is used in memory only and never stored.</p>
            <label>Password</label>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} disabled={busy} />
            <div style={{ marginTop: 14 }}>
              <button className="btn" disabled={busy || !password} onClick={() => run(() => api.tgPassword(password))}>
                {busy ? "Submitting…" : "Submit password"}
              </button>
            </div>
          </>
        )}

        {state === "reconnecting" && <p className="muted">Reconnecting…</p>}

        {status?.error && (
          <div className="error-box" style={{ marginTop: 12 }}>
            Last error: {status.error}
          </div>
        )}
      </div>
    </div>
  );
}
