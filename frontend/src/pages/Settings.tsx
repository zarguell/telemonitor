import React, { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api";
import type { User } from "../types";

export default function Settings() {
  const [retention, setRetention] = useState(90);
  const [destType, setDestType] = useState("none");
  const [webhookUrl, setWebhookUrl] = useState("");
  const [botToken, setBotToken] = useState("");
  const [botChatId, setBotChatId] = useState("");
  const [destDirty, setDestDirty] = useState(false);
  const [aliases, setAliases] = useState<{ alias: string; canonical?: string }[]>([]);
  const [storeMedia, setStoreMedia] = useState(false);
  const [users, setUsers] = useState<User[]>([]);
  const [newUser, setNewUser] = useState({ username: "", password: "", role: "analyst" });
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, u] = await Promise.all([api.settings(), api.users()]);
      setRetention(s.retention_days);
      setDestType(String(s.alert_destination.type ?? "none"));
      // Secrets are never returned; only the masked summary is shown.
      setWebhookUrl(String(s.alert_destination.url ?? ""));
      setBotChatId(String(s.alert_destination.chat_id ?? ""));
      setAliases(s.aliases ?? []);
      setStoreMedia(Boolean(s.media_settings?.store_media));
      setUsers(u.items);
      setDestDirty(false);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async () => {
    setError(null);
    setOk(null);
    try {
      const body: Record<string, unknown> = {
        retention_days: retention,
        aliases: aliases.filter((a) => a.alias),
        media_settings: { store_media: storeMedia },
      };
      // Only send the destination when the operator actually edited it — the
      // server never returns secrets, so a plain "Save" must not clobber them.
      if (destDirty) {
        if (destType === "webhook") {
          body.alert_destination = { type: "webhook", url: webhookUrl };
        } else if (destType === "telegram_bot") {
          body.alert_destination = { type: "telegram_bot", token: botToken, chat_id: botChatId };
        } else {
          body.alert_destination = { type: "none" };
        }
      }
      await api.updateSettings(body);
      setBotToken("");
      setOk("Settings saved");
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
    }
  };

  const testDest = async () => {
    setError(null);
    setOk(null);
    try {
      const r = await api.testDestination();
      setOk(r.ok ? `Destination test OK (HTTP ${r.status_code})` : `Destination test failed: ${r.error}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
    }
  };

  const createUser = async () => {
    setError(null);
    try {
      await api.createUser(newUser);
      setNewUser({ username: "", password: "", role: "analyst" });
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
    }
  };

  const setUserActive = async (u: User, active: boolean) => {
    try {
      await api.patchUser(u.id, { is_active: active });
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
    }
  };

  return (
    <div>
      <h1>Settings</h1>
      <p className="page-sub">Global configuration — Administrators only</p>
      {error && <div className="error-box">{error}</div>}
      {ok && <div className="ok-box">{ok}</div>}

      <div className="card">
        <h2>Retention</h2>
        <p className="muted">
          Message content, extracted indicators, and search records older than this are deleted by the
          maintenance worker. Audit metadata is preserved.
        </p>
        <label>Retention period (days)</label>
        <input type="number" min={0} max={3650} value={retention} onChange={(e) => setRetention(Number(e.target.value))} style={{ width: 160 }} />
      </div>

      <div className="card">
        <h2>Media storage</h2>
        <p className="muted">
          When enabled, the collector downloads and stores images from monitored
          messages on the local media volume (abstracted behind a MediaStore, so
          an object store can be plugged in later). Images are never analyzed —
          this is storage and display only. Disabled = metadata only (PRD
          default). Already-ingested messages are backfilled by the maintenance
          worker within a minute.
        </p>
        <label className="checkline" style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <input
            type="checkbox"
            checked={storeMedia}
            onChange={(e) => setStoreMedia(e.target.checked)}
            style={{ width: "auto" }}
          />
          Store and display images from monitored messages
        </label>
      </div>

      <div className="card">
        <h2>Alert destination</h2>
        <p className="muted">One approved internal destination: webhook or Telegram bot. Testable from here.</p>
        <label>Type</label>
        <select value={destType} onChange={(e) => { setDestType(e.target.value); setDestDirty(true); }}>
          <option value="none">None</option>
          <option value="webhook">Webhook</option>
          <option value="telegram_bot">Telegram bot</option>
        </select>
        {destType === "webhook" && (
          <>
            <label>Webhook URL</label>
            <input value={webhookUrl} onChange={(e) => { setWebhookUrl(e.target.value); setDestDirty(true); }} placeholder="https://hooks.internal.example/…" />
            <div className="muted" style={{ fontSize: 12 }}>
              {destDirty ? "" : "Saved URL is masked for security; re-enter it only when changing the destination."}
            </div>
          </>
        )}
        {destType === "telegram_bot" && (
          <>
            <label>Bot token</label>
            <input type="password" value={botToken} onChange={(e) => { setBotToken(e.target.value); setDestDirty(true); }} placeholder="stored encrypted (leave empty to keep the saved token)" />
            <label>Chat ID</label>
            <input value={botChatId} onChange={(e) => { setBotChatId(e.target.value); setDestDirty(true); }} placeholder="-1001234567890" />
          </>
        )}
        <div className="btn-row" style={{ marginTop: 12 }}>
          <button className="btn" onClick={() => void save()}>Save settings</button>
          <button className="btn btn-ghost" onClick={() => void testDest()} disabled={destType === "none"}>
            Test destination
          </button>
        </div>
      </div>

      <div className="card">
        <h2>User-defined aliases</h2>
        <p className="muted">
          Company names, product names, and keywords extracted as <span className="mono">alias</span> indicators
          (canonical form used for matching).
        </p>
        {aliases.map((a, i) => (
          <div className="form-row" key={i} style={{ marginBottom: 6 }}>
            <input value={a.alias} placeholder="alias" onChange={(e) => setAliases(aliases.map((x, j) => (j === i ? { ...x, alias: e.target.value } : x)))} />
            <input value={a.canonical ?? ""} placeholder="canonical (optional)" onChange={(e) => setAliases(aliases.map((x, j) => (j === i ? { ...x, canonical: e.target.value } : x)))} />
            <button className="btn btn-sm btn-ghost" onClick={() => setAliases(aliases.filter((_, j) => j !== i))}>Remove</button>
          </div>
        ))}
        <button className="btn btn-sm btn-ghost" onClick={() => setAliases([...aliases, { alias: "" }])}>
          + Add alias
        </button>
      </div>

      <div className="card">
        <h2>Users & roles</h2>
        <table>
          <thead>
            <tr>
              <th>Username</th>
              <th>Role</th>
              <th>Active</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td>{u.username}</td>
                <td>{u.role}</td>
                <td>{u.is_active ? <span className="badge green">active</span> : <span className="badge red">disabled</span>}</td>
                <td>
                  {u.id !== 1 && (
                    <button className="btn btn-sm btn-ghost" onClick={() => void setUserActive(u, !u.is_active)}>
                      {u.is_active ? "Disable" : "Enable"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <h3 style={{ marginTop: 16 }}>Add user</h3>
        <div className="form-row">
          <input placeholder="username" value={newUser.username} onChange={(e) => setNewUser({ ...newUser, username: e.target.value })} />
          <input type="password" placeholder="password (8+ chars)" value={newUser.password} onChange={(e) => setNewUser({ ...newUser, password: e.target.value })} />
          <select value={newUser.role} onChange={(e) => setNewUser({ ...newUser, role: e.target.value })}>
            <option value="analyst">Analyst</option>
            <option value="operator">Operator</option>
            <option value="admin">Administrator</option>
          </select>
          <button className="btn" onClick={() => void createUser()} disabled={!newUser.username || newUser.password.length < 8}>
            Create
          </button>
        </div>
      </div>
    </div>
  );
}
