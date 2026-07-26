"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Compass,
  Network,
  MessageSquare,
  GitBranch,
  ShieldCheck,
  Upload,
  Home,
  Settings,
  PanelLeftClose,
  PanelLeftOpen,
  Plug,
  User,
  Bell,
  Gauge,
  Menu,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";
import { useNotifications } from "@/lib/hooks";
import { ThemeToggle } from "@/components/theme/theme-toggle";

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
  { href: "/profile", labelKey: "nav.profile", icon: User },
];

const SECONDARY_NAV: NavItem[] = [
  { href: "/settings", labelKey: "nav.settings", icon: Settings },
];

const COLLAPSE_KEY = "lifetree.sidebar.collapsed";
const MOBILE_BREAKPOINT = 1024; // lg

export function Sidebar() {
  const pathname = usePathname();
  const t = useT();
  const [collapsed, setCollapsed] = useState(false);
  const [mounted, setMounted] = useState(false);
  // Mobile drawer state — only relevant below lg breakpoint.
  const [mobileOpen, setMobileOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(false);

  // Restore desktop collapse preference.
  useEffect(() => {
    const stored = localStorage.getItem(COLLAPSE_KEY);
    if (stored === "1") setCollapsed(true);
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!mounted) return;
    localStorage.setItem(COLLAPSE_KEY, collapsed ? "1" : "0");
  }, [collapsed, mounted]);

  // Track viewport size to decide drawer vs. rail layout.
  useEffect(() => {
    const update = () =>
      setIsMobile(window.innerWidth < MOBILE_BREAKPOINT);
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  // Close mobile drawer whenever route changes.
  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  // Lock body scroll when mobile drawer is open.
  useEffect(() => {
    if (!isMobile) return;
    if (mobileOpen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [mobileOpen, isMobile]);

  // Close the mobile drawer on Escape — matches the behavior of modal
  // dialogs (Radix Dialog already does this; the mobile drawer is a
  // hand-rolled overlay so we add it manually).
  useEffect(() => {
    if (!mobileOpen) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setMobileOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mobileOpen]);

  const width = collapsed ? "w-16" : "w-60";

  // ---------- Mobile: top bar + drawer ----------
  if (mounted && isMobile) {
    return (
      <>
        {/* Top bar with hamburger — only visible on mobile.
            h-14 (56px) matches the pt-14 padding on <main> in layout.tsx
            so the bar never overlaps page content. Theme-aware classes
            keep the bar legible in both light and dark modes. */}
        <div className="lg:hidden fixed top-0 left-0 right-0 h-14 z-30 flex items-center gap-2 px-3 border-b border-black/5 dark:border-white/5 bg-white/95 dark:bg-[#0b0d12]/95 backdrop-blur-md">
          <button
            onClick={() => setMobileOpen(true)}
            className="h-9 w-9 flex items-center justify-center rounded-md text-zinc-600 dark:text-zinc-300 hover:bg-black/5 dark:hover:bg-white/5"
            aria-label={t("sidebar.openMenu")}
          >
            <Menu className="h-5 w-5" />
          </button>
          <Link href="/" className="flex items-center gap-2 min-w-0">
            <img
              src="/media/logo.png"
              alt="LifeTree"
              className="h-7 w-7 shrink-0 rounded-md object-cover"
            />
            <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-100 truncate">
              LifeTree
            </span>
          </Link>
        </div>

        {/* Drawer backdrop */}
        <div
          className={cn(
            "lg:hidden fixed inset-0 z-40 bg-black/60 backdrop-blur-sm transition-opacity duration-200",
            mobileOpen
              ? "opacity-100 pointer-events-auto"
              : "opacity-0 pointer-events-none"
          )}
          onClick={() => setMobileOpen(false)}
          aria-hidden="true"
        />

        {/* Drawer */}
        <aside
          className={cn(
            "lg:hidden fixed inset-y-0 left-0 z-50 w-72 max-w-[85vw]",
            "flex flex-col bg-[#0d1015] border-r border-white/5 shadow-2xl",
            "transition-transform duration-300 ease-out",
            mobileOpen ? "translate-x-0" : "-translate-x-full"
          )}
          data-mobile-open={mobileOpen}
        >
          <SidebarContent
            collapsed={false}
            setCollapsed={() => setMobileOpen(false)}
            pathname={pathname}
            showCloseButton
            onClose={() => setMobileOpen(false)}
          />
        </aside>
      </>
    );
  }

  // ---------- Desktop: persistent rail ----------
  return (
    <aside
      className={cn(
        "shrink-0 border-r border-white/5 bg-surface/40 backdrop-blur-sm",
        "hidden lg:flex flex-col transition-[width] duration-200 ease-out",
        width
      )}
      data-collapsed={collapsed}
    >
      <SidebarContent
        collapsed={collapsed}
        setCollapsed={setCollapsed}
        pathname={pathname}
      />
    </aside>
  );
}

// ---------- Shared content ----------

function SidebarContent({
  collapsed,
  setCollapsed,
  pathname,
  showCloseButton = false,
  onClose,
}: {
  collapsed: boolean;
  setCollapsed: (v: boolean | ((prev: boolean) => boolean)) => void;
  pathname: string;
  showCloseButton?: boolean;
  onClose?: () => void;
}) {
  const t = useT();
  const compact = collapsed && !showCloseButton;

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
      {/* Brand row */}
      <div
        className={cn(
          "flex h-16 items-center border-b border-white/5",
          compact ? "justify-center px-2" : "gap-2 px-3"
        )}
      >
        {showCloseButton ? (
          <>
            <Link
              href="/"
              className="flex items-center gap-2 min-w-0 flex-1"
              title="LifeTree"
            >
              <img
                src="/media/logo.png"
                alt="LifeTree"
                className="h-8 w-8 shrink-0 rounded-md object-cover"
              />
              <div className="leading-tight min-w-0">
                <div className="text-sm font-semibold text-zinc-100 truncate">
                  LifeTree
                </div>
              </div>
            </Link>
            <button
              onClick={onClose}
              className="shrink-0 flex items-center justify-center rounded-md text-zinc-500 hover:bg-white/5 hover:text-zinc-200 h-8 w-8"
              aria-label={t("sidebar.closeMenu")}
            >
              <X className="h-4 w-4" />
            </button>
          </>
        ) : collapsed ? (
          <button
            onClick={() => setCollapsed(false)}
            className="group relative flex items-center justify-center h-9 w-9 rounded-md transition-all hover:bg-brand-500/15 hover:ring-1 hover:ring-brand-500/30"
            title={t("sidebar.expand")}
            aria-label={t("sidebar.expand")}
          >
            <img
              src="/media/logo.png"
              alt="LifeTree"
              className="h-8 w-8 rounded-md object-cover transition-opacity group-hover:opacity-25"
            />
            <PanelLeftOpen className="absolute h-4 w-4 text-brand-600 dark:text-brand-300 opacity-0 transition-opacity group-hover:opacity-100" />
          </button>
        ) : (
          <>
            <Link
              href="/"
              className="flex items-center gap-2 min-w-0 flex-1"
              title="LifeTree"
            >
              <img
                src="/media/logo.png"
                alt="LifeTree"
                className="h-8 w-8 shrink-0 rounded-md object-cover"
              />
              <div className="leading-tight min-w-0">
                <div className="text-sm font-semibold text-zinc-100 truncate">
                  LifeTree
                </div>
              </div>
            </Link>
            <button
              onClick={() => setCollapsed(true)}
              className="shrink-0 flex items-center justify-center rounded-md text-zinc-500 hover:bg-white/5 hover:text-zinc-200 transition-colors h-8 w-8"
              title={t("sidebar.collapse")}
              aria-label={t("sidebar.collapse")}
            >
              <PanelLeftClose className="h-4 w-4" />
            </button>
          </>
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

      {/* Theme toggle — above Settings so it's quick to reach.
          Renders as a full-width row in expanded mode (icon + label)
          and a centered icon button in minibar mode. */}
      <div className="px-2 py-2 border-t border-white/5">
        <ThemeToggle compact={compact} />
      </div>

      {/* Secondary nav (Settings) */}
      <div className="px-2 py-2 border-t border-white/5 space-y-0.5">
        {SECONDARY_NAV.map((item) => {
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
                  ? "bg-brand-500/10 text-brand-700 dark:text-brand-300 border border-brand-500/20"
                  : "text-zinc-500 dark:text-zinc-400 hover:bg-black/5 dark:hover:bg-white/5 hover:text-zinc-900 dark:hover:text-zinc-100 border border-transparent"
              )}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {!compact && <span className="truncate">{label}</span>}
            </Link>
          );
        })}
      </div>
    </>
  );
}
