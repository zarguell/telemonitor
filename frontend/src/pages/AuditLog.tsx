import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { AuditEvent } from "../types";

export default function AuditLog() {
  const [items, setItems] = useState<AuditEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [action, setAction] = useState("");
  const [actor, setActor] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await api.audit({ action: action || undefined, actor: actor || undefined, limit: 200 });
      setItems(r.items);
      setTotal(r.total);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [action, actor]);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 15000);
    return () => clearInterval(t);
  }, [load]);

  return (
    <div>
      <h1>Audit Log</h1>
      <p className="page-sub">
        Sanitized record of configuration changes, searches, and triage ({total} events)
      </p>
      {error && <div className="error-box">{error}</div>}
      <div className="toolbar">
        <input placeholder="Filter by actor (substring)" value={actor} onChange={(e) => setActor(e.target.value)} />
        <input placeholder="Filter by action (substring, e.g. rule)" value={action} onChange={(e) => setAction(e.target.value)} />
      </div>
      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Actor</th>
              <th>Action</th>
              <th>Object</th>
              <th>Detail</th>
              <th>IP</th>
            </tr>
          </thead>
          <tbody>
            {items.map((e) => (
              <tr key={e.id}>
                <td className="mono">{e.created_at ? new Date(e.created_at).toLocaleString() : "—"}</td>
                <td>{e.actor_username ?? "system"}</td>
                <td className="mono">{e.action}</td>
                <td className="mono">
                  {e.object_type ?? "—"}
                  {e.object_id ? `#${e.object_id}` : ""}
                </td>
                <td className="mono">{JSON.stringify(e.detail ?? {})}</td>
                <td className="mono">{e.ip_address ?? "—"}</td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr>
                <td colSpan={6} className="empty">No audit events</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
