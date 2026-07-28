"use client";

import { useState, useMemo } from "react";
import { ShieldCheck, ShieldAlert, Eye, EyeOff, Lock } from "lucide-react";
import { maskPII, type MaskResult } from "@/lib/pii-mask";
import { useT } from "@/lib/i18n/provider";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

interface PIIPreviewPanelProps {
  text: string;
  className?: string;
  title?: string;
}

export function PIIPreviewPanel({ text, className, title }: PIIPreviewPanelProps) {
  const t = useT();
  const [showOriginal, setShowOriginal] = useState(false);

  const result: MaskResult = useMemo(() => maskPII(text), [text]);

  if (!text || text.trim().length === 0) {
    return null;
  }

  // Group detected PII counts by label
  const typeCounts = result.detectedPII.reduce<Record<string, number>>((acc, item) => {
    acc[item.label] = (acc[item.label] || 0) + 1;
    return acc;
  }, {});

  return (
    <div
      className={cn(
        "rounded-lg border p-4 space-y-3 transition-colors",
        result.hasPII
          ? "border-amber-500/30 bg-amber-500/5 dark:bg-amber-500/10"
          : "border-emerald-500/30 bg-emerald-500/5 dark:bg-emerald-500/10",
        className
      )}
    >
      {/* Header / Notice */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          {result.hasPII ? (
            <ShieldAlert className="h-5 w-5 text-amber-600 dark:text-amber-400 shrink-0" />
          ) : (
            <ShieldCheck className="h-5 w-5 text-emerald-600 dark:text-emerald-400 shrink-0" />
          )}
          <div>
            <div className="text-xs font-semibold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
              <span>{title || t("ingest.pii.title")}</span>
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-black/5 dark:bg-white/10 text-zinc-600 dark:text-zinc-400 font-normal">
                {t("ingest.pii.previewBadge")}
              </span>
            </div>
            <p className="text-xs text-zinc-600 dark:text-zinc-400 mt-0.5 leading-snug">
              {result.hasPII ? (
                <span className="text-amber-700 dark:text-amber-300 font-medium">
                  {t("ingest.pii.notice")}
                </span>
              ) : (
                <span className="text-emerald-700 dark:text-emerald-300">
                  {t("ingest.pii.noPII")}
                </span>
              )}
            </p>
          </div>
        </div>

        {result.hasPII && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 text-xs px-2 text-zinc-600 dark:text-zinc-300 hover:text-zinc-900 dark:hover:text-zinc-100"
            onClick={() => setShowOriginal(!showOriginal)}
          >
            {showOriginal ? (
              <>
                <EyeOff className="h-3.5 w-3.5 mr-1" />
                隐藏原文
              </>
            ) : (
              <>
                <Eye className="h-3.5 w-3.5 mr-1" />
                对比原文
              </>
            )}
          </Button>
        )}
      </div>

      {/* Detected PII Badges */}
      {result.hasPII && (
        <div className="flex flex-wrap gap-1.5 pt-1">
          {Object.entries(typeCounts).map(([label, count]) => (
            <span
              key={label}
              className="inline-flex items-center gap-1 text-[11px] font-medium px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-800 dark:text-amber-200 border border-amber-500/30"
            >
              <Lock className="h-3 w-3" />
              {label} × {count}
            </span>
          ))}
        </div>
      )}

      {/* Highlighted Preview Area */}
      {result.hasPII && (
        <div className="rounded border border-black/10 dark:border-white/10 bg-white/60 dark:bg-zinc-900/60 p-3 max-h-48 overflow-y-auto text-xs font-mono whitespace-pre-wrap break-all leading-relaxed">
          {showOriginal ? (
            <div className="text-zinc-700 dark:text-zinc-300">{text}</div>
          ) : (
            <div>
              {result.segments.map((seg, idx) => {
                if (seg.isPII) {
                  return (
                    <mark
                      key={idx}
                      className="bg-amber-400/30 text-amber-900 dark:bg-amber-400/40 dark:text-amber-100 rounded px-1 py-0.5 mx-0.5 border border-amber-500/40 font-semibold cursor-help"
                      title={`[${seg.label}] 原文: ${seg.original}`}
                    >
                      {seg.text}
                    </mark>
                  );
                }
                return <span key={idx}>{seg.text}</span>;
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
