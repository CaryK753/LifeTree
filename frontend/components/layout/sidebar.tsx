"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import {
  Compass,
  Network,
  MessageSquare,
  GitBranch,
  ShieldCheck,
  Upload,
  Home,
  Settings,
  Plug,
  User,
  Bell,
  Gauge,
  ShieldAlert,
  LogOut,
  Sun,
  Moon,
  Monitor,
  PanelLeftClose,
  PanelLeftOpen,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";
import { useAuth, useAuthConfig, useNotifications } from "@/lib/hooks";
import { useSidebarCollapsed } from "@/lib/use-sidebar-collapsed";
import { useSidebarDrawerMode } from "@/lib/use-sidebar-drawer-mode";
import { usePwaSidebarDrawer } from "@/lib/use-pwa-sidebar-drawer";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";

type NavItem = {
  href: string;
  labelKey: string;
  icon: typeof Home;
};

const NAV: NavItem[] = [
  { href: "/", labelKey: "nav.overview", icon: Home },
  { href: "/dashboard", labelKey: "nav.dashboard", icon: Gauge },
  { href: "/goals", labelKey: "nav.goals", icon: Compass },
  { href: "/graph", labelKey: "nav.graph", icon: Network },
  { href: "/chat", labelKey: "nav.chat", icon: MessageSquare },
  { href: "/scenarios", labelKey: "nav.scenarios", icon: GitBranch },
  { href: "/sources", labelKey: "nav.sources", icon: ShieldCheck },
  { href: "/notifications", labelKey: "nav.notifications", icon: Bell },
  { href: "/ingest", labelKey: "nav.ingest", icon: Upload },
  { href: "/plugins", labelKey: "nav.plugins", icon: Plug },
];

// Admin-only nav items. Rendered only when the current user has role=admin.
const ADMIN_NAV: NavItem[] = [
  { href: "/admin", labelKey: "nav.admin", icon: ShieldAlert },
];

export function Sidebar() {
  const pathname = usePathname();
  const { collapsed, toggle: toggleCollapsed } = useSidebarCollapsed();
  const drawerMode = useSidebarDrawerMode();
  const { open: drawerOpen, setOpen: setDrawerOpen } = usePwaSidebarDrawer();

  // Close the drawer whenever route changes.
  useEffect(() => {
    setDrawerOpen(false);
  }, [pathname, setDrawerOpen]);

  // Lock body scroll while the drawer is open.
  useEffect(() => {
    if (!drawerMode) return;
    if (drawerOpen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [drawerOpen, drawerMode]);

  // Close the drawer on Escape.
  useEffect(() => {
    if (!drawerMode || !drawerOpen) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setDrawerOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawerOpen, drawerMode, setDrawerOpen]);

  // ---------- Drawer mode (PWA or narrow viewport) ----------
  // The sidebar is hidden by default and opened as a slide-in drawer
  // when the user clicks the ``SidebarToggleButton`` in any page's
  // heading. This maximizes content width on phone screens and gives
  // installed PWAs a native-app feel.
  if (drawerMode) {
    return (
      <>
        {/* Backdrop */}
        <div
          className={cn(
            "fixed inset-0 z-40 bg-black/60 backdrop-blur-sm transition-opacity duration-200",
            drawerOpen
              ? "opacity-100 pointer-events-auto"
              : "opacity-0 pointer-events-none"
          )}
          onClick={() => setDrawerOpen(false)}
          aria-hidden="true"
        />

        {/* Drawer */}
        <aside
          className={cn(
            "fixed inset-y-0 left-0 z-50 w-72 max-w-[85vw]",
            "flex flex-col bg-[#0d1015] border-r border-white/5 shadow-2xl",
            "transition-transform duration-300 ease-out",
            "safe-top safe-bottom",
            drawerOpen ? "translate-x-0" : "-translate-x-full"
          )}
          data-drawer-open={drawerOpen}
        >
          <SidebarContent
            collapsed={false}
            pathname={pathname}
            onClose={drawerOpen ? () => setDrawerOpen(false) : undefined}
          />
        </aside>
      </>
    );
  }

  // ---------- Non-PWA mode: persistent rail ----------
  // The rail is always visible; the collapse toggle in the top-right of
  // the brand row switches between wide (w-60) and compact (w-16).
  // The ``sidebar-rail`` class is a CSS hook so ``html.pwa .sidebar-rail``
  // can hide the rail as a fallback even if the React branch hasn't
  // switched to the drawer yet.
  const width = collapsed ? "w-16" : "w-60";
  return (
    <aside
      className={cn(
        "sidebar-rail shrink-0 border-r border-white/5 bg-surface/40 backdrop-blur-sm",
        "flex flex-col transition-[width] duration-200 ease-out",
        width
      )}
      data-collapsed={collapsed}
    >
      <SidebarContent
        collapsed={collapsed}
        pathname={pathname}
        onToggle={toggleCollapsed}
      />
    </aside>
  );
}

// ---------- Shared content ----------

function SidebarContent({
  collapsed,
  pathname,
  onClose,
  onToggle,
}: {
  collapsed: boolean;
  pathname: string;
  onClose?: () => void;
  onToggle?: () => void;
}) {
  const t = useT();
  const compact = collapsed;
  const { user, isAuthenticated, isAdmin } = useAuth();
  // In single mode, the default-user fallback is active — treat the user
  // as having admin access so the admin nav (admin page, etc.) is visible
  // even without logging in. The backend's _require_admin_in_multi_user
  // check is also skipped in single mode, so this is consistent.
  const { data: authConfig } = useAuthConfig();
  const useMode = authConfig?.use_mode ?? (authConfig?.multi_user_mode ? "multi" : "single");
  const singleMode = useMode === "single";
  const showAdminNav = (isAuthenticated && isAdmin) || singleMode;

  // Unread notification count — used to badge the Bell icon.
  // refreshInterval keeps the badge fresh without manual reloads. The hook is
  // shared via SWR cache, so the notifications page and this badge stay in
  // sync after mark-read actions.
  const { data: notifications } = useNotifications();
  const unreadCount = (notifications ?? []).filter(
    (n: any) => !n.read_at
  ).length;

  return (
    <>
      {/* Brand row — logo links to home.
          - Drawer mode (onClose set): close button on the right.
          - Persistent rail (onToggle set): collapse/expand button on the
            right. When collapsed, only the logo + toggle are shown. */}
      <div
        className={cn(
          "flex h-16 items-center border-b border-white/5",
          compact && !onClose && !onToggle ? "justify-center px-2" : "gap-2 px-3"
        )}
      >
        <Link
          href="/"
          className={cn(
            "flex items-center min-w-0",
            compact && !onClose ? "justify-center" : "gap-2 flex-1"
          )}
          title="LifeTree"
        >
          <img
            src="/media/logo.png"
            alt="LifeTree"
            className="h-8 w-8 shrink-0 rounded-md object-cover"
          />
          {!compact && (
            <div className="leading-tight min-w-0">
              <div className="text-sm font-semibold text-zinc-100 truncate">
                LifeTree
              </div>
            </div>
          )}
        </Link>
        {onClose && (
          <button
            onClick={onClose}
            className="shrink-0 flex items-center justify-center rounded-md text-zinc-500 hover:bg-white/5 hover:text-zinc-200 h-8 w-8"
            aria-label="Close sidebar"
          >
            <X className="h-4 w-4" />
          </button>
        )}
        {onToggle && (
          <button
            onClick={onToggle}
            className="shrink-0 flex items-center justify-center rounded-md text-zinc-500 hover:bg-white/5 hover:text-zinc-200 h-8 w-8"
            aria-label={compact ? "Expand sidebar" : "Collapse sidebar"}
            title={compact ? t("sidebar.expand") : t("sidebar.collapse")}
          >
            {compact ? (
              <PanelLeftOpen className="h-4 w-4" />
            ) : (
              <PanelLeftClose className="h-4 w-4" />
            )}
          </button>
        )}
      </div>

      {/* Primary nav */}
      <nav className="px-2 py-2 space-y-0.5 flex-1 overflow-y-auto">
        {NAV.map((item) => {
          const Icon = item.icon;
          const label = t(item.labelKey);
          const active =
            pathname === item.href ||
            (item.href !== "/" && pathname.startsWith(item.href));
          // Show unread badge only on the notifications nav item.
          const showBadge = item.href === "/notifications" && unreadCount > 0;
          return (
            <Link
              key={item.href}
              href={item.href}
              title={compact ? label : undefined}
              className={cn(
                "flex items-center rounded-md text-sm transition-colors group relative",
                compact
                  ? "justify-center h-9 w-9 mx-auto"
                  : "gap-2.5 px-3 py-2",
                active
                  ? "bg-brand-500/10 text-brand-700 dark:text-brand-300 border border-brand-500/20"
                  : "text-zinc-500 dark:text-zinc-400 hover:bg-black/5 dark:hover:bg-white/5 hover:text-zinc-900 dark:hover:text-zinc-100 border border-transparent"
              )}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {!compact && <span className="truncate">{label}</span>}
              {compact && active && (
                <span className="absolute left-0 top-1/2 -translate-y-1/2 h-5 w-0.5 rounded-r bg-brand-500 dark:bg-brand-400" />
              )}
              {/* Unread badge.
                  - Minibar: small dot at top-right corner of the icon button.
                  - Expanded: pill with count, pinned to the right edge of the row.
                  - ring color must match the sidebar surface in both themes;
                    using rgb(var(--surface)) keeps it consistent. */}
              {showBadge && compact && (
                <span className="absolute top-1 right-1 h-2 w-2 rounded-full bg-red-500 ring-2 ring-[rgb(var(--surface))]" />
              )}
              {showBadge && !compact && (
                <span className="ml-auto inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full bg-red-500/90 text-white text-[10px] font-medium leading-none">
                  {unreadCount > 99 ? "99+" : unreadCount}
                </span>
              )}
            </Link>
          );
        })}
      </nav>

      {/* Admin-only nav — rendered when the user is an admin OR in single
          mode (where the default-user fallback has admin rights and the
          backend skips the admin check). Visual treatment: red accent so
          it's visually distinct from regular user nav. */}
      {showAdminNav && (
        <div className="px-2 py-2 border-t border-white/5 space-y-0.5">
          {ADMIN_NAV.map((item) => {
            const Icon = item.icon;
            const label = t(item.labelKey);
            const active = pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                title={compact ? label : undefined}
                className={cn(
                  "flex items-center rounded-md text-sm transition-colors",
                  compact
                    ? "justify-center h-9 w-9 mx-auto"
                    : "gap-2.5 px-3 py-2",
                  active
                    ? "bg-amber-500/10 text-amber-700 dark:text-amber-300 border border-amber-500/20"
                    : "text-zinc-500 dark:text-zinc-400 hover:bg-black/5 dark:hover:bg-white/5 hover:text-zinc-900 dark:hover:text-zinc-100 border border-transparent"
                )}
              >
                <Icon className="h-4 w-4 shrink-0" />
                {!compact && <span className="truncate">{label}</span>}
              </Link>
            );
          })}
        </div>
      )}

      {/* User chip / avatar — opens a dropdown menu with:
          - 我的资料 (My profile) → /profile
          - 设置 (Settings) → /settings
          - 主题 (Theme) — 3-segment slider (light / dark / system)
          - 登出 (Sign out)

          Expanded mode: avatar + display_name + email + chevron.
          Compact/minibar mode: just the avatar (or initial fallback).
          Clicking anywhere on the chip/avatar toggles the dropdown.
          The dropdown is positioned above the chip (bottom-aligned)
          so it doesn't get clipped by the sidebar's bottom edge. */}
      <UserChip compact={compact} pathname={pathname} t={t} />
    </>
  );
}

// ---------- User chip + dropdown ----------

/**
 * UserChip — bottom-of-sidebar trigger that opens a dropdown menu.
 *
 * Behaviour:
 *   - Click the trigger toggles the menu (open/close).
 *   - Click outside the menu (on blank space) closes it.
 *   - ESC closes the menu.
 *   - Picking a menu item (profile / settings / theme segment / logout)
 *     closes the menu.
 *
 * Animation:
 *   - The dropdown is always mounted (after first open) so the close
 *     animation can play. We toggle visibility with a ``visible``
 *     state that lags behind ``open`` by one frame; the CSS transition
 *     on ``opacity`` + ``scale`` + ``translate`` plays both ways.
 *
 * Positioning:
 *   - In expanded sidebar mode the menu is anchored to the sidebar
 *     (``absolute``) so it slides out with the sidebar.
 *   - In compact/minibar mode the sidebar is very narrow (≈48px) and
 *     the menu would overflow the window's left edge if we centered it.
 *     We instead use ``fixed`` positioning anchored to the trigger
 *     button's bounding rect, clamped to the viewport so the menu
 *     always stays on screen.
 */
function UserChip({
  compact,
  pathname,
  t,
}: {
  compact: boolean;
  pathname: string;
  t: (key: string, vars?: Record<string, string | number>) => string;
}) {
  const { user, isAuthenticated, isAdmin, logout } = useAuth();
  // In single-user mode, the app is usable without login (default-user
  // fallback on the backend). We still render the chip so the user can
  // access Settings / Profile / Theme from the sidebar; the Sign-out item
  // is hidden when not actually authenticated.
  const { data: authConfig } = useAuthConfig();
  const useMode = authConfig?.use_mode ?? (authConfig?.multi_user_mode ? "multi" : "single");
  const singleMode = useMode === "single";
  // Render the chip if: (a) user is logged in, OR (b) single mode where
  // anonymous access is allowed.
  const showChip = isAuthenticated || singleMode;
  const [open, setOpen] = useState(false);
  // ``visible`` is true while the dropdown is shown (open or animating
  // out). It stays true for one tick after ``open`` flips to false so
  // the close animation can complete.
  const [visible, setVisible] = useState(false);
  // Logout confirmation dialog state. Triggered by the "退出登录" menu
  // item — we never log out immediately so the user can cancel.
  const [logoutConfirmOpen, setLogoutConfirmOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  // Wraps both the trigger button and the dropdown menu so outside-click
  // detection can use a single ``contains`` check (the menu is positioned
  // ``fixed`` in compact mode but still lives inside this DOM subtree).
  const containerRef = useRef<HTMLDivElement>(null);

  // ESC + outside-click close the menu.
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    function onMouseDown(e: MouseEvent) {
      const container = containerRef.current;
      if (!container) return;
      const target = e.target as Node;
      // Container covers the trigger button. The dropdown menu itself
      // is rendered via portal into ``document.body`` (see DropdownMenu),
      // so it's no longer a DOM descendant of ``container`` — check it
      // via the ``data-user-menu`` attribute so clicks inside the menu
      // don't get treated as "outside" clicks.
      if (container.contains(target)) return;
      if (
        target instanceof Element &&
        target.closest("[data-user-menu='true']")
      ) {
        return;
      }
      setOpen(false);
    }
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onMouseDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onMouseDown);
    };
  }, [open]);

  // Mount the dropdown on first open; keep it mounted so close
  // animation can play. After close animation finishes, unmount.
  useEffect(() => {
    if (open) {
      setVisible(true);
      return;
    }
    if (!visible) return;
    const id = window.setTimeout(() => setVisible(false), 180);
    return () => window.clearTimeout(id);
  }, [open, visible]);

  // Close dropdown on route change (after navigation completes).
  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  if (!showChip) {
    return null;
  }

  // Fallback display for anonymous single-mode users.
  const displayName = user?.display_name ?? t("auth.defaultUser");
  const displayEmail = user?.email ?? "";

  const avatar = (
    <div
      className={cn(
        "shrink-0 rounded-full bg-gradient-to-br from-brand-400 to-brand-600 flex items-center justify-center text-white font-semibold overflow-hidden",
        "h-8 w-8 text-xs"
      )}
    >
      {user?.avatar_url ? (
        <img src={user.avatar_url} alt="" className="h-full w-full object-cover" />
      ) : (
        displayName?.[0]?.toUpperCase() || "?"
      )}
    </div>
  );

  return (
    <div ref={containerRef} className="relative px-2 py-2 border-t border-white/5">
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        title={compact ? displayName : undefined}
        aria-haspopup="menu"
        aria-expanded={open}
        className={cn(
          "flex items-center w-full rounded-md transition-colors text-left",
          compact
            ? "justify-center h-9 w-9 mx-auto"
            : "gap-2 px-2 py-1.5 bg-black/[0.03] dark:bg-white/[0.03] hover:bg-black/[0.06] dark:hover:bg-white/[0.06]"
        )}
      >
        {avatar}
        {!compact && (
          <>
            <div className="flex-1 min-w-0 leading-tight">
              <div className="text-xs font-medium text-zinc-900 dark:text-zinc-100 truncate flex items-center gap-1">
                {displayName}
                {((isAuthenticated && isAdmin) || singleMode) && (
                  <span className="text-[9px] px-1 py-0.5 rounded bg-amber-500/15 text-amber-700 dark:text-amber-300 font-medium uppercase tracking-wide">
                    {t("auth.adminBadge")}
                  </span>
                )}
              </div>
              {displayEmail && (
                <div className="text-[10px] text-zinc-500 truncate">
                  {displayEmail}
                </div>
              )}
            </div>
            <svg
              viewBox="0 0 12 12"
              className={cn(
                "h-3 w-3 text-zinc-500 transition-transform shrink-0",
                open && "rotate-180"
              )}
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
            >
              <path d="M3 4.5L6 7.5L9 4.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </>
        )}
      </button>

      {/* Dropdown menu.
          Always mounted while ``visible`` so the close animation plays.
          ``open`` controls the actual animation state via opacity/scale. */}
      {visible && (
        <DropdownMenu
          open={open}
          compact={compact}
          triggerRef={triggerRef}
          pathname={pathname}
          t={t}
          isAuthenticated={isAuthenticated}
          singleMode={singleMode}
          onClose={() => setOpen(false)}
          onLogout={() => {
            // Close the dropdown first, then surface the confirmation
            // dialog. We don't log out here — the user must confirm.
            setOpen(false);
            setLogoutConfirmOpen(true);
          }}
        />
      )}

      {/* Logout confirmation dialog — uses LifeTree's native ConfirmDialog
          (Radix-based) instead of the browser's ``window.confirm`` so the
          UX matches the rest of the app (overlay, animation, focus trap). */}
      <ConfirmDialog
        open={logoutConfirmOpen}
        onOpenChange={setLogoutConfirmOpen}
        title={t("auth.logoutConfirmTitle")}
        description={t("auth.logoutConfirmDesc")}
        confirmLabel={t("auth.logoutConfirmOk")}
        cancelLabel={t("auth.logoutConfirmCancel")}
        variant="danger"
        onConfirm={() => {
          setLogoutConfirmOpen(false);
          logout();
        }}
      />
    </div>
  );
}

/**
 * DropdownMenu — the actual floating menu.
 *
 * Positioning strategy:
 *   - Expanded sidebar: the menu appears directly ABOVE the avatar,
 *     left-aligned with the trigger button so it visually pops out of
 *     the user chip area. Width (220px) is close to the sidebar's
 *     content width so the menu sits flush inside the sidebar column.
 *   - Compact/minibar sidebar: ``fixed`` positioning computed from the
 *     trigger button's ``getBoundingClientRect()``. The menu appears
 *     immediately to the RIGHT of the avatar (``left = r.right + 8``)
 *     with its bottom edge 4px above the avatar's TOP — so the menu
 *     sits visually above the avatar without overlapping it. If the
 *     menu is too tall and would overflow the viewport top, it shifts
 *     down (clamped to ``pad`` from the top) so it stays on screen.
 */
function DropdownMenu({
  open,
  compact,
  triggerRef,
  pathname,
  t,
  isAuthenticated,
  singleMode,
  onClose,
  onLogout,
}: {
  open: boolean;
  compact: boolean;
  triggerRef: React.RefObject<HTMLButtonElement | null>;
  pathname: string;
  t: (key: string, vars?: Record<string, string | number>) => string;
  isAuthenticated: boolean;
  singleMode: boolean;
  onClose: () => void;
  onLogout: () => void;
}) {
  const menuRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ left: number; bottom: number } | null>(null);

  // Compute the trigger's screen position and place the menu.
  // Both compact and expanded modes use ``position: fixed`` so the menu
  // escapes any ``overflow`` clipping inside the sidebar (the nav
  // container has ``overflow-y-auto`` which would otherwise clip an
  // ``absolute``-positioned menu).
  useLayoutEffect(() => {
    function compute() {
      const trigger = triggerRef.current;
      if (!trigger) return;
      const r = trigger.getBoundingClientRect();
      const menuW = 220; // matches min-w-[220px] below
      const menuH = menuRef.current?.offsetHeight ?? 240; // measure if mounted
      const vertGap = 2; // vertical gap above trigger's top
      const pad = 8; // viewport edge padding
      let left: number;
      if (compact) {
        // Compact/minibar: place the menu flush to the RIGHT of the
        // avatar (sidebar is too narrow to host the menu above).
        const gap = 2;
        left = r.right + gap;
        // If it overflows the right edge, flip to the left side of the avatar.
        if (left + menuW > window.innerWidth - pad) {
          left = r.left - menuW - gap;
        }
      } else {
        // Expanded: place the menu directly ABOVE the avatar, left-aligned
        // with the trigger button so it visually pops out of the user chip.
        left = r.left;
      }
      // Clamp inside viewport.
      left = Math.max(pad, Math.min(left, window.innerWidth - menuW - pad));
      // Bottom-align the menu to (trigger's top + vertGap) so the menu
      // sits just above the trigger without overlapping it.
      const desiredBottom = window.innerHeight - r.top + vertGap;
      // If the menu is too tall and would overflow the viewport top,
      // clamp it so its top edge stays at least ``pad`` from the top.
      const maxBottom = Math.max(pad, window.innerHeight - menuH - pad);
      const bottom = Math.min(desiredBottom, maxBottom);
      setPos({ left, bottom });
    }
    compute();
    window.addEventListener("resize", compute);
    window.addEventListener("scroll", compute, true);
    return () => {
      window.removeEventListener("resize", compute);
      window.removeEventListener("scroll", compute, true);
    };
  }, [triggerRef, open, compact]);

  // Render via portal into ``document.body`` so the menu escapes the
  // parent ``<aside>`` stacking context created by ``backdrop-blur-sm``.
  // Without the portal, the menu's ``z-index: 100`` is scoped inside the
  // aside and the adjacent ``<main>`` content (which forms its own
  // stacking context) renders on top, making the menu items unclickable.
  if (typeof document === "undefined") return null;
  return createPortal(
    <div
      ref={menuRef}
      role="menu"
      data-user-menu="true"
      style={{
        position: "fixed",
        // On first render ``pos`` is null (useLayoutEffect hasn't
        // run yet). Park the menu off-screen so it doesn't flash
        // in the DOM-flow position before the first compute.
        left: pos?.left ?? -9999,
        bottom: pos?.bottom ?? 0,
        width: 220,
        visibility: pos ? "visible" : "hidden",
        zIndex: 100,
      }}
      className={cn(
        "min-w-[220px] rounded-lg border border-black/10 dark:border-white/10 bg-white dark:bg-zinc-950 shadow-xl shadow-black/20 py-1 origin-bottom",
        // Only animate opacity + transform (scale/translate), NOT left/bottom.
        // Animating position properties causes the menu to "drift" from
        // its DOM-flow position to the computed fixed position on open.
        "transition-[opacity,transform] duration-150 ease-out will-change-transform",
        compact ? "origin-bottom-left" : "origin-bottom-left",
        open
          ? "opacity-100 scale-100 translate-y-0"
          : "opacity-0 scale-95 translate-y-1 pointer-events-none"
      )}
    >
      {/* Menu items — no user/email header by request.
          Profile is shown in single mode too (the default-user fallback
          is active, so the user has a profile to view even without login).
          This lets the user see their user ID (needed for admin promotion
          via LIFETREE_ADMIN_USER_IDS) and access profile-related features. */}
      {(isAuthenticated || singleMode) && (
        <MenuLink
          href="/profile"
          icon={User}
          label={t("nav.profile")}
          active={pathname.startsWith("/profile")}
          onClick={onClose}
        />
      )}
      <MenuLink
        href="/settings"
        icon={Settings}
        label={t("nav.settings")}
        active={pathname.startsWith("/settings")}
        onClick={onClose}
      />

      {/* Theme slider — 3 segments: light / dark / system.
          Clicking a theme option must NOT close the dropdown (user can
          preview multiple themes), so we don't pass ``onClose`` here. */}
      <ThemeSliderRow />

      {isAuthenticated && (
        <>
          <div className="my-1 border-t border-black/5 dark:border-white/5" />

          <button
            type="button"
            role="menuitem"
            onClick={onLogout}
            className="flex items-center gap-2.5 w-full px-3 py-1.5 text-xs text-zinc-700 dark:text-zinc-300 hover:bg-red-500/10 hover:text-red-600 dark:hover:text-red-400 transition-colors"
          >
            <LogOut className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">{t("auth.logout")}</span>
          </button>
        </>
      )}
    </div>,
    document.body
  );
}

function MenuLink({
  href,
  icon: Icon,
  label,
  active,
  onClick,
}: {
  href: string;
  icon: React.ElementType;
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <Link
      href={href}
      role="menuitem"
      onClick={onClick}
      className={cn(
        "flex items-center gap-2.5 w-full px-3 py-1.5 text-xs transition-colors",
        active
          ? "bg-brand-500/10 text-brand-700 dark:text-brand-300"
          : "text-zinc-700 dark:text-zinc-300 hover:bg-black/5 dark:hover:bg-white/5 hover:text-zinc-900 dark:hover:text-zinc-100"
      )}
    >
      <Icon className="h-3.5 w-3.5 shrink-0" />
      <span className="truncate">{label}</span>
    </Link>
  );
}

/**
 * ThemeSliderRow: 3-segment inline switch (light / dark / system).
 *
 * Uses next-themes' ``setTheme`` directly. Mounted-gate avoids hydration
 * mismatch (next-themes only knows the theme client-side).
 *
 * Note: clicking a theme option does NOT close the parent dropdown —
 * the user may want to preview multiple themes before settling. The
 * dropdown is closed only by ESC, outside-click, or picking a nav item.
 */
function ThemeSliderRow() {
  const t = useT();
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const options: { value: "light" | "dark" | "system"; icon: React.ElementType; labelKey: string }[] = [
    { value: "light", icon: Sun, labelKey: "theme.light" },
    { value: "dark", icon: Moon, labelKey: "theme.dark" },
    { value: "system", icon: Monitor, labelKey: "theme.system" },
  ];
  const current = (theme as "light" | "dark" | "system") ?? "dark";

  return (
    <div className="px-3 py-2">
      <div className="text-[10px] text-zinc-500 mb-1.5">{t("theme.label")}</div>
      <div
        role="radiogroup"
        className="grid grid-cols-3 gap-1 rounded-md bg-black/[0.04] dark:bg-white/[0.04] p-0.5"
      >
        {options.map((opt) => {
          const Icon = opt.icon;
          const isActive = mounted && current === opt.value;
          return (
            <button
              key={opt.value}
              type="button"
              role="radio"
              aria-checked={isActive}
              onClick={() => setTheme(opt.value)}
              title={t(opt.labelKey)}
              className={cn(
                "flex items-center justify-center gap-1 px-1.5 py-1 rounded text-[10px] transition-colors",
                isActive
                  ? "bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 shadow-sm"
                  : "text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100"
              )}
            >
              <Icon className="h-3 w-3" />
              <span className="truncate">{t(opt.labelKey)}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
