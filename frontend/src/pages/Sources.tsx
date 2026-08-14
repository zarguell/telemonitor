import React, { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api";
import type { DiscoveredSource, Source } from "../types";

const BACKFILL_MODES = [
  { value: "none", label: "No history" },
  { value: "last_24h", label: "Last 24 hours" },
  { value: "last_7d", label: "Last 7 days" },
  { value: "last_30d", label: "Last 30 days" },
  { value: "custom", label: "Custom date" },
];

export default function Sources() {
  const [monitored, setMonitored] = useState<Source[]>([]);
  const [discovered, setDiscovered] = useState<DiscoveredSource[]>([]);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState<DiscoveredSource | null>(null);
  const [backfill, setBackfill] = useState("last_24h");
  const [customDate, setCustomDate] = useState("");
  const [label, setLabel] = useState("");

  const load = useCallback(async () => {
    try {
      const [m, d] = await Promise.all([api.sources(), api.discovered().catch(() => [])]);
      setMonitored(m.items);
      setDiscovered(d);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
    }
  }, []);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 8000);
    return () => clearInterval(t);
  }, [load]);

  const addSource = async () => {
    if (!adding) return;
    setBusy(true);
    setError(null);
    try {
      const body: Record<string, unknown> = {
        telegram_chat_id: adding.chat_id,
        title: adding.title,
        username: adding.username,
        type: adding.type,
        enabled: true,
        label: label || undefined,
        backfill: {
          mode: backfill,
          ...(backfill === "custom" ? { custom_start: new Date(customDate).toISOString() } : {}),
        },
      };
      await api.createSource(body);
      setAdding(null);
      setLabel("");
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
    } finally {
      setBusy(false);
    }
  };

  const toggle = async (s: Source) => {
    try {
      await api.patchSource(s.id, { enabled: !s.enabled });
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
    }
  };

  const filtered = discovered.filter(
    (d) =>
      !d.allowlisted &&
      (d.title.toLowerCase().includes(filter.toLowerCase()) ||
        (d.username ?? "").toLowerCase().includes(filter.toLowerCase()) ||
        d.type.includes(filter.toLowerCase()))
  );

  const statusBadge = (s: string) => {
    const cls = s === "live" ? "green" : s === "backfilling" ? "yellow" : s === "error" ? "red" : s === "paused" ? "" : "blue";
    return <span className={`badge ${cls}`}>{s}</span>;
  };

  return (
    <div>
      <h1>Sources</h1>
      <p className="page-sub">
        Channels are only monitored after an operator explicitly adds them to the allowlist. The collector
        ignores everything else.
      </p>
      {error && <div className="error-box">{error}</div>}

      <div className="card">
        <div className="card-title">
          <span>Accessible sources</span>
          <input
            placeholder="Filter by title, username, type…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            style={{ width: 260 }}
          />
        </div>
        {filtered.length === 0 && <div className="empty">No accessible sources (authorize the Telegram account first)</div>}
        <table>
          <thead>
            <tr>
              <th>Title</th>
              <th>Username</th>
              <th>Type</th>
              <th>Last activity</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {filtered.slice(0, 100).map((d) => (
              <tr key={d.chat_id}>
                <td>{d.title}</td>
                <td className="mono">{d.username ?? "—"}</td>
                <td>{d.type}</td>
                <td className="mono">{d.last_activity_at ? new Date(d.last_activity_at).toLocaleString() : "—"}</td>
                <td>
                  <button className="btn btn-sm" onClick={() => setAdding(d)}>
                    Add to monitoring
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <div className="card-title">
          <span>Monitored sources ({monitored.length})</span>
        </div>
        {monitored.length === 0 && <div className="empty">Nothing allowlisted yet</div>}
        <table>
          <thead>
            <tr>
              <th>Title</th>
              <th>Chat ID</th>
              <th>Status</th>
              <th>Backfill</th>
              <th>Progress</th>
              <th>Last message</th>
              <th>Error</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {monitored.map((s) => (
              <tr key={s.id}>
                <td>
                  {s.title}
                  {s.label && <div className="muted">{s.label}</div>}
                </td>
                <td className="mono">{s.telegram_chat_id}</td>
                <td>{statusBadge(s.status)}</td>
                <td className="mono">{s.backfill_mode}</td>
                <td>
                  {s.backfill_total ? `${s.backfill_progress}%` : "—"}
                  {s.backfill_error && <div className="muted red">{s.backfill_error}</div>}
                </td>
                <td className="mono">{s.last_message_at ? new Date(s.last_message_at).toLocaleString() : "—"}</td>
                <td className="mono">{s.last_error ?? "—"}</td>
                <td>
                  <button className={`btn btn-sm ${s.enabled ? "btn-ghost" : ""}`} onClick={() => toggle(s)}>
                    {s.enabled ? "Pause" : "Enable"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {adding && (
        <div className="modal-backdrop" onClick={() => setAdding(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>Approve & monitor “{adding.title}”</h2>
            <p className="muted">
              Confirm this source is approved for monitoring by your organization. Telegram chat ID{" "}
              <span className="mono">{adding.chat_id}</span>
            </p>
            <label>Source label (optional)</label>
            <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. Partner feed — approved" />
            <label>Historical backfill</label>
            <select value={backfill} onChange={(e) => setBackfill(e.target.value)}>
              {BACKFILL_MODES.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
            {backfill === "custom" && (
              <>
                <label>Earliest timestamp</label>
                <input type="datetime-local" value={customDate} onChange={(e) => setCustomDate(e.target.value)} />
              </>
            )}
            <div className="btn-row" style={{ marginTop: 16 }}>
              <button className="btn" disabled={busy || (backfill === "custom" && !customDate)} onClick={() => void addSource()}>
                {busy ? "Adding…" : "Confirm and add to allowlist"}
              </button>
              <button className="btn btn-ghost" onClick={() => setAdding(null)}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
