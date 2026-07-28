/**
 * SWR hooks for the most common reads.
 */

import useSWR from "swr";
import {
  api,
  swrConfig,
  clearTokens,
  getAccessToken,
  setTokens,
  type AdminStats,
  type AdminUserRead,
  type NotificationChannel,
  type NotificationSeverity,
  type NotificationStatus,
  type NotificationRead,
  type PasskeyRead,
  type PublicAuthConfig,
  type RegisterWithCodeRequest,
  type UserProfileRead,
} from "./api";

export function useGoals() {
  return useSWR("goals", () => api.listGoals(), swrConfig);
}

export function useGoal(goalId?: string) {
  return useSWR(goalId ? ["goal", goalId] : null, () => api.getGoal(goalId!), swrConfig);
}

export function useDashboard(goalId?: string) {
  return useSWR(
    goalId ? ["dashboard", goalId] : null,
    () => (goalId ? api.getDashboard(goalId) : null),
    swrConfig
  );
}

export function usePathways(goalId?: string) {
  return useSWR(goalId ? ["pathways", goalId] : null, () => api.listPathways(goalId!), swrConfig);
}

export function useRequirements(pathwayId?: string) {
  return useSWR(
    pathwayId ? ["requirements", pathwayId] : null,
    () => api.listRequirements(pathwayId!),
    swrConfig
  );
}

export function useRiskFactors() {
  return useSWR("risk-factors", () => api.listRiskFactors(), swrConfig);
}

export function useEvents(riskLevel?: string) {
  return useSWR(["events", riskLevel], () => api.listEvents(riskLevel), swrConfig);
}

// §4.9 Review Inbox — pending-review queue
export function usePendingReview(limit = 50) {
  return useSWR(["pending-review", limit], () => api.listPendingReview(limit), swrConfig);
}

export function useSources() {
  return useSWR("sources", () => api.listSources(), swrConfig);
}

export function useCredibility() {
  return useSWR("credibility", () => api.credibility(), swrConfig);
}

export function useScenarios(goalId?: string) {
  return useSWR(goalId ? ["scenarios", goalId] : null, () => api.listScenarios(goalId!), swrConfig);
}

export function useGraph(goalId?: string, scenarioId?: string) {
  return useSWR(
    goalId ? ["graph", goalId, scenarioId] : null,
    () => (goalId ? api.getGraph(goalId, scenarioId) : null),
    swrConfig
  );
}

export interface NotificationFilter {
  severity?: NotificationSeverity | string;
  status?: NotificationStatus | string;
  channel?: NotificationChannel | string;
  limit?: number;
  offset?: number;
}

/**
 * Notifications list with server-side filtering + pagination.
 *
 * SWR key is `["notifications", filter]` so the SSEProvider's function
 * matcher (which matches any array whose first element is "notifications")
 * revalidates this hook when a `risk_alert` or `notification` event arrives.
 *
 * `refreshInterval` (60s) acts as a fallback polling mechanism so the list
 * stays fresh even if SSE silently drops.
 */
export function useNotifications(filter?: NotificationFilter) {
  return useSWR<NotificationRead[]>(
    ["notifications", filter ?? {}],
    () => api.listNotifications(filter),
    { ...swrConfig, refreshInterval: 60000 }
  );
}

/**
 * Efficient unread badge count — backed by `GET /notifications/unread-count`.
 * Polled every 30s so the badge stays fresh even without an SSE push.
 */
export function useUnreadCount() {
  return useSWR<{ count: number }>(
    ["notifications", "unread-count"],
    () => api.getUnreadCount(),
    { ...swrConfig, refreshInterval: 30000 }
  );
}

export function useSettings() {
  return useSWR("settings", () => api.getSettings(), swrConfig);
}

export function useRuntimeCatalog() {
  return useSWR("runtime-catalog", () => api.getRuntimeCatalog(), swrConfig);
}

export function useMcpServers() {
  return useSWR("mcp-servers", () => api.listMcpServers(), swrConfig);
}

export function useUserSkills() {
  return useSWR("user-skills", () => api.listSkills(), swrConfig);
}

export function useSystemComponents() {
  return useSWR("system-components", () => api.getSystemComponents(), swrConfig);
}

export function usePlugins() {
  return useSWR("plugins", () => api.listPlugins(), swrConfig);
}

export function useUserProfile(id?: string) {
  // In multi-user mode, non-admins get only their own profile from
  // ``GET /users`` (the backend restricts the list). We prefer
  // ``GET /auth/me`` for the current user's profile — it's cheaper
  // and doesn't require admin privileges. The ``id`` param (used by
  // the profile page to view a specific user) falls back to ``listUsers``
  // so admins can still view other users.
  return useSWR<UserProfileRead>(
    id ? ["user-profile", id] : "user-profile",
    async () => {
      if (id) {
        const list = await api.listUsers();
        const users = list as UserProfileRead[];
        return users.find((u) => u.id === id) ?? users[0];
      }
      return api.getMe();
    },
    swrConfig
  );
}

// ---------- Auth ----------

/**
 * useAuth: current user state + login/register/logout actions.
 *
 * Fetches ``GET /auth/me`` only when an access token exists. Both runtime
 * modes require login, so anonymous polling would only produce repeated 401s.
 *
 * The token is refreshed automatically by the ``request()`` helper in
 * lib/api.ts when an API call returns 401.
 */
export function useAuth(options: { loadAnonymousUser?: boolean } = {}) {
  const { loadAnonymousUser = false } = options;
  const hasToken = typeof window !== "undefined" && !!getAccessToken();
  const {
    data: user,
    error,
    isLoading,
    mutate,
  } = useSWR<UserProfileRead | null>(
    hasToken || loadAnonymousUser ? "auth-me" : null,
    () => api.getMe().catch(() => null),
    { ...swrConfig, shouldRetryOnError: false }
  );

  async function login(email: string, password: string) {
    const res = await api.login({ email, password });
    setTokens(res.access_token, res.refresh_token);
    await mutate(res.user, { revalidate: false });
    return res.user;
  }

  async function register(
    displayName: string,
    email: string,
    password: string,
    legalConsent: import("./api").LegalConsentRequest
  ) {
    const res = await api.register({
      display_name: displayName,
      email,
      password,
      ...legalConsent,
    });
    setTokens(res.access_token, res.refresh_token);
    await mutate(res.user, { revalidate: false });
    return res.user;
  }

  async function registerWithCode(body: RegisterWithCodeRequest) {
    const res = await api.registerWithCode(body);
    setTokens(res.access_token, res.refresh_token);
    await mutate(res.user, { revalidate: false });
    return res.user;
  }

  /** Complete OAuth login by exchanging the provider's code for our JWT pair. */
  async function loginWithOAuth(
    providerId: string,
    code: string,
    state?: string
  ) {
    const res = await api.oauthCallback(providerId, code, state);
    setTokens(res.access_token, res.refresh_token);
    await mutate(res.user, { revalidate: false });
    return res.user;
  }

  async function logout() {
    clearTokens();
    await mutate(null, { revalidate: false });
  }

  return {
    user,
    error,
    // Only show the loading overlay when verifying a token.
    isLoading: hasToken && isLoading,
    // True only when a token resolves to a real account.
    isAuthenticated: hasToken && !!user,
    isAdmin: user?.role === "admin",
    login,
    register,
    registerWithCode,
    loginWithOAuth,
    logout,
    refresh: () => mutate(),
  };
}

/**
 * useAuthConfig: public auth config for the login dialog.
 *
 * Returns OAuth provider list (id + name only) and the email-verification
 * flag. Safe to call unauthenticated — the underlying ``GET /auth/config``
 * endpoint returns no secrets.
 */
export function useAuthConfig() {
  return useSWR<PublicAuthConfig>(
    "auth-config",
    () => api.getAuthConfig(),
    { ...swrConfig, shouldRetryOnError: false }
  );
}

// ---------- Admin ----------

export function useAdminStats() {
  return useSWR<AdminStats>("admin-stats", () => api.adminStats(), swrConfig);
}

export function useAdminUsers() {
  return useSWR<AdminUserRead[]>("admin-users", () => api.adminListUsers(), swrConfig);
}

export function useMemories(category?: string) {
  return useSWR(
    category ? ["memories", category] : "memories",
    () => api.listMemories(category),
    swrConfig
  );
}

/**
 * usePasskeys: list of passkeys bound to the current user.
 *
 * Only fetched when ``enabled`` is true (i.e. admin has turned on passkey
 * login) — otherwise the backend returns 403 and we'd just waste a
 * network round-trip.
 */
export function usePasskeys(enabled: boolean) {
  return useSWR<PasskeyRead[]>(
    enabled ? "passkeys" : null,
    () => api.listPasskeys(),
    swrConfig
  );
}

export function useDecayDistribution() {
  return useSWR(
    "lifecycle-distribution",
    () => api.getDecayDistribution(),
    swrConfig
  );
}

export function useLifecycleEvents(status?: import("./api").DecayStatus) {
  return useSWR(
    ["lifecycle-events", status ?? "all"],
    () => api.listLifecycleEvents(status),
    swrConfig
  );
}
