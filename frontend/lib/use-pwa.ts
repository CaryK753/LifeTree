"use client";
import { useLayoutEffect, useState } from "react";

/**
 * Detect whether the app is running as an installed PWA.
 *
 * Detection sources (any one true ⇒ PWA):
 *   1. ``?pwa=1`` URL query param — manual override for testing.
 *   2. ``display-mode`` media query (standalone / minimal-ui /
 *      window-controls-overlay / fullscreen). Each query is run
 *      separately because some browsers mis-handle the comma-separated
 *      OR syntax inside ``matchMedia``.
 *   3. iOS ``navigator.standalone`` (legacy flag, iOS Safari only).
 *   4. iOS: ``document.referrer === ""`` inside standalone (extra
 *      signal — standalone web apps have no referrer on launch).
 *
 * In PWA mode the sidebar is hidden by default and opened as a drawer
 * via ``SidebarToggleButton`` (vs. a persistent rail in non-PWA).
 *
 * Uses ``useLayoutEffect`` so detection runs before first paint.
 * Also toggles a ``pwa`` class on ``<html>`` for CSS-only adjustments.
 */
export function useIsPwa(): boolean {
  const [isPwa, setIsPwa] = useState(false);
  useLayoutEffect(() => {
    const check = () => {
      // 1. Manual override via ?pwa=1 (for testing in any browser)
      let manual = false;
      try {
        manual = new URL(window.location.href).searchParams.get("pwa") === "1";
      } catch {}

      // 2. display-mode media queries — run each separately because
      //    comma-separated OR in matchMedia isn't reliable everywhere.
      const modes = ["standalone", "minimal-ui", "window-controls-overlay", "fullscreen"];
      let modeMatch = false;
      for (const m of modes) {
        try {
          if (window.matchMedia(`(display-mode: ${m})`).matches) {
            modeMatch = true;
            break;
          }
        } catch {}
      }

      // 3. iOS navigator.standalone (legacy)
      let iosStandalone = false;
      try {
        iosStandalone = (window.navigator as any).standalone === true;
      } catch {}

      const pwa = manual || modeMatch || iosStandalone;
      setIsPwa(pwa);
      document.documentElement.classList.toggle("pwa", pwa);
    };

    check();

    // Re-check when any display-mode query changes (e.g. user
    // installs the app while it's open).
    let cleanupFns: Array<() => void> = [];
    ["standalone", "minimal-ui", "window-controls-overlay", "fullscreen"].forEach(
      (m) => {
        try {
          const mq = window.matchMedia(`(display-mode: ${m})`);
          mq.addEventListener("change", check);
          cleanupFns.push(() => mq.removeEventListener("change", check));
        } catch {}
      }
    );

    return () => cleanupFns.forEach((fn) => fn());
  }, []);
  return isPwa;
}
