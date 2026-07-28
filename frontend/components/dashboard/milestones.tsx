"use client";

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { useT } from "@/lib/i18n/provider";
import { useEffect, useRef, useState } from "react";
import { CheckCircle2, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";

interface Milestone {
  label?: string;
  due?: string;
  status?: string;
  pathway?: string;
}

interface Props {
  milestones: Milestone[];
}

function isDone(status?: string): boolean {
  return Boolean(status?.match(/done|complete|met/i));
}

/**
 * §5 里程碑点亮动画 — milestone completion "lighting up".
 *
 * When a milestone transitions to a done state (done / complete / met),
 * the row briefly plays a pop + sparkle animation so the user gets
 * immediate positive feedback. Per project plan §6 (低焦虑设计): the
 * animation is a one-shot, not a perpetual loop, and respects
 * prefers-reduced-motion (handled globally in globals.css).
 */
export function Milestones({ milestones }: Props) {
  const t = useT();
  const completed = milestones.filter((m) => isDone(m.status)).length;
  const pct = milestones.length > 0 ? (completed / milestones.length) * 100 : 0;

  // Track which milestones were done on the previous render. A milestone
  // that flips from not-done → done this render gets the celebrate class.
  const prevDoneRef = useRef<Set<string>>(new Set());
  const [celebrating, setCelebrating] = useState<Set<string>>(new Set());

  useEffect(() => {
    const next = new Set<string>();
    const newlyDone: string[] = [];
    milestones.forEach((m, i) => {
      const key = `${i}-${m.label ?? ""}`;
      if (isDone(m.status)) {
        next.add(key);
        if (!prevDoneRef.current.has(key)) {
          newlyDone.push(key);
        }
      }
    });
    prevDoneRef.current = next;

    if (newlyDone.length > 0) {
      setCelebrating((prev) => {
        const updated = new Set(prev);
        for (const k of newlyDone) updated.add(k);
        return updated;
      });
      // Clear celebration flag after the animation completes (~600ms).
      const timer = setTimeout(() => {
        setCelebrating((prev) => {
          const updated = new Set(prev);
          for (const k of newlyDone) updated.delete(k);
          return updated;
        });
      }, 1200);
      return () => clearTimeout(timer);
    }
  }, [milestones]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("milestones.title")}</CardTitle>
        <CardDescription>
          {t("milestones.completed", { done: completed, total: milestones.length })}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Progress value={pct} className="mb-4" />
        <div className="space-y-2">
          {milestones.map((m, i) => {
            const done = isDone(m.status);
            const key = `${i}-${m.label ?? ""}`;
            const isCelebrating = celebrating.has(key);
            return (
              <div
                key={key}
                className={cn(
                  "grid grid-cols-[1fr_auto] items-center gap-3 text-xs rounded-md px-2 py-1.5 transition-colors",
                  done && "bg-emerald-500/[0.06]",
                  isCelebrating && "animate-celebrate-pop"
                )}
              >
                <div className="min-w-0 flex items-center gap-2">
                  {done ? (
                    <div className="relative shrink-0">
                      <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
                      {isCelebrating && (
                        <Sparkles className="absolute -top-1.5 -right-1.5 h-2.5 w-2.5 text-amber-400 animate-ping" />
                      )}
                    </div>
                  ) : (
                    <div className="h-3.5 w-3.5 rounded-full border border-zinc-600 shrink-0" />
                  )}
                  <div className="min-w-0">
                    <div className={cn("truncate", done ? "text-zinc-200" : "text-zinc-400")}>
                      {m.label}
                    </div>
                    <div className="text-[10px] text-zinc-500 mt-0.5">
                      {m.pathway && <span>{m.pathway} · </span>}
                      {m.due && <span>{t("milestones.due", { date: m.due })}</span>}
                    </div>
                  </div>
                </div>
                <Badge
                  variant="risk"
                  riskLevel={
                    done ? "low"
                    : m.status?.match(/in_progress/i) ? "medium"
                    : "high"
                  }
                >
                  {m.status ?? "pending"}
                </Badge>
              </div>
            );
          })}
          {milestones.length === 0 && (
            <div className="text-xs text-zinc-500 text-center py-4">
              {t("milestones.empty")}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
