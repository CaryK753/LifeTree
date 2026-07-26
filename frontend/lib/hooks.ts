/**
 * SWR hooks for the most common reads.
 */

import useSWR from "swr";
import {
  api,
  swrConfig,
  type NotificationChannel,
  type NotificationSeverity,
  type NotificationStatus,
  type NotificationRead,
  type UserProfileRead,
} from "./api";

export function useGoals() {
  return useSWR("goals", () => api.listGoals(), swrConfig);
}

export function useGoal(goalId?: string) {
  return useSWR(goalId ? ["goal", goalId] : null, () => api.getGoal(goalId!), swrConfig);
}

export function useDashboard(goalId?: string) {
  return useSWR(goalId ? ["dashboard", goalId] : null, () => api.getDashboard(goalId!), swrConfig);
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
    () => api.getGraph(goalId!, scenarioId),
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

export function useSystemComponents() {
  return useSWR("system-components", () => api.getSystemComponents(), swrConfig);
}

export function usePlugins() {
  return useSWR("plugins", () => api.listPlugins(), swrConfig);
}

export function useUserProfile(id?: string) {
  // Use the first user (single-user app). When id is provided, fetch that one.
  return useSWR<UserProfileRead>(
    "user-profile",
    async () => {
      const list = await api.listUsers();
      const users = list as UserProfileRead[];
      if (users.length === 0) throw new Error("No user created yet");
      return id ? users.find((u) => u.id === id) ?? users[0] : users[0];
    },
    swrConfig
  );
}

export function useMemories(category?: string) {
  return useSWR(
    category ? ["memories", category] : "memories",
    () => api.listMemories(category),
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
