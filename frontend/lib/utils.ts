import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function riskColor(level?: string | null): string {
  if (level === "high") return "text-red-400";
  if (level === "medium") return "text-amber-400";
  if (level === "low") return "text-emerald-400";
  return "text-zinc-400";
}

export function riskPillClass(level?: string | null): string {
  if (level === "high") return "pill-risk-high";
  if (level === "medium") return "pill-risk-medium";
  if (level === "low") return "pill-risk-low";
  return "bg-white/5 text-zinc-300 border border-white/10";
}

export function formatDate(value?: string | Date | null): string {
  if (!value) return "—";
  const d = typeof value === "string" ? new Date(value) : value;
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("zh-CN", {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit",
  });
}

export function formatPercent(value?: number | null, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}
