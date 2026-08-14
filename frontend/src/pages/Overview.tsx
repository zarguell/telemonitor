import React, { useEffect, useState } from "react";
import { api } from "../api";
import type { Health, Overview } from "../types";

function Stat({ value, label }: { value: React.ReactNode; label: string }) {
  return (
    <div className="stat">
      <div className="value">{value}</div>
      <div className="label">{label}</div>
    </div>
  );
}

export default function Overview() {
  const [ov, setOv] = useState<Overview | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const [o, h] = await Promise.all([api.overview(), api.health()]);
        if (alive) {
          setOv(o);
          setHealth(h);
        }
      } catch (e) {
        if (alive) setError(String(e));
      }
    };
    load();
    const t = setInterval(load, 15000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  if (error) return <div className="error-box">{error}</div>;
  if (!ov || !health) return <div className="empty">Loading overview…</div>;

  const tgBadge = (() => {
    const s = ov.telegram.state;
    const connected = health.collector.connected;
    if (s === "authorized" && connected) return <span className="badge green">connected</span>;
    if (s === "authorized") return <span className="badge yellow">authorized · collector offline</span>;
    if (s === "waiting_code" || s === "waiting_2fa" || s === "waiting_phone")
      return <span className="badge yellow">{s.replace(/_/g, " ")}</span>;
    if (s === "error") return <span className="badge red">error</span>;
    return <span className="badge">{s.replace(/_/g, " ")}</span>;
  })();

  const workerBadges = Object.entries(health.workers).map(([name, w]) => (
    <span key={name} className={w.status === "up" ? "badge green" : "badge red"}>
      {name} {w.status}
    </span>
  ));

  return (
    <div>
      <h1>Overview</h1>
      <p className="page-sub">Operational status of the monitoring platform</p>

      <div className="grid grid-4">
        <Stat value={tgBadge} label="Telegram connection" />
        <Stat value={ov.enabled_sources} label="Enabled sources" />
        <Stat value={ov.messages_24h} label="Messages (24h)" />
        <Stat value={ov.backfill_in_progress} label="Backfills in progress" />
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-title">Open alerts by severity</div>
        <div className="pill-row">
          {(["critical", "high", "medium", "low", "informational"] as const).map((s) => (
            <span key={s} className={`badge severity-${s}`}>
              {s}: {ov.open_alerts[s] ?? 0}
            </span>
          ))}
          <span className="badge blue">total: {ov.open_alert_total}</span>
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <span>Collector & workers</span>
          <span className="pill-row">{workerBadges}</span>
        </div>
        <div className="detail-row">
          <span className="k">Collector state</span>
          <span>{health.collector.state} {health.collector.detail ? `— ${health.collector.detail}` : ""}</span>
        </div>
        <div className="detail-row">
          <span className="k">Collector heartbeat</span>
          <span className="mono">{health.collector.heartbeat ?? "never"}</span>
        </div>
        <div className="detail-row">
          <span className="k">Database</span>
          <span>{health.database.ok ? <span className="badge green">ok</span> : <span className="badge red">down</span>}</span>
        </div>
      </div>

      <div className="card">
        <div className="card-title">Queues</div>
        <table>
          <thead>
            <tr>
              <th>Queue</th>
              <th>Depth</th>
              <th>Failed</th>
              <th>Last success</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(health.queues).map(([q, st]) => (
              <tr key={q}>
                <td className="mono">{q}</td>
                <td>{st.depth}</td>
                <td>{st.failed > 0 ? <span className="badge red">{st.failed}</span> : st.failed}</td>
                <td className="mono">{st.last_success ?? "—"}</td>
              </tr>
            ))}
            {Object.keys(health.queues).length === 0 && (
              <tr>
                <td colSpan={4} className="empty">No queue activity yet</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="card">
        <div className="card-title">Recent errors</div>
        {ov.recent_errors.length === 0 && <div className="empty">No recent errors</div>}
        {ov.recent_errors.map((e, i) => (
          <div key={i} className="detail-row">
            <span className="k">{e.kind}</span>
            <span className="mono">{e.source ?? `#${e.alert_id ?? ""}`}: {e.error}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
