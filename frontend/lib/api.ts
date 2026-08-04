/**
 * API client + SWR fetchers + AI streaming helpers.
 *
 * Browser requests use the Next.js /api/v1 proxy by default. Desktop builds
 * can inject a local sidecar or remote API origin at runtime.
 */

import type { SWRConfiguration } from "swr";
import { apiErrorMessage } from "@/lib/api-error";

export const API_PREFIX = "/api/v1";
export const RUNTIME_API_BASE_URL_KEY = "lifetree.runtime.api_base_url";

declare global {
  interface Window {
    __LIFETREE_RUNTIME__?: { apiBaseUrl?: string; desktopToken?: string };
    __BACKEND_PUBLIC_URL__?: string;
  }
}

function normalizeBaseUrl(value: string | undefined): string {
  return (value || "").trim().replace(/\/+$/, "");
}

/** Resolve the API origin at request time so a desktop sidecar can use a random port. */
export function getApiBaseUrl(): string {
  if (typeof window !== "undefined") {
    const injected = normalizeBaseUrl(window.__LIFETREE_RUNTIME__?.apiBaseUrl);
    if (injected) return injected;
    const stored = normalizeBaseUrl(
      window.localStorage.getItem(RUNTIME_API_BASE_URL_KEY) || undefined
    );
    if (stored) return stored;
  }
  return normalizeBaseUrl(process.env.NEXT_PUBLIC_API_BASE_URL);
}

export function setRuntimeApiBaseUrl(value: string | null): void {
  if (typeof window === "undefined") return;
  if (value) {
    window.localStorage.setItem(RUNTIME_API_BASE_URL_KEY, normalizeBaseUrl(value));
  } else {
    window.localStorage.removeItem(RUNTIME_API_BASE_URL_KEY);
  }
}

export function apiUrl(path: string): string {
  return `${getApiBaseUrl()}${API_PREFIX}${path}`;
}

export function getDesktopHeaders(): Record<string, string> {
  if (typeof window === "undefined") return {};
  const token = window.__LIFETREE_RUNTIME__?.desktopToken;
  return token ? { "X-LifeTree-Desktop-Token": token } : {};
}

/**
 * Direct backend URL for streaming endpoints (SSE).
 *
 * Why: Next.js `rewrites()` proxies buffer the entire response before
 * forwarding — fine for JSON, fatal for SSE. The chat stream would arrive
 * at the browser as a single buffered chunk, defeating token-by-token
 * streaming and making the typewriter cursor look fake.
 *
 * Resolution order:
 *   1. ``window.__BACKEND_PUBLIC_URL__`` — runtime-injected by layout.tsx
 *      from the server-side ``BACKEND_PUBLIC_URL`` env var. Set when the
 *      browser can reach the backend directly (requires CORS).
 *   2. Desktop runtime injection or localStorage configuration.
 *   3. ``NEXT_PUBLIC_API_BASE_URL`` — build-time fallback (local dev only).
 *   4. empty string → SSE uses same-origin ``/api/v1/*``. This is the
 *      default in cloud/Docker deployments where nginx (or a similar
 *      streaming-aware reverse proxy) fronts both frontend and backend,
 *      so the browser only talks to one origin and there are no CORS
 *      issues. See nginx/nginx.conf in the repo.
 */
function getStreamBaseUrl(): string {
  if (typeof window !== "undefined") {
    if (typeof window.__BACKEND_PUBLIC_URL__ === "string") {
      return normalizeBaseUrl(window.__BACKEND_PUBLIC_URL__);
    }
  }
  return getApiBaseUrl();
}

export function streamApiUrl(path: string): string {
  return `${getStreamBaseUrl()}${API_PREFIX}${path}`;
}

// ---------- Auth token storage ----------
//
// Tokens are persisted to localStorage and attached to every API request
// as a Bearer header. The auth module (lib/auth.ts) owns these accessors
// and refreshes the access token automatically when it expires.
//
// Why localStorage (not cookies):
//   - LifeTree is a SPA-style Next.js app; localStorage integrates cleanly
//     with fetch + SWR without CSRF concerns.
//   - Cross-tab sync is handled via a custom event (see lib/auth.ts).

export const ACCESS_TOKEN_KEY = "lifetree.access_token";
export const REFRESH_TOKEN_KEY = "lifetree.refresh_token";

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(ACCESS_TOKEN_KEY);
}

export function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(REFRESH_TOKEN_KEY);
}

export function setTokens(access: string, refresh: string) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(ACCESS_TOKEN_KEY, access);
  window.localStorage.setItem(REFRESH_TOKEN_KEY, refresh);
  // Notify other tabs/tabs that auth changed.
  window.dispatchEvent(new Event("lifetree:auth-changed"));
}

export function clearTokens() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(ACCESS_TOKEN_KEY);
  window.localStorage.removeItem(REFRESH_TOKEN_KEY);
  window.dispatchEvent(new Event("lifetree:auth-changed"));
}

export class ApiError extends Error {
  constructor(public status: number, message: string, public details?: unknown) {
    super(message);
    this.name = "ApiError";
  }
}

export async function request<T>(
  path: string,
  init?: RequestInit & { skipJson?: boolean }
): Promise<T> {
  // Attach Bearer token to every request when available.
  const token = getAccessToken();

  // FormData: the browser must set Content-Type itself (with the
  // multipart boundary). Forcing ``application/json`` here would make
  // the backend try to parse the body as JSON and fail. Detect FormData
  // and skip the default Content-Type so uploads work correctly.
  const isFormData = init?.body instanceof FormData;

  const headers = new Headers(init?.headers);
  for (const [name, value] of Object.entries(getDesktopHeaders())) {
    headers.set(name, value);
  }
  if (!isFormData && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const res = await fetch(apiUrl(path), {
    ...init,
    headers,
  });

  // 401 → attempt a single token refresh, then retry once.
  if (res.status === 401 && token && !headers.has("X-Retry")) {
    const refreshed = await tryRefreshAccessToken();
    if (refreshed) {
      headers.set("X-Retry", "1");
      headers.delete("Authorization");
      return request<T>(path, {
        ...init,
        headers,
      });
    }
  }

  if (!res.ok) {
    let details: unknown;
    try {
      details = await res.json();
    } catch {
      details = undefined;
    }
    throw new ApiError(res.status, apiErrorMessage(res.status, path, details), details);
  }
  if (init?.skipJson) return undefined as T;
  return res.json() as Promise<T>;
}

// ---------- Token refresh (singleton, deduped) ----------
//
// When multiple in-flight requests get 401 simultaneously, we only want
// to hit /auth/refresh once. The pending-promise pattern below dedupes.

let refreshPromise: Promise<boolean> | null = null;

async function tryRefreshAccessToken(): Promise<boolean> {
  if (refreshPromise) return refreshPromise;
  refreshPromise = (async () => {
    const refresh = getRefreshToken();
    if (!refresh) return false;
    try {
      const res = await fetch(apiUrl("/auth/refresh"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...getDesktopHeaders(),
        },
        body: JSON.stringify({ refresh_token: refresh }),
      });
      if (!res.ok) {
        clearTokens();
        return false;
      }
      const data = await res.json();
      setTokens(data.access_token, data.refresh_token);
      return true;
    } catch {
      clearTokens();
      return false;
    } finally {
      refreshPromise = null;
    }
  })();
  return refreshPromise;
}

// ---------- Domain fetchers ----------

export const api = {
  // Auth
  login: (body: { email: string; password: string }) =>
    request<AuthTokenResponse>(`/auth/login`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  register: (body: RegisterRequest) =>
    request<AuthTokenResponse>(`/auth/register`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getMe: () => request<UserProfileRead>(`/auth/me`),
  logout: () => clearTokens(),

  // Auth config + OAuth + email verification
  getAuthConfig: () => request<PublicAuthConfig>(`/auth/config`),
  sendCode: (email: string) =>
    request<SendCodeResponse>(`/auth/send-code`, {
      method: "POST",
      body: JSON.stringify({ email }),
    }),
  registerWithCode: (body: RegisterWithCodeRequest) =>
    request<AuthTokenResponse>(`/auth/register-with-code`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  oauthStart: (
    providerId: string,
    mode?: "login" | "register",
    acceptedTerms = false
  ) => {
    const params = new URLSearchParams();
    if (mode && mode !== "login") params.set("mode", mode);
    if (acceptedTerms) params.set("accepted_terms", "true");
    const query = params.size ? `?${params.toString()}` : "";
    return request<OAuthStartResponse>(
      `/auth/oauth/${encodeURIComponent(providerId)}/start${query}`
    );
  },
  oauthCallback: (providerId: string, code: string, state?: string) => {
    const qs = new URLSearchParams({ code });
    if (state) qs.set("state", state);
    return request<AuthTokenResponse>(
      `/auth/oauth/${encodeURIComponent(providerId)}/callback?${qs.toString()}`
    );
  },

  // OAuth binding (current user) — link/unlink an OAuth provider to your account
  oauthBindStart: (providerId: string) =>
    request<OAuthStartResponse>(
      `/auth/oauth/${encodeURIComponent(providerId)}/bind-start`
    ),
  listOAuthBindings: () =>
    request<OAuthBindingRead[]>(`/auth/oauth/bindings`),
  unbindOAuth: (providerId: string) =>
    request<{ ok: boolean }>(
      `/auth/oauth/bindings/${encodeURIComponent(providerId)}`,
      { method: "DELETE" }
    ),

  // Admin OAuth provider CRUD (admin-only)
  listOAuthProviders: () =>
    request<OAuthProviderView[]>(`/settings/oauth`),
  addOAuthProvider: (body: OAuthProviderCreate) =>
    request<OAuthProviderView>(`/settings/oauth`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateOAuthProvider: (id: string, body: OAuthProviderUpdate) =>
    request<OAuthProviderView>(`/settings/oauth/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteOAuthProvider: (id: string) =>
    request<{ ok: boolean }>(`/settings/oauth/${id}`, {
      method: "DELETE",
    }),
  getOAuthProviderSecret: (id: string) =>
    request<{ value: string | null; configured: boolean }>(
      `/settings/oauth/${id}/secret`
    ),

  // Admin
  adminListUsers: () => request<AdminUserRead[]>(`/admin/users`),
  adminUpdateUser: (id: string, body: AdminUserUpdate) =>
    request<AdminUserRead>(`/admin/users/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  adminDeleteUser: (id: string) =>
    request<void>(`/admin/users/${id}`, { method: "DELETE", skipJson: true }),
  adminStats: () => request<AdminStats>(`/admin/stats`),

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
  destroyMyAccount: () =>
    request<void>(`/users/me/destroy`, {
      method: "DELETE",
      skipJson: true,
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

  // Actions — today's queue, CRUD, complete, ROI sort
  listTodayActions: (goalId?: string) =>
    request<ActionRead[]>(
      `/actions/today${goalId ? `?goal_id=${encodeURIComponent(goalId)}` : ""}`
    ),
  listActions: (params?: {
    goal_id?: string;
    status?: ActionStatus | string;
    stage?: string;
    due_before?: string;
    due_after?: string;
    limit?: number;
  }) => {
    const q = new URLSearchParams();
    if (params?.goal_id) q.set("goal_id", params.goal_id);
    if (params?.status) q.set("status", params.status);
    if (params?.stage) q.set("stage", params.stage);
    if (params?.due_before) q.set("due_before", params.due_before);
    if (params?.due_after) q.set("due_after", params.due_after);
    if (params?.limit != null) q.set("limit", String(params.limit));
    const qs = q.toString();
    return request<ActionRead[]>(`/actions${qs ? `?${qs}` : ""}`);
  },
  createAction: (payload: ActionCreate) =>
    request<ActionRead>(`/actions`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateAction: (id: string, payload: ActionUpdate) =>
    request<ActionRead>(`/actions/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  completeAction: (id: string) =>
    request<ActionRead>(`/actions/${id}/complete`, { method: "POST" }),
  deleteAction: (id: string) =>
    request<void>(`/actions/${id}`, { method: "DELETE", skipJson: true }),
  listROIActions: (limit = 10) =>
    request<ActionROISort>(`/actions/roi?limit=${limit}`),
  downloadActionCalendar: async () => {
    const token = getAccessToken();
    const response = await fetch(apiUrl("/actions/calendar.ics"), {
      headers: {
        ...getDesktopHeaders(),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    });
    if (!response.ok) throw new ApiError(response.status, "Action calendar export failed");
    const url = URL.createObjectURL(await response.blob());
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "lifetree-actions.ics";
    anchor.click();
    URL.revokeObjectURL(url);
  },

  // Risk factors
  listRiskFactors: () => request<unknown[]>(`/risk-factors`),

  // Events
  listEvents: (riskLevel?: string) =>
    request<unknown[]>(`/events${riskLevel ? `?risk_level=${riskLevel}` : ""}`),

  // §4.9 Review Inbox — pending-review queue + status transition
  listPendingReview: (limit = 50) =>
    request<unknown[]>(`/events/pending-review?limit=${limit}`),
  updateEventStatus: (eventId: string, action: "approve" | "sink" | "keep_sunk") =>
    request<unknown>(`/events/${eventId}/status`, {
      method: "PATCH",
      body: JSON.stringify({ action }),
    }),
  getUnifiedReviewInbox: () => request<UnifiedReviewInbox>(`/review/inbox`),
  getNotificationChannelStatus: () =>
    request<NotificationChannelStatus>(`/notifications/channels/status`),
  listPushSubscriptions: () =>
    request<Array<{ id: string; enabled: boolean; user_agent?: string | null }>>(
      `/notifications/push-subscriptions`
    ),
  upsertPushSubscription: (payload: {
    endpoint: string;
    p256dh: string;
    auth: string;
    user_agent?: string;
  }) => request<{ id: string; enabled: boolean }>(`/notifications/push-subscriptions`, {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  deletePushSubscription: (id: string) =>
    request<void>(`/notifications/push-subscriptions/${id}`, {
      method: "DELETE",
      skipJson: true,
    }),
  acceptSourceProposal: (id: string) =>
    request<unknown>(`/source-proposals/${id}/accept`, { method: "POST" }),
  rejectSourceProposal: (id: string) =>
    request<unknown>(`/source-proposals/${id}/reject`, { method: "POST" }),
  rejectRiskProposal: (id: string) =>
    request<unknown>(`/risk-discovery/proposals/${id}/reject`, { method: "POST" }),
  adoptRiskProposal: (proposal: ReviewRiskProposal, pathwayId: string) =>
    request<unknown>(`/risk-discovery/adopt`, {
      method: "POST",
      body: JSON.stringify({
        proposal_id: proposal.id,
        pathway_id: pathwayId,
        name: proposal.name,
        type: proposal.type,
        region: proposal.region,
        level: proposal.urgency === "urgent" ? "high" : "medium",
        urgency: proposal.urgency,
        description: proposal.description,
      }),
    }),
  resolveSourceConflict: (conflict: ReviewConflict, sourceId: string) =>
    request<unknown>(`/cross-validation/resolve`, {
      method: "POST",
      body: JSON.stringify({
        subject_id: conflict.subject_id,
        predicate: conflict.predicate,
        winning_source_id: sourceId,
      }),
    }),

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
  updateSourceSchedule: (id: string, body: { auto_refresh: boolean; refresh_interval_minutes: number }) =>
    request<unknown>(`/sources/${id}/schedule`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  refreshSourceNow: (id: string) =>
    request<unknown>(`/sources/${id}/refresh`, { method: "POST" }),

  // Scenarios
  listScenarios: (goalId: string) =>
    request<unknown[]>(`/scenarios?goal_id=${goalId}`),
  createScenario: (payload: {
    goal_id: string;
    pathway_id?: string;
    name: string;
    description?: string;
    assumptions?: Record<string, unknown>;
  }) =>
    request<unknown>(`/scenarios`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateScenario: (
    id: string,
    payload: {
      name?: string;
      description?: string;
      status?: "draft" | "active" | "dormant" | "merged" | "closed";
      assumptions?: Record<string, unknown>;
      impact_threshold?: number;
    }
  ) =>
    request<unknown>(`/scenarios/${id}`, {
      method: "PATCH",
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
  mergeScenario: (id: string) =>
    request<unknown>(`/scenarios/${id}/merge`, { method: "POST" }),
  runScenario: (id: string) =>
    request<unknown>(`/scenarios/${id}/run`, { method: "POST" }),
  evolveScenario: (id: string) =>
    request<EvolutionProjection>(`/scenarios/${id}/evolve`, { method: "POST" }),
  getEvolution: (id: string) =>
    request<EvolutionProjection>(`/scenarios/${id}/evolve`, { method: "GET" }),

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
    // Use ``request`` (not raw fetch) so the Authorization header is
    // attached and 401 token-refresh retry kicks in. Previously this
    // used a bare ``fetch`` with no auth, causing the backend to reject
    // uploads with 500 (auth failure surfaced as a server error).
    return request<IngestUploadResponse>(`/ingest/upload`, {
      method: "POST",
      body: fd,
    });
  },

  // Plugins
  listPlugins: () => request<PluginManifest[]>(`/plugins`),
  getPlugin: (id: string) => request<PluginManifest>(`/plugins/${id}`),
  runPlugin: (id: string, body: { params: Record<string, unknown>; title?: string; skip_llm?: boolean }) =>
    request<PluginRunResult>(`/plugins/${id}/run`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  uploadPlugin: (file: File, overwrite?: boolean) => {
    const fd = new FormData();
    const token = getAccessToken();
    fd.append("file", file);
    if (overwrite) fd.append("overwrite", "true");
    return fetch(apiUrl("/plugins/upload"), {
      method: "POST",
      body: fd,
      headers: {
        ...getDesktopHeaders(),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    }).then(async (r) => {
      if (!r.ok) {
        let details: unknown;
        try { details = await r.json(); } catch { details = undefined; }
        throw new ApiError(r.status, `Upload failed (${r.status})`, details);
      }
      return r.json() as Promise<PluginUploadResponse>;
    });
  },
  deletePlugin: (id: string) =>
    request<{ ok: boolean; plugin_id: string }>(`/plugins/${id}`, {
      method: "DELETE",
    }),
  togglePlugin: (id: string, enabled: boolean) =>
    request<{ ok: boolean; plugin_id: string; enabled: boolean }>(
      `/plugins/${id}/enabled`,
      {
        method: "PATCH",
        body: JSON.stringify({ enabled }),
      }
    ),

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
  getRuntimeCatalog: () => request<RuntimeCatalog>(`/settings/runtime/catalog`),
  getUserServicePolicy: () => request<{ enabled: boolean }>(`/settings/runtime/policy`),
  setUserServicePolicy: (enabled: boolean) =>
    request<{ enabled: boolean }>(`/settings/runtime/policy`, {
      method: "PUT", body: JSON.stringify({ enabled }),
    }),
  addUserProvider: (body: ProviderCreate) =>
    request<RuntimeCatalog>(`/settings/runtime/providers`, {
      method: "POST", body: JSON.stringify(body),
    }),
  addUserModel: (body: ModelCreate) =>
    request<RuntimeCatalog>(`/settings/runtime/models`, {
      method: "POST", body: JSON.stringify(body),
    }),
  setUserRoles: (assignments: Partial<Record<Role, string | null>>) =>
    request<RuntimeCatalog>(`/settings/runtime/roles`, {
      method: "PUT", body: JSON.stringify({ assignments }),
    }),
  setUserServices: (body: UserServicesUpdate) =>
    request<RuntimeCatalog>(`/settings/runtime/services`, {
      method: "PUT", body: JSON.stringify(body),
    }),
  listMcpServers: () => request<MCPServer[]>(`/settings/runtime/mcp`),
  addMcpServer: (body: MCPServerCreate) =>
    request<MCPServer>(`/settings/runtime/mcp`, {
      method: "POST", body: JSON.stringify(body),
    }),
  toggleMcpServer: (id: string, enabled: boolean) =>
    request<MCPServer>(`/settings/runtime/mcp/${id}`, {
      method: "PATCH", body: JSON.stringify({ enabled }),
    }),
  deleteMcpServer: (id: string) =>
    request<void>(`/settings/runtime/mcp/${id}`, { method: "DELETE", skipJson: true }),
  listSkills: () => request<UserSkillView[]>(`/settings/skills`),
  addTextSkill: (name: string, content: string) =>
    request<UserSkillView>(`/settings/skills/text`, {
      method: "POST", body: JSON.stringify({ name, content }),
    }),
  addGithubSkill: (name: string, repositoryUrl: string) =>
    request<UserSkillView>(`/settings/skills/github`, {
      method: "POST", body: JSON.stringify({ name, repository_url: repositoryUrl }),
    }),
  addArchiveSkill: (name: string, archive: File) => {
    const body = new FormData();
    body.append("name", name);
    body.append("archive", archive);
    return request<UserSkillView>(`/settings/skills/archive`, { method: "POST", body });
  },
  addFolderSkill: (name: string, files: File[]) => {
    const body = new FormData();
    body.append("name", name);
    files.forEach((file) => body.append("files", file, file.webkitRelativePath || file.name));
    return request<UserSkillView>(`/settings/skills/folder`, { method: "POST", body });
  },
  toggleSkill: (id: string, enabled: boolean) =>
    request<UserSkillView>(`/settings/skills/${id}`, {
      method: "PATCH", body: JSON.stringify({ enabled }),
    }),
  deleteSkill: (id: string) =>
    request<void>(`/settings/skills/${id}`, { method: "DELETE", skipJson: true }),

  // System components — read-only docker service status
  getSystemComponents: () =>
    request<SystemComponentsView>(`/system/components`),

  // Changes summary — since-last-visit aggregate digest
  getChangesSummary: (since?: string) =>
    request<ChangesSummary>(
      `/changes-summary${since ? `?since=${encodeURIComponent(since)}` : ""}`
    ),
  getLastVisit: () =>
    request<{ last_visit_at: string | null }>(`/changes-summary/last-visit`),

  // Health — unauthenticated component reachability
  getComponentsHealth: () =>
    request<ComponentsHealth>(`/health/components`),

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

  setUseMode: (mode: "single" | "multi") =>
    request<{ mode: "single" | "multi" }>(`/settings/use-mode`, {
      method: "PUT",
      body: JSON.stringify({ mode }),
    }),

  // Email verification toggle (admin)
  getEmailVerification: () =>
    request<{ enabled: boolean }>(`/settings/email-verification`),
  setEmailVerification: (enabled: boolean) =>
    request<{ enabled: boolean }>(`/settings/email-verification`, {
      method: "PUT",
      body: JSON.stringify({ enabled }),
    }),

  // Disable registration toggle (admin)
  getDisableRegistration: () =>
    request<{ enabled: boolean }>(`/settings/disable-registration`),
  setDisableRegistration: (enabled: boolean) =>
    request<{ enabled: boolean }>(`/settings/disable-registration`, {
      method: "PUT",
      body: JSON.stringify({ enabled }),
    }),

  // Service address (admin) — public URL used in emails/notifications
  getServiceAddress: () =>
    request<{ address: string }>(`/settings/service-address`),
  setServiceAddress: (address: string) =>
    request<{ address: string }>(`/settings/service-address`, {
      method: "PUT",
      body: JSON.stringify({ address }),
    }),

  // Passkey login toggle (admin)
  getPasskeyLogin: () =>
    request<{ enabled: boolean }>(`/settings/passkey-login`),
  setPasskeyLogin: (enabled: boolean) =>
    request<{ enabled: boolean }>(`/settings/passkey-login`, {
      method: "PUT",
      body: JSON.stringify({ enabled }),
    }),

  // Passkey registration (current user — bind a new passkey to your account)
  passkeyRegisterOptions: () =>
    request<{ options: Record<string, unknown> }>(
      `/auth/passkey/registration/options`,
      { method: "POST" }
    ),
  passkeyRegisterVerify: (
    credential: Record<string, unknown>,
    nickname?: string
  ) =>
    request<{ ok: boolean; passkey: PasskeyRead }>(
      `/auth/passkey/registration/verify`,
      {
        method: "POST",
        body: JSON.stringify({ credential, nickname: nickname ?? "" }),
      }
    ),

  // Passkey authentication (no auth — passwordless login)
  passkeyAuthOptions: () =>
    request<{ options: Record<string, unknown> }>(
      `/auth/passkey/auth/options`,
      { method: "POST" }
    ),
  passkeyAuthVerify: (credential: Record<string, unknown>) =>
    request<AuthTokenResponse>(`/auth/passkey/auth/verify`, {
      method: "POST",
      body: JSON.stringify({ credential }),
    }),

  // Passkey management (current user)
  listPasskeys: () => request<PasskeyRead[]>(`/auth/passkeys`),
  deletePasskey: (id: string) =>
    request<{ ok: boolean }>(`/auth/passkeys/${id}`, {
      method: "DELETE",
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

// ---------- Scenario self-evolution types ----------

export interface ProjectedEvent {
  month: number;
  title: string;
  type: "milestone" | "risk" | "opportunity" | "decision";
  description: string;
  probability: number;
  impact: number;
  dependencies: string[];
}

export interface EvolutionProjection {
  summary: string;
  projected_events: ProjectedEvent[];
  trajectory: Array<{ month: number; p: number }>;
  final_probability: number;
  confidence: number;
  evolved_at: string | null;
  horizon_months: number;
  cached: boolean;
}

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

export type Protocol =
  | "openai_compatible"
  | "ollama"
  | "anthropic"
  | "bailian"
  | "bailian_rerank";
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

// ---------- Action types ----------

export type ActionStatus =
  | "pending"
  | "in_progress"
  | "completed"
  | "skipped"
  | "deferred";

export const ALL_ACTION_STATUSES: ActionStatus[] = [
  "pending",
  "in_progress",
  "completed",
  "skipped",
  "deferred",
];

export interface ActionRead {
  id: string;
  user_id: string;
  goal_id: string;
  title: string;
  description?: string | null;
  stage?: string | null;
  status: ActionStatus;
  due_at?: string | null;
  recurrence?: string;
  cost?: number;
  expected_prob_lift?: number;
  roi?: number;
  scenario_id?: string | null;
  pathway_id?: string | null;
  requirement_id?: string | null;
  risk_factor_id?: string | null;
  source?: string;
  completed_at?: string | null;
  actual_cost?: number | null;
  actual_prob_lift?: number | null;
  source_run_id?: string | null;
  meta?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ActionCreate {
  goal_id: string;
  title: string;
  description?: string | null;
  stage?: string | null;
  due_at?: string | null;
  recurrence?: string;
  cost?: number;
  expected_prob_lift?: number;
  scenario_id?: string | null;
  pathway_id?: string | null;
  requirement_id?: string | null;
  risk_factor_id?: string | null;
}

export interface ActionUpdate {
  title?: string;
  description?: string | null;
  stage?: string | null;
  status?: ActionStatus;
  due_at?: string | null;
  recurrence?: string;
  cost?: number;
  expected_prob_lift?: number;
  scenario_id?: string | null;
  pathway_id?: string | null;
  requirement_id?: string | null;
  risk_factor_id?: string | null;
}

export interface ActionROISort {
  actions: ActionRead[];
  count: number;
}

export interface ReviewSourceProposal {
  id: string;
  title: string;
  url: string;
  relevance_score: number;
  credibility_hint: string;
}

export interface ReviewPendingSource {
  id: string;
  title: string;
  kind: string;
  url?: string | null;
  publisher?: string | null;
  published_at?: string | null;
  credibility: string;
}

export interface ReviewRiskProposal {
  id: string;
  name: string;
  type: string;
  region?: string | null;
  urgency: string;
  description: string;
  affected_goals_count: number;
  impact_preview: { suggested_pathway_id?: string | null };
}

export interface ReviewConflict {
  subject_id: string;
  predicate: string;
  severity: string;
  conflicting_values: Array<{
    object_id: string;
    source_id: string | null;
    source_title?: string | null;
    source_credibility: number;
  }>;
}

export interface UnifiedReviewInbox {
  counts: Record<
    "events" | "source_proposals" | "pending_sources" | "risk_proposals" | "conflicts",
    number
  >;
  events: Array<{
    id: string;
    subject?: string | null;
    action: string;
    risk_flag_level?: string | null;
    created_at: string;
  }>;
  source_proposals: ReviewSourceProposal[];
  pending_sources: ReviewPendingSource[];
  risk_proposals: ReviewRiskProposal[];
  conflicts: ReviewConflict[];
}

export interface NotificationChannelStatus {
  web_push: {
    available: boolean;
    credentials_configured: boolean;
    subscriptions: number;
    public_key?: string | null;
  };
  sms: { available: boolean; provider: string; reason?: string | null };
  email: { available: boolean; recipient_configured: boolean };
  in_app: { available: boolean; transport: string };
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
  role: "admin" | "user";
  is_enabled: boolean;
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

// ---------- Auth / admin types ----------

export interface AuthTokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  user: UserProfileRead;
}

export interface AdminUserRead extends UserProfileRead {
  has_password: boolean;
}

export interface AdminUserUpdate {
  display_name?: string;
  role?: "admin" | "user";
  is_enabled?: boolean;
  new_password?: string;
}

export interface AdminStats {
  total_users: number;
  enabled_users: number;
  admin_users: number;
  disabled_users: number;
}

// ---------- Public auth config (login dialog) ----------

export interface OAuthProviderPublic {
  id: string;
  name: string;
  avatar_url?: string;
}

export interface PublicAuthConfig {
  oauth_providers: OAuthProviderPublic[];
  email_verification_enabled: boolean;
  disable_registration: boolean;
  multi_user_mode: boolean;
  use_mode: "single" | "multi";
  /** False when no real users exist → frontend shows first-admin setup. */
  has_users: boolean;
  /** When true, login dialog shows passkey button + profile shows passkey UI. */
  passkey_login_enabled: boolean;
}

export interface SendCodeResponse {
  ok: boolean;
  error?: string | null;
  expires_in: number;
}

export interface LegalConsentRequest {
  accepted_terms: true;
  terms_version: string;
  privacy_version: string;
}

export interface RegisterRequest extends LegalConsentRequest {
  display_name: string;
  email: string;
  password: string;
}

export interface RegisterWithCodeRequest extends LegalConsentRequest {
  display_name: string;
  email: string;
  code: string;
  password?: string;
}

export interface OAuthStartResponse {
  authorize_url: string;
  state: string;
}

// ---------- OAuth provider (admin-configured) ----------

export interface OAuthProviderView {
  id: string;
  name: string;
  client_id: string;
  client_id_configured: boolean;
  client_secret_configured: boolean;
  authorize_url: string;
  token_url: string;
  userinfo_url: string;
  scopes: string[];
  redirect_uri: string;
  enabled: boolean;
  avatar_url: string;
  created_at: string;
}

export interface OAuthProviderCreate {
  name: string;
  client_id?: string;
  client_secret?: string;
  authorize_url?: string;
  token_url?: string;
  userinfo_url?: string;
  scopes?: string[];
  redirect_uri?: string;
  enabled?: boolean;
  avatar_url?: string;
}

export interface OAuthProviderUpdate {
  name?: string;
  client_id?: string | null;
  client_secret?: string | null;
  authorize_url?: string | null;
  token_url?: string | null;
  userinfo_url?: string | null;
  scopes?: string[] | null;
  redirect_uri?: string | null;
  enabled?: boolean | null;
  avatar_url?: string | null;
}

// ---------- OAuth binding (current user) ----------

export interface OAuthBindingRead {
  provider_id: string;
  provider_name: string;
  external_sub: string;
  created_at: string;
}

// ---------- Passkey (current user) ----------

export interface PasskeyRead {
  id: string;
  nickname: string;
  device_type: string;
  backed_up: boolean;
  transports: string[];
  aaguid: string;
  created_at: string;
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
  // §5.3 信源溯源下钻 — populated by the reasoning engine so the UI can
  // offer one-click drill-down to the original source behind any deduction.
  source_title?: string;
  source_url?: string;
  source_kind?: string;
  source_credibility?: string;
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

export interface RuntimeProvider extends ProviderView {
  managed_by: "admin" | "user";
}

export interface RuntimeModel extends ModelView {
  managed_by: "admin" | "user";
}

export interface RuntimeCatalog {
  allow_user_service_config: boolean;
  providers: RuntimeProvider[];
  models: RuntimeModel[];
  role_assignments: Partial<Record<Role, string>>;
  tavily_configured: boolean;
  mineru_configured: boolean;
  mineru_base_url: string;
}

export interface UserServicesUpdate {
  tavily_api_key?: string | null;
  mineru_api_key?: string | null;
  mineru_base_url?: string | null;
}

export interface MCPServer {
  id: string;
  name: string;
  protocol: "http" | "sse" | "stdio";
  description: string;
  config: Record<string, unknown>;
  enabled: boolean;
  created_at: string;
}

export interface MCPServerCreate {
  name: string;
  protocol: "http" | "sse" | "stdio";
  description?: string;
  url?: string;
  command?: string;
  args?: string[];
  headers?: Record<string, string>;
  extra_body?: Record<string, unknown>;
}

export interface UserSkillView {
  id: string;
  name: string;
  source_type: "text" | "archive" | "folder" | "github";
  source_ref: string;
  enabled: boolean;
  content_preview: string;
  created_at: string;
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
  // Plugin upload extension (optional — builtins don't set these)
  source?: "builtin" | "user";
  enabled?: boolean;
  can_delete?: boolean;
  uploaded_at?: string;
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

export interface IngestUploadResponse {
  source_id: string;
  events_created: number;
  metrics_created: number;
  assertions_created: number;
  relationships_created: number;
  extraction_confidence: number | null;
  notifications_triggered: number;
  // Backends may include extra fields (e.g. parser warnings); allow them.
  [key: string]: unknown;
}

export interface PluginUploadResponse {
  ok: boolean;
  plugin_id: string | null;
  manifest: Omit<PluginManifest, "source" | "enabled" | "can_delete" | "uploaded_at"> | null;
  source: "user";
  warnings: string[];
  error: string | null;
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

// ---------- Changes summary (since-last-visit digest) ----------

export interface RiskLevelChange {
  risk_factor_name: string;
  old_level: string | null;
  new_level: string | null;
}

export interface HighRiskEventSummary {
  subject: string;
  action: string;
  occurred_at: string | null;
}

export interface ChangesSummary {
  since: string;
  new_events: number;
  new_sources: number;
  new_goals: number;
  new_actions: number;
  completed_actions: number;
  new_risk_factors: number;
  updated_scenarios: number;
  new_source_proposals: number;
  risk_level_changes: RiskLevelChange[];
  recent_high_risk_events: HighRiskEventSummary[];
  last_visit_at: string | null;
}

// ---------- Health (component reachability) ----------

export interface ComponentsHealth {
  database: { status: "ok" | "error" | "unknown" };
  neo4j: { status: "ok" | "error" | "unknown" };
  redis: { status: "ok" | "error" | "unknown" };
  timestamp: string;
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
  id?: string | null;
}

export interface ChatChunk {
  delta: string;
  tool_call?: ChatToolCall | null;
  finish_reason: string | null;
  usage?: Record<string, number>;
  reasoning_delta?: string | null;
}

export async function* streamChat(
  body: {
    goal_id?: string;
    scenario_id?: string;
    model_id?: string;
    messages: { role: string; content: string }[];
    web_search?: boolean;
    enabled_mcp_servers?: string[];
    enabled_skills?: string[];
  },
  signal?: AbortSignal
): AsyncGenerator<ChatChunk> {
  // Bypass the Next.js rewrite proxy when a runtime API origin is configured.
  // Why: Next.js `rewrites()` buffers the SSE response in dev mode — the
  // browser receives the entire stream as one giant chunk, defeating
  // token-by-token streaming and making the typewriter cursor look fake.
  // Hitting the backend origin directly preserves true SSE chunking.
  // Falls back to the proxy path when no backend URL is configured (e.g.
  // production behind a streaming-aware reverse proxy).
  const streamUrl = streamApiUrl("/chat/stream");
  // Attach Bearer token — streamChat uses raw fetch (not ``request``) so
  // it must add the Authorization header manually. Without this the backend
  // returns 401 and the user sees "Chat stream failed".
  const token = getAccessToken();
  const authHeaders: Record<string, string> = token
    ? { Authorization: `Bearer ${token}` }
    : {};
  const res = await fetch(streamUrl, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...getDesktopHeaders(),
      ...authHeaders,
    },
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
