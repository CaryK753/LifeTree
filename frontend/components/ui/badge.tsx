import * as React from "react";
import { cn, riskPillClass } from "@/lib/utils";

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: "default" | "risk";
  riskLevel?: "low" | "medium" | "high" | null | undefined;
}

export function Badge({
  className,
  variant = "default",
  riskLevel,
  children,
  ...props
}: BadgeProps) {
  const cls =
    variant === "risk" && riskLevel
      ? riskPillClass(riskLevel)
      : "bg-black/[0.04] dark:bg-white/5 text-zinc-700 dark:text-zinc-300 border border-black/10 dark:border-white/10";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
        cls,
        className
      )}
      {...props}
    >
      {children}
    </span>
  );
}
