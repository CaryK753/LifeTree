"use client";

import { useEffect, useRef } from "react";
import { useSWRConfig } from "swr";
import { useToast } from "@/components/ui/toast";
import { useT } from "@/lib/i18n/provider";
import { streamServerEvents, type ServerEvent } from "@/lib/sse-stream";
import {
  DEFAULT_NOTIFICATION_ICON,
  sendSystemNotification,
} from "@/lib/notifications";

const RISK_REVALIDATE_MATCHER = (key: unknown): boolean => {
  if (typeof key === "string") return key === "events" || key === "dashboard";
  if (!Array.isArray(key)) return false;
  return ["notifications", "events", "dashboard"].includes(key[0]);
};

const SCENARIO_REVALIDATE_MATCHER = (key: unknown): boolean => {
  if (typeof key === "string") return key === "scenarios" || key === "dashboard";
  if (!Array.isArray(key)) return false;
  return key[0] === "scenarios" || key[0] === "dashboard";
};

/** Global authenticated SSE subscription for app routes. */
export function SSEProvider({ children }: { children: React.ReactNode }) {
  const { mutate } = useSWRConfig();
  const toast = useToast();
  const t = useT();
  const handlersRef = useRef({ toast, mutate, t });
  handlersRef.current = { toast, mutate, t };

  useEffect(() => {
    let disposed = false;
    let controller: AbortController | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let reconnectAttempts = 0;

    const handleEvent = (event: ServerEvent) => {
      const { toast, mutate, t } = handlersRef.current;
      if (event.event === "hello") {
        reconnectAttempts = 0;
        return;
      }
      if (event.event === "notification") {
        mutate(RISK_REVALIDATE_MATCHER);
        return;
      }
      if (event.event === "risk_alert") {
        let data: Record<string, unknown> = {};
        try {
          data = JSON.parse(event.data);
        } catch {
          // Keep the generic alert text when a server payload is malformed.
        }
        const severity = data.severity;
        const title = String(data.title ?? data.summary ?? "Risk Alert");
        const body = data.body || data.message ? String(data.body ?? data.message) : undefined;
        toast({
          title,
          description: body,
          variant:
            severity === "critical" ? "error" : severity === "warning" ? "warning" : "default",
        });
        // 同步投递到操作系统级通知（浏览器 Notification API / Tauri 通知插件）。
        // 静默失败：权限未授予或环境不支持时回退到上面的应用内 toast。
        void sendSystemNotification({
          title,
          body,
          url: "/notifications",
          icon: DEFAULT_NOTIFICATION_ICON,
          tag: data.event_id ? `risk:${data.event_id}` : "risk-alert",
        });
        mutate(RISK_REVALIDATE_MATCHER);
        return;
      }
      if (event.event === "scenario_run") {
        let data: Record<string, unknown> = {};
        try {
          data = JSON.parse(event.data);
        } catch {
          // Keep the generic completion text when a server payload is malformed.
        }
        const probability = data.success_probability as
          | { bayesian_point?: number; p50?: number }
          | undefined;
        toast({
          title: data.name
            ? `${t("sse.scenarioRun.title")}: ${String(data.name)}`
            : t("sse.scenarioRun.title"),
          description: probability
            ? `${t("sse.scenarioRun.probability")}: ${Math.round(
                (probability.bayesian_point ?? probability.p50 ?? 0) * 100
              )}%`
            : undefined,
          variant: "success",
        });
        mutate(SCENARIO_REVALIDATE_MATCHER);
      }
    };

    const scheduleReconnect = () => {
      if (disposed) return;
      const delay = Math.min(1000 * 2 ** reconnectAttempts, 30000);
      reconnectAttempts += 1;
      reconnectTimer = setTimeout(connect, delay);
    };

    const connect = async () => {
      controller = new AbortController();
      try {
        await streamServerEvents(controller.signal, handleEvent);
        scheduleReconnect();
      } catch (error) {
        if ((error as { name?: string }).name !== "AbortError") scheduleReconnect();
      }
    };

    void connect();
    return () => {
      disposed = true;
      controller?.abort();
      if (reconnectTimer) clearTimeout(reconnectTimer);
    };
  }, []);

  return <>{children}</>;
}
