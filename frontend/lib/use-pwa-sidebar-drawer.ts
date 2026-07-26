"use client";
import { useCallback, useEffect, useState } from "react";

/**
 * Shared PWA sidebar drawer state.
 *
 * In PWA mode the sidebar is hidden by default and opened as a slide-in
 * drawer. This hook lets ``SidebarToggleButton`` (in each page heading)
 * open the drawer without prop-drilling or a context provider — state is
 * mirrored across all hook instances via a custom event.
 *
 * Non-PWA mode ignores this hook entirely (the persistent rail is used
 * there with collapse/expand via ``useSidebarCollapsed``).
 */

const EVENT = "pwa-sidebar-drawer-change";

export function usePwaSidebarDrawer() {
  const [open, setOpenState] = useState(false);

  useEffect(() => {
    const onCustom = () => {
      // Read the latest open state from a module-level singleton so all
      // hook instances stay in sync without lifting state up.
      setOpenState(currentOpen);
    };
    window.addEventListener(EVENT, onCustom);
    return () => window.removeEventListener(EVENT, onCustom);
  }, []);

  const setOpen = useCallback((v: boolean) => {
    currentOpen = v;
    window.dispatchEvent(new Event(EVENT));
  }, []);

  const toggle = useCallback(() => {
    setOpen(!currentOpen);
  }, [setOpen]);

  return { open, setOpen, toggle };
}

// Module-level singleton — the single source of truth shared by every
// hook instance. Avoids a React context while still keeping all
// ``usePwaSidebarDrawer`` callers in sync.
let currentOpen = false;
