import React, { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api";
import type { Rule, RuleCondition, RuleDefinition } from "../types";

const SEVERITIES = ["informational", "low", "medium", "high", "critical"];
const CONDITION_TYPES = ["keyword", "phrase", "regex", "indicator", "source"];

const emptyDefinition = (): RuleDefinition => ({
  match: "any",
  conditions: [{ type: "keyword", value: "" }],
});

export default function Rules() {
  const [rules, setRules] = useState<Rule[]>([]);
  const [sources, setSources] = useState<{ id: number; title: string }[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Rule | null>(null);
  const [isNew, setIsNew] = useState(false);
  const [testResult, setTestResult] = useState<{
    matched: boolean;
    warning?: string | null;
    conditions: unknown[];
    excerpt: string;
  } | null>(null);
  const [sampleText, setSampleText] = useState("");

  const load = useCallback(async () => {
    try {
      const [r, s] = await Promise.all([api.rules(), api.sources()]);
      setRules(r.items);
      setSources(s.items.map((x) => ({ id: x.id, title: x.title })));
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const openNew = () => {
    setEditing({
      id: 0,
      name: "",
      description: "",
      enabled: true,
      severity: "high",
      definition: emptyDefinition(),
      source_scope: null,
      dedup_window_seconds: 3600,
      version: 1,
    });
    setIsNew(true);
    setTestResult(null);
  };

  const save = async () => {
    if (!editing) return;
    setError(null);
    try {
      const body = {
        name: editing.name,
        description: editing.description,
        severity: editing.severity,
        definition: editing.definition,
        source_scope: editing.source_scope,
        dedup_window_seconds: editing.dedup_window_seconds,
        enabled: editing.enabled,
      };
      if (isNew) await api.createRule(body);
      else await api.patchRule(editing.id, body);
      setEditing(null);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
    }
  };

  const toggle = async (r: Rule) => {
    try {
      await api.patchRule(r.id, { enabled: !r.enabled });
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
    }
  };

  const remove = async (r: Rule) => {
    if (!window.confirm(`Delete rule "${r.name}"? Existing alerts are preserved.`)) return;
    try {
      await api.deleteRule(r.id);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
    }
  };

  const testRule = async () => {
    if (!editing || !sampleText) return;
    setError(null);
    try {
      const res = await api.testRule(editing.definition, sampleText);
      setTestResult(res);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
    }
  };

  const setCondition = (i: number, patch: Partial<RuleCondition>) => {
    if (!editing) return;
    const conditions = editing.definition.conditions.map((c, j) => (j === i ? { ...c, ...patch } : c));
    setEditing({ ...editing, definition: { ...editing.definition, conditions } });
  };

  const severityBadge = (s: string) => <span className={`badge severity-${s}`}>{s}</span>;

  return (
    <div>
      <h1>Rules</h1>
      <p className="page-sub">Deterministic keyword, phrase, regex, and indicator monitors</p>
      {error && <div className="error-box">{error}</div>}

      <div className="card">
        <div className="card-title">
          <span>Rule list</span>
          <button className="btn btn-sm" onClick={openNew}>
            New rule
          </button>
        </div>
        {rules.length === 0 && <div className="empty">No rules yet</div>}
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Severity</th>
              <th>State</th>
              <th>Scope</th>
              <th>Matches</th>
              <th>Last match</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rules.map((r) => (
              <tr key={r.id}>
                <td>
                  <strong>{r.name}</strong>
                  {r.description && <div className="muted">{r.description}</div>}
                </td>
                <td>{severityBadge(r.severity)}</td>
                <td>{r.enabled ? <span className="badge green">enabled</span> : <span className="badge">disabled</span>}</td>
                <td className="mono">
                  {r.source_scope?.length ? `${r.source_scope.length} source(s)` : "all sources"}
                </td>
                <td>{r.recent_match_count ?? 0}</td>
                <td className="mono">{r.last_match_at ? new Date(r.last_match_at).toLocaleString() : "—"}</td>
                <td className="btn-row">
                  <button className="btn btn-sm btn-ghost" onClick={() => { setEditing({ ...r }); setIsNew(false); setTestResult(null); }}>
                    Edit
                  </button>
                  <button className="btn btn-sm btn-ghost" onClick={() => void toggle(r)}>
                    {r.enabled ? "Disable" : "Enable"}
                  </button>
                  <button className="btn btn-sm btn-danger" onClick={() => void remove(r)}>
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {editing && (
        <div className="modal-backdrop" onClick={() => setEditing(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>{isNew ? "New rule" : `Edit rule v${editing.version}`}</h2>
            <div className="form-row">
              <div>
                <label>Name</label>
                <input value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })} />
              </div>
              <div>
                <label>Severity</label>
                <select value={editing.severity} onChange={(e) => setEditing({ ...editing, severity: e.target.value })}>
                  {SEVERITIES.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </div>
            </div>
            <label>Description</label>
            <input value={editing.description ?? ""} onChange={(e) => setEditing({ ...editing, description: e.target.value })} />
            <label>Deduplication window (seconds)</label>
            <input
              type="number"
              value={editing.dedup_window_seconds}
              onChange={(e) => setEditing({ ...editing, dedup_window_seconds: Number(e.target.value) })}
            />
            <label>Source scope (optional)</label>
            <select
              multiple
              value={editing.source_scope?.map(String) ?? []}
              onChange={(e) =>
                setEditing({
                  ...editing,
                  source_scope: Array.from(e.target.selectedOptions).map((o) => Number(o.value)),
                })
              }
            >
              {sources.map((s) => (
                <option key={s.id} value={s.id}>{s.title}</option>
              ))}
            </select>
            <div className="muted" style={{ fontSize: 12 }}>
              Leave empty to match all monitored sources.
            </div>

            <label>Match logic</label>
            <div className="seg">
              <button className={editing.definition.match === "any" ? "active" : ""} onClick={() => setEditing({ ...editing, definition: { ...editing.definition, match: "any" } })}>
                ANY
              </button>
              <button className={editing.definition.match === "all" ? "active" : ""} onClick={() => setEditing({ ...editing, definition: { ...editing.definition, match: "all" } })}>
                ALL
              </button>
            </div>

            <label>Conditions</label>
            {editing.definition.conditions.map((c, i) => (
              <div className="form-row" key={i} style={{ marginBottom: 8 }}>
                <select value={c.type} onChange={(e) => setCondition(i, { type: e.target.value as RuleCondition["type"], value: "" })}>
                  {CONDITION_TYPES.map((t) => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </select>
                <input
                  placeholder={
                    c.type === "regex"
                      ? "regular expression"
                      : c.type === "indicator"
                      ? "indicator type: url|domain|ipv4|ipv6|email|hash|crypto|telegram_username"
                      : c.type === "source"
                      ? "source id"
                      : "value"
                  }
                  value={c.value}
                  onChange={(e) => setCondition(i, { value: e.target.value })}
                />
                <button
                  className="btn btn-sm btn-ghost"
                  disabled={editing.definition.conditions.length <= 1}
                  onClick={() =>
                    setEditing({
                      ...editing,
                      definition: { ...editing.definition, conditions: editing.definition.conditions.filter((_, j) => j !== i) },
                    })
                  }
                >
                  Remove
                </button>
              </div>
            ))}
            <button
              className="btn btn-sm btn-ghost"
              onClick={() =>
                setEditing({
                  ...editing,
                  definition: { ...editing.definition, conditions: [...editing.definition.conditions, { type: "keyword", value: "" }] },
                })
              }
            >
              + Add condition
            </button>

            {testResult && (
              <div className={testResult.matched ? "ok-box" : "warn-box"} style={{ marginTop: 12 }}>
                <strong>{testResult.matched ? "Matched" : "No match"}</strong>
                {testResult.warning && <div>{testResult.warning}</div>}
                <div className="muted">{testResult.excerpt}</div>
              </div>
            )}

            <label>Test against sample message</label>
            <textarea rows={3} value={sampleText} onChange={(e) => setSampleText(e.target.value)} placeholder="Paste a sample message to test the rule before enabling…" />
            <div className="btn-row" style={{ marginTop: 8 }}>
              <button className="btn btn-sm btn-ghost" onClick={() => void testRule()} disabled={!sampleText}>
                Test rule
              </button>
            </div>

            <div className="btn-row" style={{ marginTop: 16 }}>
              <button className="btn" onClick={() => void save()} disabled={!editing.name || editing.definition.conditions.some((c) => !c.value)}>
                {isNew ? "Create rule" : "Save changes"}
              </button>
              <button className="btn btn-ghost" onClick={() => setEditing(null)}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
