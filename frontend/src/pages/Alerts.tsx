import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { Alert } from "../types";

const STATES = ["", "open", "acknowledged", "resolved", "false_positive"];
const SEVERITIES = ["", "critical", "high", "medium", "low", "informational"];

function stateBadge(s: string) {
  const cls = s === "open" ? "red" : s === "acknowledged" ? "yellow" : s === "resolved" ? "green" : s === "false_positive" ? "" : "";
  return <span className={`badge ${cls}`}>{s.replace("_", " ")}</span>;
}

export default function Alerts() {
  const [items, setItems] = useState<Alert[]>([]);
  const [total, setTotal] = useState(0);
  const [state, setState] = useState("");
  const [severity, setSeverity] = useState("");
  const [detail, setDetail] = useState<Alert | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await api.alerts({ state: state || undefined, severity: severity || undefined, limit: 100 });
      setItems(r.items);
      setTotal(r.total);
    } catch (e) {
      setError(String(e));
    }
  }, [state, severity]);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 10000);
    return () => clearInterval(t);
  }, [load]);

  const openDetail = async (id: number) => {
    try {
      setDetail(await api.alert(id));
      setNote("");
    } catch (e) {
      setError(String(e));
    }
  };

  const triage = async (next: string) => {
    if (!detail) return;
    try {
      setDetail(await api.triageAlert(detail.id, next, note || undefined));
      await load();
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <div>
      <h1>Alerts</h1>
      <p className="page-sub">Rule matches, deduplicated within each rule's window ({total} total)</p>
      {error && <div className="error-box">{error}</div>}

      <div className="toolbar">
        <select value={state} onChange={(e) => setState(e.target.value)}>
          {STATES.map((s) => (
            <option key={s} value={s}>{s === "" ? "All states" : s.replace("_", " ")}</option>
          ))}
        </select>
        <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
          {SEVERITIES.map((s) => (
            <option key={s} value={s}>{s === "" ? "All severities" : s}</option>
          ))}
        </select>
      </div>

      {items.length === 0 && <div className="empty">No alerts</div>}
      {items.map((a) => (
        <div key={a.id} className="alert-row" onClick={() => void openDetail(a.id)}>
          <div>
            <div>
              <span className={`badge severity-${a.severity}`}>{a.severity}</span>{" "}
              {stateBadge(a.state)}{" "}
              <span className="badge">{a.delivery_state}</span>{" "}
              <strong>#{a.id}</strong> — {a.rule_name ?? `rule ${a.rule_id}`}
            </div>
            <div className="muted" style={{ marginTop: 4 }}>
              {a.excerpt?.slice(0, 220)}
            </div>
          </div>
          <div className="muted" style={{ textAlign: "right", whiteSpace: "nowrap" }}>
            <div>{a.message_count} message(s)</div>
            <div className="mono">{a.source_title ?? "—"}</div>
            <div>{a.created_at ? new Date(a.created_at).toLocaleString() : ""}</div>
          </div>
        </div>
      ))}

      {detail && (
        <div className="modal-backdrop" onClick={() => setDetail(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>
              Alert #{detail.id}{" "}
              <span className={`badge severity-${detail.severity}`}>{detail.severity}</span> {stateBadge(detail.state)}
            </h2>
            <div className="detail-row">
              <span className="k">Rule</span>
              <span>{detail.rule_name ?? "—"} (v{detail.rule_version ?? "?"})</span>
            </div>
            <div className="detail-row">
              <span className="k">Source</span>
              <span>{detail.source_title ?? "—"}</span>
            </div>
            <div className="detail-row">
              <span className="k">First seen</span>
              <span className="mono">{detail.first_seen_at ? new Date(detail.first_seen_at).toLocaleString() : "—"}</span>
            </div>
            <div className="detail-row">
              <span className="k">Last seen</span>
              <span className="mono">{detail.last_seen_at ? new Date(detail.last_seen_at).toLocaleString() : "—"}</span>
            </div>
            <div className="detail-row">
              <span className="k">Messages</span>
              <span>{detail.message_count} (dedupe window {detail.dedupe_window_seconds}s)</span>
            </div>
            <div className="detail-row">
              <span className="k">Delivery</span>
              <span>
                {detail.delivery_state}
                {detail.last_delivery_error && <span className="mono"> — {detail.last_delivery_error}</span>}
              </span>
            </div>

            <h3 style={{ marginTop: 16 }}>Excerpt</h3>
            <div className="card" style={{ background: "var(--bg)" }}>
              {detail.excerpt ?? "—"}
            </div>

            <h3>Linked messages</h3>
            {detail.messages?.map((m) => (
              <div key={m.id} className="card" style={{ background: "var(--bg)" }}>
                <div className="muted mono">
                  #{m.telegram_message_id} · {m.sent_at ? new Date(m.sent_at).toLocaleString() : "—"} · {m.state}
                  {m.permalink && (
                    <>
                      {" "}· <a href={m.permalink} target="_blank" rel="noreferrer">open in Telegram</a>
                    </>
                  )}
                </div>
                <div>{m.text_preview}</div>
                {m.indicators.length > 0 && (
                  <div className="pill-row">
                    {m.indicators.map((ind, i) => (
                      <span key={i} className="badge blue mono">{ind.type}: {ind.value}</span>
                    ))}
                  </div>
                )}
              </div>
            ))}

            {detail.deliveries && detail.deliveries.length > 0 && (
              <>
                <h3>Delivery attempts</h3>
                <table>
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Destination</th>
                      <th>Status</th>
                      <th>Time</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.deliveries.map((d) => (
                      <tr key={d.attempt}>
                        <td>{d.attempt}</td>
                        <td className="mono">{d.destination_type} {d.destination_ref}</td>
                        <td>
                          <span className={`badge ${d.status === "success" ? "green" : "red"}`}>{d.status}</span>
                          {d.error && <div className="muted mono">{d.error}</div>}
                        </td>
                        <td className="mono">{d.attempted_at ? new Date(d.attempted_at).toLocaleString() : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}

            {detail.triage_note && (
              <div className="detail-row">
                <span className="k">Triage note</span>
                <span>{detail.triage_note} <span className="muted">— {detail.triaged_by}</span></span>
              </div>
            )}

            <label>Triage note (optional)</label>
            <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Analyst note…" />
            <div className="btn-row" style={{ marginTop: 12 }}>
              <button className="btn btn-ghost" onClick={() => void triage("acknowledged")}>Acknowledge</button>
              <button className="btn" onClick={() => void triage("resolved")}>Resolve</button>
              <button className="btn btn-danger" onClick={() => void triage("false_positive")}>False positive</button>
              <button className="btn btn-ghost" onClick={() => void triage("open")}>Reopen</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
