"use client";
import { useLayoutEffect, useState } from "react";
import { useIsPwa } from "@/lib/use-pwa";

/**
 * Decide whether the sidebar should render as a drawer (vs. a
 * persistent rail).
 *
 * Returns ``true`` when EITHER condition holds:
 *   1. The app is running as an installed PWA (``display-mode`` matches
 *      ``standalone`` / ``minimal-ui`` / ``window-controls-overlay`` /
 *      ``fullscreen``, or iOS ``navigator.standalone``).
 *   2. The viewport width is below the ``lg`` breakpoint (1024px) —
 *      i.e. mobile / tablet / narrow desktop window. This gives mobile
 *      browsers the same drawer UX as PWA without needing the app to
 *      be installed.
 *
 * The check runs in ``useLayoutEffect`` so the drawer branch is chosen
 * before first paint (no flash of the rail).
 */
export function useSidebarDrawerMode(): boolean {
  const isPwa = useIsPwa();
  const [isMobile, setIsMobile] = useState(false);

  useLayoutEffect(() => {
    const LG = 1024; // Tailwind ``lg`` breakpoint
    const update = () => setIsMobile(window.innerWidth < LG);
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  return isPwa || isMobile;
}
