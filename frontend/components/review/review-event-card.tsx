"use client";

import Link from "next/link";
import { AlertTriangle, Anchor, Archive, Check, ExternalLink, Loader2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { EventRead } from "@/lib/api";
import { useT } from "@/lib/i18n/provider";
import { cn, formatDate } from "@/lib/utils";
import type { ReviewAction } from "./use-event-review-queue";

export function ReviewEventCard({
  event,
  acting,
  highlight,
  onAction,
}: {
  event: EventRead;
  acting: boolean;
  highlight: boolean;
  onAction: (action: ReviewAction) => void;
}) {
  const t = useT();
  const level = (event.risk_flag_level as string | null) ?? "low";
  const riskType = (event.risk_flag_type as string | null) ?? null;
  const confidence = (event.extraction_confidence as number | undefined) ?? null;
  const occurredAt = (event.occurred_at as string | null) ?? null;
  const sourceId = (event.source_id as string | null) ?? null;
  const confidenceColor = confidence == null
    ? "bg-border/20"
    : confidence < 0.5
      ? "bg-risk-high"
      : confidence < 0.7
        ? "bg-risk-medium"
        : "bg-risk-low";

  return (
    <Card className={cn("transition-all", acting && "opacity-60 pointer-events-none", highlight && "ring-2 ring-brand-500/30 ring-offset-2 ring-offset-bg")}>
      <CardContent className="p-4 space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              {level === "high" && <AlertTriangle className="h-4 w-4 text-amber-500" />}
              <span className="text-sm font-medium truncate">{event.subject ?? t("review.unlabeled")}</span>
              <Badge variant="risk" riskLevel={level === "high" ? "high" : level === "medium" ? "medium" : "low"}>
                {t(`review.riskLevel.${level}`)}
              </Badge>
            </div>
            <div className="text-xs text-muted-foreground mt-1">
              <span className="text-foreground/80">{event.action}</span>
              {event.object && <span> · {event.object}</span>}
            </div>
          </div>
          <div className="text-[10px] text-muted-foreground text-right shrink-0">
            <div>{formatDate(event.created_at)}</div>
            {occurredAt && <div>{t("review.occurred", { date: formatDate(occurredAt) })}</div>}
          </div>
        </div>

        <div className="flex items-center gap-3 text-[10px] text-muted-foreground flex-wrap">
          {riskType && <span>{t("review.riskType")}: <span className="text-foreground/80">{riskType}</span></span>}
          {confidence != null && (
            <span className="inline-flex items-center gap-1.5">
              {t("review.confidence")}:
              <span className="relative h-1.5 w-12 rounded-full bg-border/15 overflow-hidden">
                <span className={cn("absolute inset-y-0 left-0", confidenceColor)} style={{ width: `${Math.round(confidence * 100)}%` }} />
              </span>
              {(confidence * 100).toFixed(0)}%
            </span>
          )}
          {sourceId && <Link href="/sources" className="inline-flex items-center gap-1 text-brand-600"><ExternalLink className="h-3 w-3" />{t("review.viewSource")}</Link>}
        </div>

        <div className="pt-2 border-t border-border/8 space-y-1.5">
          <div className="flex items-center gap-2 flex-wrap">
            <ActionButton action="approve" acting={acting} onAction={onAction} icon={Check} />
            <ActionButton action="sink" acting={acting} onAction={onAction} icon={Archive} variant="outline" />
            <ActionButton action="keep_sunk" acting={acting} onAction={onAction} icon={Anchor} variant="ghost" />
          </div>
          <div className="flex flex-wrap gap-x-4 text-[10px] text-muted/80">
            <span>· {t("review.actionHint.approve")}</span>
            <span>· {t("review.actionHint.sink")}</span>
            <span>· {t("review.actionHint.keepSunk")}</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function ActionButton({ action, acting, onAction, icon: Icon, variant = "default" }: {
  action: ReviewAction;
  acting: boolean;
  onAction: (action: ReviewAction) => void;
  icon: typeof Check;
  variant?: "default" | "outline" | "ghost";
}) {
  const t = useT();
  const suffix = action === "keep_sunk" ? "keepSunk" : action;
  return <Button size="sm" variant={variant} onClick={() => onAction(action)} disabled={acting} title={t(`review.actionHint.${suffix}`)}>{acting && action === "approve" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Icon className="h-3.5 w-3.5" />}<span className="ml-1.5">{t(`review.${suffix}`)}</span></Button>;
}
