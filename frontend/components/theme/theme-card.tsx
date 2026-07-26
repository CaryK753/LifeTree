"use client";

/**
 * Theme selector card for the Settings page.
 *
 * Shows three explicit options (Light / Dark / System) as a segmented
 * control. The "System" option also displays the currently-resolved
 * effective theme (light or dark) so the user knows what they'll get.
 */

import { useEffect, useState } from "react";
import { useTheme } from "next-themes";
import { Sun, Moon, Monitor } from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";

type ThemeOption = "light" | "dark" | "system";

const OPTIONS: { value: ThemeOption; icon: React.ElementType }[] = [
  { value: "light", icon: Sun },
  { value: "dark", icon: Moon },
  { value: "system", icon: Monitor },
];

export function ThemeCard() {
  const t = useT();
  const { theme, setTheme, resolvedTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const current = (theme as ThemeOption) ?? "dark";

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("theme.title")}</CardTitle>
        <CardDescription>{t("theme.subtitle")}</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-3 gap-2">
          {OPTIONS.map(({ value, icon: Icon }) => {
            const active = mounted && current === value;
            return (
              <button
                key={value}
                type="button"
                onClick={() => setTheme(value)}
                className={cn(
                  "flex flex-col items-center gap-2 rounded-md border px-3 py-4 transition-colors",
                  active
                    ? "border-brand-500/40 bg-brand-500/10 text-brand-300"
                    : "border-white/5 bg-white/[0.02] text-zinc-400 hover:bg-white/[0.04] hover:text-zinc-100"
                )}
                aria-pressed={active}
              >
                <Icon className="h-5 w-5" />
                <span className="text-xs font-medium">
                  {t(`theme.${value}`)}
                </span>
              </button>
            );
          })}
        </div>

        {mounted && current === "system" && (
          <div className="mt-3 text-[11px] text-zinc-500 flex items-center gap-1.5">
            <span>{t("theme.effective")}:</span>
            <span className="text-zinc-300">
              {resolvedTheme === "dark" ? t("theme.dark") : t("theme.light")}
            </span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
