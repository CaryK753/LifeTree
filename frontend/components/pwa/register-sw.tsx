"use client";

import { useEffect } from "react";

/**
 * Registers the LifeTree service worker for offline support / installability.
 *
 * - Only runs in production builds by default (set NEXT_PUBLIC_SW_DEV=1 to
 *   enable in dev — useful for verifying caching strategies locally).
 * - Listens for a new SW taking control and offers a reload prompt via a
 *   custom event so the UI layer can show a toast.
 */
export function RegisterSW() {
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!("serviceWorker" in navigator)) return;

    const isDev = process.env.NODE_ENV === "development";
    const enableInDev = process.env.NEXT_PUBLIC_SW_DEV === "1";
    if (isDev && !enableInDev) return;

    const register = () => {
      navigator.serviceWorker
        .register("/sw.js", { scope: "/" })
        .then((reg) => {
          // Watch for a new SW taking over.
          let refreshing = false;
          navigator.serviceWorker.addEventListener("controllerchange", () => {
            if (refreshing) return;
            refreshing = true;
            window.dispatchEvent(new CustomEvent("sw:updated"));
            // Auto-reload once the new controller is in charge.
            window.location.reload();
          });

          // If a new SW is waiting, prompt it to skip waiting.
          reg.addEventListener("updatefound", () => {
            const newWorker = reg.installing;
            if (!newWorker) return;
            newWorker.addEventListener("statechange", () => {
              if (
                newWorker.state === "installed" &&
                navigator.serviceWorker.controller
              ) {
                // There's an existing controller → this is an update.
                newWorker.postMessage("SKIP_WAITING");
              }
            });
          });
        })
        .catch((err) => {
          // SW registration is best-effort — don't crash the page.
          console.warn("[sw] registration failed", err);
        });
    };

    // Register after window load to avoid competing with first paint.
    if (document.readyState === "complete") {
      register();
    } else {
      window.addEventListener("load", register, { once: true });
    }
  }, []);

  return null;
}
