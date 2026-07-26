"use client";

/**
 * Global SSE (Server-Sent Events) Provider.
 *
 * Subscribes to the backend `/api/v1/sse` endpoint and dispatches:
 *   - `risk_alert` → toast notification + SWR revalidation of notifications/dashboard/events
 *   - `scenario_run` → SWR revalidation of scenarios + dashboard
 *   - `hello` → connection established (no-op, just logs)
 *
 * The connection is automatically retried with exponential backoff on
 * disconnect. On the client only (skipped during SSR).
 *
 * Mounted once in `app/layout.tsx` so it runs for every route.
 */

import { useEffect, useRef } from "react";
import { useSWRConfig } from "swr";
import { useToast } from "@/components/ui/toast";
import { useT } from "@/lib/i18n/provider";
import { STREAM_BASE_URL, API_PREFIX } from "@/lib/api";

// Bypass the Next.js rewrite proxy when STREAM_BASE_URL is configured.
// Why: the dev proxy buffers SSE chunks and may abort the connection
// prematurely (net::ERR_INCOMPLETE_CHUNKED_ENCODING), causing repeated
// reconnects. Hitting the backend origin directly preserves the long-lived
// SSE connection. Falls back to the proxy path in production.
const SSE_ENDPOINT = STREAM_BASE_URL
  ? `${STREAM_BASE_URL}${API_PREFIX}/sse`
  : `${API_PREFIX}/sse`;

// Match the SWR keys used in lib/hooks.ts so we can revalidate them.
// `useNotifications` and `useUnreadCount` use array keys whose first
// element is "notifications", so a function matcher is needed to cover
// all filtered/paginated variants + the unread-count key.
const RISK_REVALIDATE_MATCHER = (key: unknown): boolean => {
  if (typeof key === "string") {
    return key === "events" || key === "dashboard";
  }
  if (Array.isArray(key)) {
    const head = key[0];
    return (
      head === "notifications" ||
      head === "events" ||
      head === "dashboard"
    );
  }
  return false;
};

const SCENARIO_REVALIDATE_MATCHER = (key: unknown): boolean => {
  if (typeof key === "string") {
    return key === "scenarios" || key === "dashboard";
  }
  if (Array.isArray(key)) {
    const head = key[0];
    return head === "scenarios" || head === "dashboard";
  }
  return false;
};

export function SSEProvider({ children }: { children: React.ReactNode }) {
  const { mutate } = useSWRConfig();
  const toast = useToast();
  const t = useT();
  // Keep latest toast/mutate/t in a ref so the event handlers (attached once)
  // always see the current values without re-subscribing on every render.
  const handlersRef = useRef({ toast, mutate, t });
  handlersRef.current = { toast, mutate, t };

  const esRef = useRef<EventSource | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectAttempts = useRef(0);

  useEffect(() => {
    if (typeof window === "undefined") return;

    const connect = () => {
      try {
        const es = new EventSource(SSE_ENDPOINT);
        esRef.current = es;

        es.addEventListener("hello", (e) => {
          reconnectAttempts.current = 0;
          try {
            const data = JSON.parse(e.data);
            // eslint-disable-next-line no-console
            console.debug("[SSE] connected", data);
          } catch {
            // ignore
          }
        });

        es.addEventListener("risk_alert", (e) => {
          const { toast, mutate } = handlersRef.current;
          let title = "Risk Alert";
          let description: string | undefined;
          let severity: "info" | "warning" | "critical" = "warning";

          try {
            const data = JSON.parse(e.data);
            title = data.title ?? data.summary ?? title;
            description = data.body ?? data.message ?? description;
            severity = data.severity ?? severity;
          } catch {
            // keep defaults
          }

          toast({
            title,
            description,
            variant:
              severity === "critical"
                ? "error"
                : severity === "warning"
                ? "warning"
                : "default",
          });

          // Revalidate the data that depends on risk alerts.
          mutate(RISK_REVALIDATE_MATCHER);
        });

        // Generic notification event — backend pushes these when any
        // notification is created/delivered (covers channels beyond risk_alert).
        // We don't toast here (the risk_alert handler already covers
        // user-facing alerts); we just trigger SWR revalidation so the
        // notification list + unread badge refresh in real time.
        es.addEventListener("notification", () => {
          const { mutate } = handlersRef.current;
          mutate(RISK_REVALIDATE_MATCHER);
        });

        es.addEventListener("scenario_run", (e) => {
          const { toast, mutate, t } = handlersRef.current;
          let title = t("sse.scenarioRun.title");
          let description: string | undefined;

          try {
            const data = JSON.parse(e.data);
            if (data.name) {
              title = `${t("sse.scenarioRun.title")}: ${data.name}`;
            }
            if (data.success_probability !== undefined) {
              description = `${t("sse.scenarioRun.probability")}: ${Math.round(
                (data.success_probability.bayesian_point ?? data.success_probability.p50 ?? 0
              ) * 100
              )}%`;
            }
          } catch {
            // keep defaults
          }

          toast({ title, description, variant: "success" });

          mutate(SCENARIO_REVALIDATE_MATCHER);
        });

        es.onerror = () => {
          es.close();
          esRef.current = null;
          // Exponential backoff: 1s, 2s, 4s, 8s, max 30s
          const delay = Math.min(
            1000 * Math.pow(2, reconnectAttempts.current),
            30000
          );
          reconnectAttempts.current += 1;
          reconnectTimer.current = setTimeout(connect, delay);
        };
      } catch {
        // EventSource construction can throw if the browser doesn't support it
        // (very rare). Retry anyway.
        const delay = Math.min(
          1000 * Math.pow(2, reconnectAttempts.current),
          30000
        );
        reconnectAttempts.current += 1;
        reconnectTimer.current = setTimeout(connect, delay);
      }
    };

    connect();

    return () => {
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current);
        reconnectTimer.current = null;
      }
      if (esRef.current) {
        esRef.current.close();
        esRef.current = null;
      }
    };
  }, []); // Attach once; handlers read latest values via ref.

  return <>{children}</>;
}
