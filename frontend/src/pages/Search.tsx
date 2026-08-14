import React, { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import type { SearchResult, Source } from "../types";

export default function Search() {
  const [q, setQ] = useState("");
  const [sources, setSources] = useState<Source[]>([]);
  const [sourceId, setSourceId] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [indicatorType, setIndicatorType] = useState("");
  const [messageState, setMessageState] = useState("");
  const [alertState, setAlertState] = useState("");
  const [items, setItems] = useState<SearchResult[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<SearchResult | null>(null);
  const [rules, setRules] = useState<{ id: number; name: string }[]>([]);
  const [ruleId, setRuleId] = useState("");
  const [searchParams] = useSearchParams();

  useEffect(() => {
    void api.sources().then((r) => setSources(r.items)).catch(() => {});
    void api.rules().then((r) => setRules(r.items.map((x) => ({ id: x.id, name: x.name })))).catch(() => {});
    // Browse mode: a ?source= param (from the Sources page) preselects the
    // channel; an empty query then shows ALL indexed messages, newest first.
    const sourceParam = searchParams.get("source");
    if (sourceParam) {
      setSourceId(sourceParam);
      void runOnce(sourceParam);
    } else {
      void runOnce(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const runOnce = useCallback(
    async (sourceOverride: string | null) => {
      setBusy(true);
      setError(null);
      try {
        const r = await api.search({
          q: q || undefined,
          source_id: sourceOverride || sourceId || undefined,
          start_time: start ? new Date(start).toISOString() : undefined,
          end_time: end ? new Date(end).toISOString() : undefined,
          rule_id: ruleId || undefined,
          indicator_type: indicatorType || undefined,
          message_state: messageState || undefined,
          alert_state: alertState || undefined,
          limit: 50,
          offset: 0,
        });
        setItems(r.items);
        setTotal(r.total);
        setOffset(0);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );

  const run = useCallback(
    async (off = 0) => {
      setBusy(true);
      setError(null);
      try {
        const r = await api.search({
          q: q || undefined,
          source_id: sourceId || undefined,
          start_time: start ? new Date(start).toISOString() : undefined,
          end_time: end ? new Date(end).toISOString() : undefined,
          rule_id: ruleId || undefined,
          indicator_type: indicatorType || undefined,
          message_state: messageState || undefined,
          alert_state: alertState || undefined,
          limit: 50,
          offset: off,
        });
        setItems(r.items);
        setTotal(r.total);
        setOffset(off);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(false);
      }
    },
    [q, sourceId, start, end, ruleId, indicatorType, messageState, alertState]
  );

  return (
    <div>
      <h1>Search</h1>
      <p className="page-sub">Full-text and substring search over normalized message text ({total} results)</p>
      {error && <div className="error-box">{error}</div>}

      <div className="toolbar">
        <input
          placeholder="Search terms, domains, indicators…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void run()}
          style={{ flex: 1, minWidth: 260 }}
        />
        <button className="btn" onClick={() => void run()} disabled={busy}>
          {busy ? "Searching…" : "Search"}
        </button>
      </div>
      <div className="toolbar">
        <select value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
          <option value="">All sources</option>
          {sources.map((s) => (
            <option key={s.id} value={s.id}>{s.title}</option>
          ))}
        </select>
        <input type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} />
        <span className="muted">→</span>
        <input type="datetime-local" value={end} onChange={(e) => setEnd(e.target.value)} />
        <select value={indicatorType} onChange={(e) => setIndicatorType(e.target.value)}>
          <option value="">Any indicator</option>
          {["url", "domain", "ipv4", "ipv6", "email", "hash", "crypto", "telegram_username", "alias"].map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        <select value={messageState} onChange={(e) => setMessageState(e.target.value)}>
          <option value="">Any message state</option>
          {["pending", "processed", "failed", "deleted"].map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <select value={alertState} onChange={(e) => setAlertState(e.target.value)}>
          <option value="">Any alert state</option>
          {["open", "acknowledged", "resolved", "false_positive"].map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <select value={ruleId} onChange={(e) => setRuleId(e.target.value)}>
          <option value="">Any rule</option>
          {rules.map((r) => (
            <option key={r.id} value={r.id}>{r.name}</option>
          ))}
        </select>
      </div>

      {items.length === 0 && !busy && (
        <div className="empty">
          {q ? "No messages match. Try different terms or filters." : "No messages indexed for these filters yet — add or re-index a source to see history."}
        </div>
      )}

      {items.map((m) => (
        <div key={m.id} className="alert-row" onClick={() => setDetail(m)}>
          <div>
            <div>
              <span className="badge">{m.state}</span>{" "}
              <strong>{m.source_name}</strong>{" "}
              <span className="muted mono">#{m.telegram_message_id}</span>{" "}
              {m.alerts.map((a) => (
                <span key={a.id} className={`badge severity-${a.severity}`}>
                  alert #{a.id} · {a.state}
                </span>
              ))}
            </div>
            <div style={{ marginTop: 4 }} dangerouslySetInnerHTML={{ __html: m.snippet }} />
            <div className="pill-row" style={{ marginTop: 4 }}>
              {m.indicators.slice(0, 6).map((ind, i) => (
                <span key={i} className="badge blue mono">{ind.type}: {ind.value}</span>
              ))}
            </div>
          </div>
          <div className="muted" style={{ textAlign: "right", whiteSpace: "nowrap" }}>
            <div>{m.sent_at ? new Date(m.sent_at).toLocaleString() : "—"}</div>
            <div className="mono">{m.source_username ?? ""}</div>
          </div>
        </div>
      ))}

      {total > 50 && (
        <div className="btn-row">
          <button className="btn btn-ghost btn-sm" disabled={offset === 0} onClick={() => void run(Math.max(0, offset - 50))}>
            Previous
          </button>
          <span className="muted">
            {offset + 1}–{Math.min(offset + 50, total)} of {total}
          </span>
          <button className="btn btn-ghost btn-sm" disabled={offset + 50 >= total} onClick={() => void run(offset + 50)}>
            Next
          </button>
        </div>
      )}

      {detail && (
        <div className="modal-backdrop" onClick={() => setDetail(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>
              Message #{detail.id} — {detail.source_name}
            </h2>
            <div className="detail-row">
              <span className="k">Telegram message ID</span>
              <span className="mono">{detail.telegram_message_id}</span>
            </div>
            <div className="detail-row">
              <span className="k">Sent</span>
              <span className="mono">{detail.sent_at ? new Date(detail.sent_at).toLocaleString() : "—"}</span>
            </div>
            <div className="detail-row">
              <span className="k">Ingested</span>
              <span className="mono">{detail.ingested_at ? new Date(detail.ingested_at).toLocaleString() : "—"}</span>
            </div>
            <div className="detail-row">
              <span className="k">Edited</span>
              <span className="mono">{detail.edited_at ? new Date(detail.edited_at).toLocaleString() : "—"}</span>
            </div>
            <div className="detail-row">
              <span className="k">State</span>
              <span>{detail.state}</span>
            </div>
            <div className="detail-row">
              <span className="k">Reply to</span>
              <span className="mono">{detail.reply_to_msg_id ?? "—"}</span>
            </div>
            <div className="detail-row">
              <span className="k">Forward from</span>
              <span>{detail.forward_from_name ?? "—"}</span>
            </div>
            <div className="detail-row">
              <span className="k">Media</span>
              <span>{detail.media_type ?? "none (metadata only)"}</span>
            </div>
            {detail.permalink && (
              <div className="detail-row">
                <span className="k">Telegram permalink</span>
                <a href={detail.permalink} target="_blank" rel="noreferrer">open in Telegram</a>
              </div>
            )}

            <h3 style={{ marginTop: 16 }}>Original text</h3>
            <div className="card" style={{ background: "var(--bg)", whiteSpace: "pre-wrap" }}>
              {detail.text_preview}
            </div>
            {detail.normalized_text && (
              <>
                <h3>Normalized text</h3>
                <div className="card mono" style={{ background: "var(--bg)", whiteSpace: "pre-wrap" }}>
                  {detail.normalized_text}
                </div>
              </>
            )}

            <h3>Extracted indicators</h3>
            {detail.indicators.length === 0 && <div className="muted">None</div>}
            <table>
              <tbody>
                {detail.indicators.map((ind, i) => (
                  <tr key={i}>
                    <td><span className="badge blue">{ind.type}</span></td>
                    <td className="mono">{ind.value}</td>
                    <td className="mono muted">{ind.normalized_value}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <h3>Rule matches</h3>
            {detail.rule_matches.length === 0 && <div className="muted">None</div>}
            <div className="pill-row">
              {detail.rule_matches.map((rm, i) => (
                <span key={i} className="badge purple">rule #{rm.rule_id} v{rm.rule_version}</span>
              ))}
            </div>

            <h3>Associated alerts</h3>
            {detail.alerts.length === 0 && <div className="muted">None</div>}
            <div className="pill-row">
              {detail.alerts.map((a) => (
                <span key={a.id} className={`badge severity-${a.severity}`}>alert #{a.id} · {a.state}</span>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
