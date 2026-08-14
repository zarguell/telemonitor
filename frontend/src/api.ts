import type {
  Alert,
  AuditEvent,
  DiscoveredSource,
  Health,
  Overview,
  Rule,
  RuleDefinition,
  SearchResult,
  Source,
  TgStatus,
  User,
} from "./types";

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

/** Fired when any API call returns 401 so the app can return to Login. */
export const UNAUTHORIZED_EVENT = "tm:unauthorized";

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api/v1${path}`, {
    method,
    credentials: "include",
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  let data: Record<string, unknown> | null = null;
  try {
    data = (await res.json()) as Record<string, unknown>;
  } catch {
    data = null;
  }
  if (res.status === 401) {
    const detail = typeof data?.detail === "string" ? data.detail : "Not authenticated";
    // Session expiry mid-use: return the whole UI to the login screen.
    if (!path.startsWith("/auth/login")) {
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    }
    throw new ApiError(401, detail);
  }
  if (!res.ok) {
    const detail =
      typeof data?.detail === "string"
        ? data.detail
        : JSON.stringify(data?.detail ?? data ?? {});
    throw new ApiError(res.status, detail);
  }
  return data as T;
}

export const api = {
  me: () => request<{ user: User }>("GET", "/auth/me"),
  login: (username: string, password: string) =>
    request<{ user: User }>("POST", "/auth/login", { username, password }),
  logout: () => request<{ ok: boolean }>("POST", "/auth/logout"),
  changePassword: (current_password: string, new_password: string) =>
    request<{ ok: boolean }>("POST", "/auth/password", { current_password, new_password }),

  health: () => request<Health>("GET", "/health"),
  overview: () => request<Overview>("GET", "/overview"),

  tgStatus: () => request<TgStatus>("GET", "/telegram/status"),
  tgInitialize: (api_id: string, api_hash: string, acknowledgement: boolean) =>
    request<TgStatus>("POST", "/telegram/initialize", { api_id, api_hash, acknowledgement }),
  tgPhone: (phone: string) => request<TgStatus>("POST", "/telegram/phone", { phone }),
  tgCode: (code: string) => request<TgStatus>("POST", "/telegram/code", { code }),
  tgPassword: (password: string) => request<TgStatus>("POST", "/telegram/password", { password }),
  tgDisconnect: (confirm: boolean) => request<TgStatus>("POST", "/telegram/disconnect", { confirm }),
  tgTest: () => request<{ ok: boolean; state: string }>("POST", "/telegram/test"),

  discovered: () => request<DiscoveredSource[]>("GET", "/sources/discovered"),
  sources: () => request<{ items: Source[]; total: number }>("GET", "/sources"),
  createSource: (body: Record<string, unknown>) => request<Source>("POST", "/sources", body),
  patchSource: (id: number, body: Record<string, unknown>) => request<Source>("PATCH", `/sources/${id}`, body),
  deleteSource: (id: number) => request<{ ok: boolean }>("DELETE", `/sources/${id}`),

  rules: () => request<{ items: Rule[]; total: number }>("GET", "/rules"),
  createRule: (body: Record<string, unknown>) => request<Rule>("POST", "/rules", body),
  patchRule: (id: number, body: Record<string, unknown>) => request<Rule>("PATCH", `/rules/${id}`, body),
  deleteRule: (id: number) => request<{ ok: boolean }>("DELETE", `/rules/${id}`),
  testRule: (definition: RuleDefinition, sample_text: string, source_id?: number) =>
    request<{ matched: boolean; warning?: string | null; conditions: unknown[]; excerpt: string; indicators: unknown[] }>(
      "POST",
      "/rules/test",
      { definition, sample_text, source_id }
    ),

  search: (params: Record<string, string | number | undefined>) => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
    }
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return request<{ total: number; limit: number; offset: number; items: SearchResult[] }>("GET", `/search${suffix}`);
  },

  alerts: (params: Record<string, string | number | undefined>) => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
    }
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return request<{ items: Alert[]; total: number }>("GET", `/alerts${suffix}`);
  },
  alert: (id: number) => request<Alert>("GET", `/alerts/${id}`),
  triageAlert: (id: number, state: string, note?: string) =>
    request<Alert>("PATCH", `/alerts/${id}`, { state, note }),

  settings: () =>
    request<{
      retention_days: number;
      alert_destination: Record<string, unknown>;
      aliases: { alias: string; canonical?: string }[];
      media_settings?: { store_media: boolean };
    }>("GET", "/settings"),
  updateSettings: (body: Record<string, unknown>) => request("PUT", "/settings", body),
  testDestination: () => request<{ ok: boolean; status_code?: number | null; error?: string | null }>(
    "POST",
    "/settings/destination/test"
  ),

  users: () => request<{ items: User[]; total: number }>("GET", "/users"),
  createUser: (body: Record<string, unknown>) => request<User>("POST", "/users", body),
  patchUser: (id: number, body: Record<string, unknown>) => request<User>("PATCH", `/users/${id}`, body),

  audit: (params: Record<string, string | number | undefined>) => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
    }
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return request<{ items: AuditEvent[]; total: number }>("GET", `/audit${suffix}`);
  },
};
