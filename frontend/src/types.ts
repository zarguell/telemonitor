export interface User {
  id: number;
  username: string;
  role: "admin" | "operator" | "analyst";
  display_name?: string;
  email?: string;
  is_active: boolean;
}

export interface TgStatus {
  state: string;
  detail?: string | null;
  error?: string | null;
  connected_account?: string | null;
  last_update?: string | null;
  collector_heartbeat?: string | null;
  simulated?: boolean;
  encryption_key_fingerprint?: string | null;
}

export interface DiscoveredSource {
  chat_id: number;
  title: string;
  username?: string | null;
  type: string;
  last_activity_at?: string | null;
  allowlisted: boolean;
  monitored_id?: number | null;
  enabled?: boolean;
  label?: string | null;
}

export interface Source {
  id: number;
  telegram_chat_id: number;
  title: string;
  username?: string | null;
  type: string;
  enabled: boolean;
  label?: string | null;
  status: string;
  backfill_mode: string;
  backfill_start?: string | null;
  backfill_checkpoint?: number | null;
  backfill_total?: number | null;
  backfill_done?: number;
  backfill_progress?: number | null;
  backfill_error?: string | null;
  last_message_at?: string | null;
  last_success_at?: string | null;
  last_error?: string | null;
  allowlisted_at?: string | null;
}

export interface Rule {
  id: number;
  name: string;
  description?: string | null;
  enabled: boolean;
  severity: string;
  definition: RuleDefinition;
  source_scope?: number[] | null;
  dedup_window_seconds: number;
  version: number;
  recent_match_count?: number;
  last_match_at?: string | null;
  updated_at?: string | null;
}

export interface RuleCondition {
  type: "keyword" | "phrase" | "regex" | "indicator" | "source";
  value: string;
  match?: string;
}

export interface RuleDefinition {
  match: "all" | "any";
  conditions: RuleCondition[];
}

export interface Indicator {
  type: string;
  value: string;
  normalized_value: string;
  confidence?: number | null;
}

export interface SearchResult {
  id: number;
  source_id: number;
  source_name: string;
  source_username?: string | null;
  telegram_message_id: number;
  sent_at?: string | null;
  ingested_at?: string | null;
  edited_at?: string | null;
  state: string;
  snippet: string;
  text_preview: string;
  normalized_text?: string;
  indicators: Indicator[];
  rule_matches: { rule_id: number; rule_version: number }[];
  alerts: { id: number; state: string; severity: string }[];
  permalink?: string | null;
  reply_to_msg_id?: number | null;
  forward_from_name?: string | null;
  sender_id?: number | null;
  media_type?: string | null;
}

export interface Alert {
  id: number;
  rule_id?: number | null;
  rule_name?: string | null;
  rule_version?: number | null;
  source_id?: number | null;
  source_title?: string | null;
  severity: string;
  state: string;
  excerpt?: string | null;
  message_count: number;
  first_seen_at?: string | null;
  last_seen_at?: string | null;
  delivery_state: string;
  delivery_attempts?: number;
  last_delivery_error?: string | null;
  dedupe_window_seconds?: number;
  triage_note?: string | null;
  triaged_by?: string | null;
  triaged_at?: string | null;
  created_at?: string | null;
  messages?: {
    id: number;
    telegram_message_id: number;
    sent_at?: string | null;
    text_preview: string;
    permalink?: string | null;
    state?: string;
    indicators: Indicator[];
  }[];
  deliveries?: {
    attempt: number;
    status: string;
    status_code?: number | null;
    error?: string | null;
    attempted_at?: string | null;
    destination_type: string;
    destination_ref?: string | null;
  }[];
}

export interface AuditEvent {
  id: number;
  actor_username?: string | null;
  action: string;
  object_type?: string | null;
  object_id?: string | null;
  detail?: Record<string, unknown> | null;
  ip_address?: string | null;
  created_at?: string | null;
}

export interface Overview {
  telegram: { state: string; detail?: string | null; collector_heartbeat?: string | null };
  enabled_sources: number;
  backfill_in_progress: number;
  messages_24h: number;
  processed_messages_24h?: number;
  failed_messages_24h: number;
  alerts_created_24h?: number;
  alerts_delivered_24h?: number;
  open_alerts: Record<string, number>;
  open_alert_total: number;
  recent_errors: { kind: string; source?: string; alert_id?: number; error?: string }[];
  queues: Record<string, { depth: number; failed: number }>;
}

export interface Health {
  status: string;
  database: { ok: boolean };
  collector: {
    state: string;
    detail?: string | null;
    heartbeat?: string | null;
    worker: string;
    connected: boolean;
  };
  workers: Record<string, { kind: string; status: string; queues?: string | null; last_beat_at?: string | null }>;
  queues: Record<string, { depth: number; oldest_todo?: string | null; failed: number; last_success?: string | null }>;
}
