"use client";
import { Menu } from "lucide-react";
import { useSidebarDrawerMode } from "@/lib/use-sidebar-drawer-mode";
import { usePwaSidebarDrawer } from "@/lib/use-pwa-sidebar-drawer";
import { cn } from "@/lib/utils";

/**
 * SidebarToggleButton — rendered in each page's heading.
 *
 * Renders only when the sidebar is in drawer mode (PWA or narrow
 * viewport). Clicking it opens the sidebar as a slide-in drawer.
 *
 * In persistent-rail mode (wide non-PWA) this renders nothing — the
 * rail is always visible and has its own collapse toggle.
 */
export function SidebarToggleButton({ className }: { className?: string }) {
  const drawerMode = useSidebarDrawerMode();
  const { toggle: toggleDrawer } = usePwaSidebarDrawer();

  if (!drawerMode) return null;

  return (
    <button
      onClick={toggleDrawer}
      className={cn(
        "shrink-0 rounded-md p-1 text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100 transition-colors",
        className
      )}
      aria-label="Open sidebar"
    >
      <Menu className="h-5 w-5" />
    </button>
  );
}
