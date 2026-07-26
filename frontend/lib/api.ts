/**
 * API client + SWR fetchers + AI streaming helpers.
 *
 * All requests proxy through /api/v1/* which Next.js rewrites to the
 * FastAPI backend (see next.config.mjs).
 */

import type { SWRConfiguration } from "swr";

export const API_PREFIX = "/api/v1";

/**
 * Direct backend URL for streaming endpoints (SSE).
 *
 * Why: Next.js `rewrites()` proxies buffer the entire response before
 * forwarding — fine for JSON, fatal for SSE. The chat stream would arrive
 * at the browser as a single buffered chunk, defeating token-by-token
 * streaming and making the typewriter cursor look fake.
 *
 * For SSE endpoints only, we bypass the proxy and hit the backend origin
 * directly. Falls back to the proxy path when no backend URL is configured
 * (e.g. in production behind a proper streaming-aware reverse proxy).
 */
export const STREAM_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || "";

export class ApiError extends Error {
  constructor(public status: number, message: string, public details?: unknown) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(
  path: string,
  init?: RequestInit & { skipJson?: boolean }
): Promise<T> {
  const res = await fetch(`${API_PREFIX}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    let details: unknown;
    try {
      details = await res.json();
    } catch {
      details = undefined;
    }
    throw new ApiError(res.status, `API ${res.status} on ${path}`, details);
  }
  if (init?.skipJson) return undefined as T;
  return res.json() as Promise<T>;
}

// ---------- Domain fetchers ----------

export const api = {
  // Users
  listUsers: () => request<unknown[]>(`/users`),
  getUser: (id: string) => request<unknown>(`/users/${id}`),
  createUser: (body: unknown) =>
    request<unknown>(`/users`, { method: "POST", body: JSON.stringify(body) }),
  updateUser: (id: string, body: UserProfileUpdate) =>
    request<UserProfileRead>(`/users/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  // Memories (unbounded "remember this" channel)
  listMemories: (category?: string) =>
    request<UserMemoryRead[]>(
      `/memories${category ? `?category=${encodeURIComponent(category)}` : ""}`
    ),
  createMemory: (body: UserMemoryCreate) =>
    request<UserMemoryRead>(`/memories`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateMemory: (id: string, body: UserMemoryUpdate) =>
    request<UserMemoryRead>(`/memories/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteMemory: (id: string) =>
    request<void>(`/memories/${id}`, { method: "DELETE", skipJson: true }),

  // Goals
  listGoals: () => request<unknown[]>(`/goals`),
  getGoal: (id: string) => request<unknown>(`/goals/${id}`),
  createGoal: (body: unknown) =>
    request<unknown>(`/goals`, { method: "POST", body: JSON.stringify(body) }),
  updateGoal: (id: string, body: GoalUpdate) =>
    request<unknown>(`/goals/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteGoal: (id: string) =>
    request<void>(`/goals/${id}`, { method: "DELETE", skipJson: true }),
  listPathways: (goalId: string) =>
    request<unknown[]>(`/goals/${goalId}/pathways`),
  listRequirements: (pathwayId: string) =>
    request<unknown[]>(`/goals/pathways/${pathwayId}/requirements`),

  // Risk factors
  listRiskFactors: () => request<unknown[]>(`/risk-factors`),

  // Events
  listEvents: (riskLevel?: string) =>
    request<unknown[]>(`/events${riskLevel ? `?risk_level=${riskLevel}` : ""}`),

  // Sources
  listSources: () => request<unknown[]>(`/sources`),
  credibility: () =>
    request<{
      high: number; medium: number; low: number; pending: number;
      user_marked_reliable: number; user_marked_questionable: number;
      total: number; private_share: number;
    }>(`/sources/credibility`),
  markCredibility: (id: string, credibility: string) =>
    request<unknown>(`/sources/${id}/credibility?credibility=${credibility}`, {
      method: "PATCH",
    }),

  // Scenarios
  listScenarios: (goalId: string) =>
    request<unknown[]>(`/scenarios?goal_id=${goalId}`),
  createScenario: (payload: {
    goal_id: string;
    name: string;
    description?: string;
    assumptions?: Record<string, unknown>;
  }) =>
    request<unknown>(`/scenarios`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  branchScenario: (parentId: string, name: string, assumptions: Record<string, unknown>) =>
    request<unknown>(
      `/scenarios/${parentId}/branch?name=${encodeURIComponent(name)}&impact_threshold=0.05`,
      {
        method: "POST",
        body: JSON.stringify(assumptions),
      }
    ),
  runScenario: (id: string) =>
    request<unknown>(`/scenarios/${id}/run`, { method: "POST" }),

  // Graph
  getGraph: (goalId: string, scenarioId?: string) =>
    request<{ nodes: unknown[]; edges: unknown[] }>(
      `/graph/${goalId}${scenarioId ? `?scenario_id=${scenarioId}` : ""}`
    ),

  // Dashboard
  getDashboard: (goalId: string) =>
    request<DashboardSummary>(`/dashboard/${goalId}`),

  // Notifications
  listNotifications: (params?: {
    severity?: NotificationSeverity | string;
    status?: NotificationStatus | string;
    channel?: NotificationChannel | string;
    limit?: number;
    offset?: number;
  }) => {
    const q = new URLSearchParams();
    if (params?.severity) q.set("severity", params.severity);
    if (params?.status) q.set("status", params.status);
    if (params?.channel) q.set("channel", params.channel);
    if (params?.limit != null) q.set("limit", String(params.limit));
    if (params?.offset != null) q.set("offset", String(params.offset));
    const qs = q.toString();
    return request<NotificationRead[]>(
      `/notifications${qs ? `?${qs}` : ""}`
    );
  },
  markRead: (id: string) =>
    request<NotificationRead>(`/notifications/${id}/read`, {
      method: "POST",
    }),
  bulkMarkRead: (notificationIds: string[]) =>
    request<{ updated: number }>(`/notifications/bulk-read`, {
      method: "POST",
      body: JSON.stringify({ notification_ids: notificationIds }),
    }),
  getUnreadCount: () =>
    request<{ count: number }>(`/notifications/unread-count`),

  // Ingest
  ingestText: (body: unknown) =>
    request<unknown>(`/ingest/text`, { method: "POST", body: JSON.stringify(body) }),
  ingestUpload: (file: File, fields: Record<string, string>) => {
    const fd = new FormData();
    fd.append("file", file);
    for (const [k, v] of Object.entries(fields)) {
      if (v !== undefined && v !== null) fd.append(k, v);
    }
    return fetch(`${API_PREFIX}/ingest/upload`, { method: "POST", body: fd }).then(
      async (r) => {
        if (!r.ok) {
          let details: unknown;
          try { details = await r.json(); } catch { details = undefined; }
          throw new ApiError(r.status, `Upload failed (${r.status})`, details);
        }
        return r.json();
      }
    );
  },

  // Plugins
  listPlugins: () => request<PluginManifest[]>(`/plugins`),
  getPlugin: (id: string) => request<PluginManifest>(`/plugins/${id}`),
  runPlugin: (id: string, body: { params: Record<string, unknown>; title?: string; skip_llm?: boolean }) =>
    request<PluginRunResult>(`/plugins/${id}/run`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // Crawler (Tavily search / extract / crawl)
  crawlerSearch: (q: string, opts?: { max_results?: number; topic?: string; region?: string; days?: number }) =>
    request<unknown[]>(
      `/crawler/search?q=${encodeURIComponent(q)}${opts?.max_results ? `&max_results=${opts.max_results}` : ""}${opts?.topic ? `&topic=${opts.topic}` : ""}${opts?.region ? `&region=${encodeURIComponent(opts.region)}` : ""}${opts?.days != null ? `&days=${opts.days}` : ""}`
    ),
  crawlerExtract: (body: {
    urls: string | string[];
    query?: string;
    extract_depth?: "basic" | "advanced";
    chunks_per_source?: number;
    include_images?: boolean;
    format?: "markdown" | "text";
    timeout?: number;
  }) => request<unknown[]>(`/crawler/extract`, { method: "POST", body: JSON.stringify(body) }),
  crawlerCrawl: (body: {
    url: string;
    instructions?: string;
    max_depth?: number;
    max_breadth?: number;
    limit?: number;
    extract_depth?: "basic" | "advanced";
    format?: "markdown" | "text";
    select_paths?: string[];
    exclude_paths?: string[];
    timeout?: number;
  }) => request<unknown[]>(`/crawler/crawl`, { method: "POST", body: JSON.stringify(body) }),

  // Settings — multi-provider / multi-model
  getSettings: () => request<LLMConfigView>(`/settings`),

  // System components — read-only docker service status
  getSystemComponents: () =>
    request<SystemComponentsView>(`/system/components`),

  addProvider: (body: ProviderCreate) =>
    request<LLMConfigView>(`/settings/providers`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateProvider: (id: string, body: ProviderUpdate) =>
    request<LLMConfigView>(`/settings/providers/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteProvider: (id: string) =>
    request<LLMConfigView>(`/settings/providers/${id}`, {
      method: "DELETE",
    }),

  addModel: (body: ModelCreate) =>
    request<LLMConfigView>(`/settings/models`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateModel: (id: string, body: ModelUpdate) =>
    request<LLMConfigView>(`/settings/models/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteModel: (id: string) =>
    request<LLMConfigView>(`/settings/models/${id}`, {
      method: "DELETE",
    }),

  setRoles: (assignments: Partial<Record<Role, string | null>>) =>
    request<LLMConfigView>(`/settings/roles`, {
      method: "PUT",
      body: JSON.stringify({ assignments }),
    }),
  setTavily: (apiKey: string) =>
    request<LLMConfigView>(`/settings/tavily`, {
      method: "PUT",
      body: JSON.stringify({ api_key: apiKey }),
    }),
  setMineru: (apiKey: string, baseUrl?: string) =>
    request<LLMConfigView>(`/settings/mineru`, {
      method: "PUT",
      body: JSON.stringify({ api_key: apiKey, base_url: baseUrl ?? null }),
    }),
  setSmtp: (body: SmtpUpdate) =>
    request<LLMConfigView>(`/settings/smtp`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  testRole: (role: Role) =>
    request<TestResult>(`/settings/test/${role}`, { method: "POST" }),

  // Secret reveal — fetch the FULL (unmasked) API key for display in the UI.
  // Used by the eye-toggle button on provider/tavily/mineru/smtp cards.
  getProviderKey: (id: string) =>
    request<{ value: string | null; configured: boolean }>(
      `/settings/providers/${id}/key`
    ),
  getTavilyKey: () =>
    request<{ value: string | null; configured: boolean }>(`/settings/tavily/key`),
  getMineruKey: () =>
    request<{ value: string | null; configured: boolean }>(`/settings/mineru/key`),
  getSmtpKey: () =>
    request<{ value: string | null; configured: boolean }>(`/settings/smtp/key`),

  // SMTP test email
  testSmtp: (toAddr: string) =>
    request<{ ok: boolean; error?: string }>(`/settings/smtp/test`, {
      method: "POST",
      body: JSON.stringify({ to_addr: toAddr }),
    }),

  // Delete a source row
  deleteSource: (id: string) =>
    request<void>(`/sources/${id}`, { method: "DELETE" }),

  // Meta — project about + update check
  get: <T>(path: string) => request<T>(path),
  getAbout: () =>
    request<AboutInfo>(`/meta/about`),
  checkUpdate: () =>
    request<UpdateCheck>(`/meta/check-update`),

  // Lifecycle — information half-life / decay management (§4.8)
  getDecayDistribution: () =>
    request<DecayDistribution>(`/lifecycle/distribution`),
  listLifecycleEvents: (status?: DecayStatus) =>
    request<LifecycleEvent[]>(
      `/lifecycle/events${status ? `?status=${status}` : ""}`
    ),
  refreshLifecycleEvent: (eventId: string) =>
    request<LifecycleEvent>(`/lifecycle/events/${eventId}/refresh`, {
      method: "POST",
    }),
  archiveLifecycleEvent: (eventId: string) =>
    request<LifecycleEvent>(`/lifecycle/events/${eventId}/archive`, {
      method: "POST",
    }),
  updateEventHalfLife: (eventId: string, halfLifeDays: number) =>
    request<LifecycleEvent>(`/lifecycle/events/${eventId}/half-life`, {
      method: "PATCH",
      body: JSON.stringify({ half_life_days: halfLifeDays }),
    }),
  sweepExpiredEvents: () =>
    request<{ status: string; archived: number }>(`/lifecycle/sweep`, {
      method: "POST",
    }),
};

// ---------- Lifecycle (information half-life) types ----------

export type DecayStatus = "fresh" | "stale" | "expired" | "archived";

export interface DecayScore {
  event_id: string;
  score: number;
  age_days: number;
  half_life_days: number;
  status: DecayStatus | string;
  last_refreshed_at: string | null;
}

export interface DecayDistribution {
  total: number;
  fresh: number;
  stale: number;
  expired: number;
  archived: number;
  avg_score: number;
}

export interface LifecycleEvent {
  event: EventRead;
  decay: DecayScore;
}

// ---------- Settings types ----------

export type Protocol = "openai_compatible" | "anthropic" | "bailian";
export type Role = "chat" | "vision" | "embedding" | "rerank";
export const ALL_ROLES: Role[] = ["chat", "vision", "embedding", "rerank"];

// ---------- User profile types ----------

export type RiskTolerance = "low" | "medium" | "high";

// ---------- Goal types ----------

export type GoalStatus =
  | "draft"
  | "active"
  | "paused"
  | "achieved"
  | "abandoned";

export const ALL_GOAL_STATUSES: GoalStatus[] = [
  "draft",
  "active",
  "paused",
  "achieved",
  "abandoned",
];

export interface GoalUpdate {
  title?: string;
  description?: string | null;
  scenario?: string;
  target_date?: string | null;
  status?: GoalStatus;
  meta?: Record<string, unknown> | null;
}

export interface UserProfileRead {
  id: string;
  display_name: string;
  email: string | null;
  avatar_url: string | null;
  demographics: Record<string, unknown>;
  priority_factors: Record<string, unknown>;
  risk_tolerance: RiskTolerance;
  notify_channels: Record<string, boolean>;
  quiet_hours: Record<string, unknown>;
  primary_goal_id: string | null;
  preferred_pathway_id: string | null;
  progress: Record<string, unknown>;
  implicit_tags: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface UserProfileUpdate {
  display_name?: string;
  email?: string | null;
  avatar_url?: string | null;
  demographics?: Record<string, unknown> | null;
  priority_factors?: Record<string, unknown> | null;
  risk_tolerance?: RiskTolerance;
  notify_channels?: Record<string, boolean> | null;
  quiet_hours?: Record<string, unknown> | null;
  primary_goal_id?: string | null;
  preferred_pathway_id?: string | null;
}

// ---------- User memory types ----------

export type MemoryCategory =
  | "family"
  | "career"
  | "health"
  | "finance"
  | "education"
  | "location"
  | "preference"
  | "goal"
  | "constraint"
  | "other";

export interface UserMemoryRead {
  id: string;
  user_id: string;
  content: string;
  category: string;
  importance: number;
  source: "chat" | "manual" | "upload" | "plugin";
  meta: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface UserMemoryCreate {
  content: string;
  category?: string;
  importance?: number;
  source?: "chat" | "manual" | "upload" | "plugin";
  meta?: Record<string, unknown>;
}

export interface UserMemoryUpdate {
  content?: string;
  category?: string;
  importance?: number;
  meta?: Record<string, unknown>;
}

// ---------- Notification types ----------

export type NotificationSeverity = "info" | "warning" | "critical";
export type NotificationChannel = "in_app" | "email" | "sms" | "push";
export type NotificationStatus =
  | "pending"
  | "sent"
  | "failed"
  | "suppressed"
  | "read";

export interface NotificationRead {
  id: string;
  user_id: string;
  channel: NotificationChannel | string;
  status: NotificationStatus | string;
  severity: NotificationSeverity | string;
  title: string;
  body: string;
  event_id: string | null;
  risk_factor_id: string | null;
  impact_summary: Record<string, unknown>;
  sent_at: string | null;
  read_at: string | null;
  created_at: string;
}

// ---------- Dashboard types ----------

export interface SuccessProbability {
  p10?: number;
  p50?: number;
  p90?: number;
  bayesian_point?: number;
  p_by_target_date?: number;
  overall_risk?: number;
  factor_scores?: unknown[];
  computed_at?: string | null;
}

export interface Milestone {
  label?: string;
  date?: string;
  pathway?: string;
  status?: string;
  [k: string]: unknown;
}

export interface RiskHeatmapCell {
  type: string;
  level: string;
  count: number;
}

export interface CredibilityDistribution {
  high: number;
  medium: number;
  low: number;
  pending: number;
  user_marked_reliable: number;
  user_marked_questionable: number;
  total: number;
  private_share: number;
}

export interface DashboardSummary {
  goal_id: string;
  goal_title?: string;
  goal_scenario?: string;
  goal_target_date?: string | null;
  goal_status?: string;
  success_probability: SuccessProbability;
  milestones: Milestone[];
  recent_events: EventRead[];
  risk_heatmap: RiskHeatmapCell[];
  credibility: CredibilityDistribution;
  active_scenarios: number;
  consecutive_planning_days: number;
  // §5 透明化 + 收敛建议 — drill-down from the latest reasoning run
  regret_free_actions?: RegretFreeAction[];
  factor_contributions?: FactorContribution[];
  reasoning_explanation?: string | null;
  median_time_months?: number | null;
  survival_curve?: SurvivalPoint[];
  key_risk_times?: KeyRiskTime[];
  reasoning_run_id?: string | null;
  reasoning_iterations?: number | null;
}

export interface RegretFreeAction {
  requirement_id?: string;
  risk_factor_id?: string;
  name: string;
  action: string;
}

export interface FactorContribution {
  factor_id?: string;
  name: string;
  type: "requirement" | "risk_factor" | string;
  p: number; // success probability for this factor
  contribution: number; // contribution to failure
}

export interface SurvivalPoint {
  month?: number;
  t?: number;
  p?: number;
  cumulative_hazard?: number;
  [k: string]: unknown;
}

export interface KeyRiskTime {
  month?: number;
  risk?: number;
  label?: string;
  [k: string]: unknown;
}

export interface EventRead {
  id: string;
  subject?: string | null;
  action?: string | null;
  object?: string | null;
  occurred_at?: string | null;
  created_at?: string;
  updated_at?: string;
  risk_flag_level?: string | null;
  risk_flag_type?: string | null;
  old_value?: unknown;
  new_value?: unknown;
  half_life_days?: number | null;
  [k: string]: unknown;
}

export interface ProviderView {
  id: string;
  name: string;
  protocol: Protocol;
  base_url: string | null;
  api_key_configured: boolean;
  api_key_preview: string;
  created_at: string;
}

export interface ModelView {
  id: string;
  provider_id: string;
  name: string;
  display_name: string;
  capabilities: Role[];
  created_at: string;
}

export interface LLMConfigView {
  version: number;
  providers: ProviderView[];
  models: ModelView[];
  role_assignments: Partial<Record<Role, string>>;
  tavily_api_key_configured: boolean;
  tavily_api_key_preview: string;
  roles_configured: Record<Role, boolean>;
  mineru_api_key_configured: boolean;
  mineru_api_key_preview: string;
  mineru_base_url: string;
  // SMTP for email notifications (§4.5)
  smtp_host: string;
  smtp_port: number;
  smtp_user: string;
  smtp_password_configured: boolean;
  smtp_password_preview: string;
  smtp_from: string;
  smtp_sender_name: string;
  smtp_use_tls: boolean;
  smtp_use_ssl: boolean;
}

export interface ProviderCreate {
  name: string;
  protocol: Protocol;
  base_url?: string | null;
  api_key?: string;
}

export interface ProviderUpdate {
  name?: string;
  protocol?: Protocol;
  base_url?: string | null;
  api_key?: string | null;
}

export interface ModelCreate {
  provider_id: string;
  name: string;
  display_name?: string;
  capabilities?: Role[];
}

export interface ModelUpdate {
  name?: string;
  display_name?: string;
  capabilities?: Role[];
}

export interface SmtpUpdate {
  host?: string | null;
  port?: number | null;
  user?: string | null;
  password?: string | null;
  from_addr?: string | null;
  sender_name?: string | null;
  use_tls?: boolean | null;
  use_ssl?: boolean | null;
}

export interface TestResult {
  ok: boolean;
  role?: Role | null;
  model?: string | null;
  provider?: string | null;
  error?: string | null;
  available_count?: number | null;
}

// ---------- Plugins ----------

export interface PluginParam {
  name: string;
  label: string;
  type: "string" | "number" | "boolean" | "select";
  required: boolean;
  default: unknown;
  help: string;
  options: { value: string; label: string }[];
}

export interface PluginManifest {
  id: string;
  name: string;
  description: string;
  version: string;
  author: string;
  params: PluginParam[];
  tags: string[];
}

export interface PluginRunResult {
  ok: boolean;
  source_id: string | null;
  events_created: number;
  metrics_created: number;
  assertions_created: number;
  relationships_created: number;
  extraction_confidence: number | null;
  notifications_triggered: number;
  error: string | null;
  warning: string | null;
}

// ---------- System components (docker services) ----------

export type SystemComponentKind = "database" | "graph" | "cache" | "storage";

export interface SystemComponentView {
  key: string;
  name: string;
  kind: SystemComponentKind | string;
  endpoint: string;
  available: boolean;
  enabled: boolean;
  detail: string | null;
  error: string | null;
}

export interface SystemComponentsView {
  components: SystemComponentView[];
}

// ---------- Meta (about / update check) ----------

export interface AboutInfo {
  name: string;
  version: string;
  description: string;
  github_url: string;
  license: string;
}

export interface UpdateCheck {
  has_update: boolean;
  latest_version: string;
  current_version: string;
  release_url: string;
}

// Legacy aliases kept so older imports don't break.
export type LLMSettingsRead = LLMConfigView;
export type LLMSettingsUpdate = ProviderCreate & {
  llm_model?: string;
  llm_embedding_model?: string;
  tavily_api_key?: string;
};
export interface LLMSettingsUpdateResponse {
  ok: boolean;
  message: string;
  restarted_cache: boolean;
  new_state: LLMConfigView;
}

// ---------- SWR defaults ----------

export const swrConfig: SWRConfiguration = {
  revalidateOnFocus: false,
  shouldRetryOnError: false,
  dedupingInterval: 5000,
};

// ---------- AI streaming chat ----------

export interface ChatToolCall {
  name: string;
  args: Record<string, unknown>;
  result: unknown | null;
}

export interface ChatChunk {
  delta: string;
  tool_call?: ChatToolCall | null;
  finish_reason: string | null;
  usage?: Record<string, number>;
}

export async function* streamChat(
  body: {
    goal_id?: string;
    scenario_id?: string;
    messages: { role: string; content: string }[];
  },
  signal?: AbortSignal
): AsyncGenerator<ChatChunk> {
  // Bypass the Next.js rewrite proxy when STREAM_BASE_URL is configured.
  // Why: Next.js `rewrites()` buffers the SSE response in dev mode — the
  // browser receives the entire stream as one giant chunk, defeating
  // token-by-token streaming and making the typewriter cursor look fake.
  // Hitting the backend origin directly preserves true SSE chunking.
  // Falls back to the proxy path when no backend URL is configured (e.g.
  // production behind a streaming-aware reverse proxy).
  const streamUrl = STREAM_BASE_URL
    ? `${STREAM_BASE_URL}${API_PREFIX}/chat/stream`
    : `${API_PREFIX}/chat/stream`;
  const res = await fetch(streamUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...body, stream: true }),
    signal,
  });
  if (!res.ok || !res.body) {
    throw new ApiError(res.status, "Chat stream failed");
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let idx: number;
      while ((idx = buffer.indexOf("\n\n")) !== -1) {
        const evt = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        const dataLine = evt.split("\n").find((l) => l.startsWith("data: "));
        if (!dataLine) continue;
        const payload = dataLine.slice(6);
        if (payload === "[DONE]") return;
        try {
          yield JSON.parse(payload) as ChatChunk;
        } catch {
          // skip malformed lines
        }
      }
    }
  } finally {
    // Ensure the reader is released on early return / abort so the
    // underlying fetch connection is not left dangling.
    try {
      reader.releaseLock();
    } catch {
      // already released
    }
  }
}
