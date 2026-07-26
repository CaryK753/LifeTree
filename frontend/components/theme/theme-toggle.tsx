"use client";

/**
 * Compact 3-state theme toggle for the sidebar.
 *
 * Cycles through light → dark → system → light.
 * Shows an icon for the *current effective* theme (sun for light,
 * moon for dark, monitor for system). The next-state label appears
 * as a tooltip.
 *
 * Layout:
 *   - compact (minibar): centered icon button, h-9 w-9 — matches the
 *     sidebar's secondary nav link sizing.
 *   - expanded: full-width row with icon + current-theme label, styled
 *     to blend in with the Settings link directly below it.
 *
 * Mounted-gate: next-themes returns undefined theme on the server, so
 * we render a placeholder until mounted to avoid hydration mismatch.
 */

import { useEffect, useState } from "react";
import { useTheme } from "next-themes";
import { Moon, Sun, Monitor } from "lucide-react";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";

type ThemeOption = "light" | "dark" | "system";

const ORDER: ThemeOption[] = ["light", "dark", "system"];

const ICONS: Record<ThemeOption, React.ElementType> = {
  light: Sun,
  dark: Moon,
  system: Monitor,
};

export function ThemeToggle({ compact = false }: { compact?: boolean }) {
  const t = useT();
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  // Avoid hydration mismatch — next-themes only knows the theme client-side.
  useEffect(() => setMounted(true), []);

  const current = (theme as ThemeOption) ?? "dark";
  const next = ORDER[(ORDER.indexOf(current) + 1) % ORDER.length];
  const Icon = mounted ? ICONS[current] : Moon;

  const labelKey =
    current === "light"
      ? "theme.light"
      : current === "dark"
        ? "theme.dark"
        : "theme.system";

  const switchLabel = mounted ? t(`theme.switchTo.${next}`) : "";

  return (
    <button
      type="button"
      onClick={() => setTheme(next)}
      title={switchLabel}
      aria-label={switchLabel}
      className={cn(
        "flex items-center rounded-md text-sm transition-colors border border-transparent",
        "text-zinc-400 hover:bg-white/5 hover:text-zinc-100",
        compact
          ? "justify-center h-9 w-9 mx-auto"
          : "gap-2.5 px-3 py-2 w-full"
      )}
    >
      <Icon className="h-4 w-4 shrink-0" />
      {!compact && mounted && (
        <span className="truncate text-xs">{t(labelKey)}</span>
      )}
    </button>
  );
}
