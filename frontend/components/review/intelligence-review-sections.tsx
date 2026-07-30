"use client";

import { useState } from "react";
import { AlertTriangle, Check, ExternalLink, Loader2, Radio, X } from "lucide-react";
import { api, type ReviewRiskProposal } from "@/lib/api";
import { useUnifiedReview } from "@/lib/hooks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";

export function IntelligenceReviewSections() {
  const { data, mutate, isLoading } = useUnifiedReview();
  const toast = useToast();
  const [working, setWorking] = useState<string | null>(null);

  async function run(id: string, operation: () => Promise<unknown>) {
    setWorking(id);
    try {
      await operation();
      await mutate();
      toast({ title: "审阅结果已保存", variant: "success" });
    } catch (error: any) {
      toast({ title: "审阅失败", description: error?.message, variant: "error" });
    } finally {
      setWorking(null);
    }
  }

  if (isLoading) return <Skeleton className="h-28 w-full" />;
  if (!data) return null;
  const intelligenceCount =
    data.counts.source_proposals + data.counts.risk_proposals;
  if (intelligenceCount === 0) return null;

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center justify-between text-base">
          <span className="flex items-center gap-2">
            <Radio className="h-4 w-4 text-brand-500" /> 情报审阅
          </span>
          <Badge>{intelligenceCount}</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="divide-y divide-border/20 p-0">
        {data.source_proposals.map((source) => (
          <div key={source.id} className="flex items-start gap-3 px-4 py-3">
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium">{source.title}</div>
              <div className="mt-1 flex items-center gap-2 text-xs text-muted">
                <span>相关度 {(source.relevance_score * 100).toFixed(0)}%</span>
                <a href={source.url} target="_blank" rel="noreferrer" title="查看信源">
                  <ExternalLink className="h-3.5 w-3.5" />
                </a>
              </div>
            </div>
            <ReviewButtons
              busy={working === source.id}
              onAccept={() => run(source.id, () => api.acceptSourceProposal(source.id))}
              onReject={() => run(source.id, () => api.rejectSourceProposal(source.id))}
            />
          </div>
        ))}

        {data.risk_proposals.map((risk) => (
          <RiskRow key={risk.id} risk={risk} working={working} run={run} />
        ))}
      </CardContent>
    </Card>
  );
}

function RiskRow({ risk, working, run }: {
  risk: ReviewRiskProposal;
  working: string | null;
  run: (id: string, operation: () => Promise<unknown>) => Promise<void>;
}) {
  const pathwayId = risk.impact_preview?.suggested_pathway_id;
  return (
    <div className="flex items-start gap-3 px-4 py-3">
      <AlertTriangle className="mt-0.5 h-4 w-4 text-amber-500" />
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium">{risk.name}</div>
        <div className="mt-1 text-xs text-muted">
          {risk.region || "全球"} · 影响 {risk.affected_goals_count} 个目标
        </div>
      </div>
      <ReviewButtons
        busy={working === risk.id}
        acceptDisabled={!pathwayId}
        onAccept={() => pathwayId && run(risk.id, () => api.adoptRiskProposal(risk, pathwayId))}
        onReject={() => run(risk.id, () => api.rejectRiskProposal(risk.id))}
      />
    </div>
  );
}

function ReviewButtons({ busy, acceptDisabled, onAccept, onReject }: {
  busy: boolean;
  acceptDisabled?: boolean;
  onAccept: () => void;
  onReject: () => void;
}) {
  return (
    <div className="flex shrink-0 gap-1">
      <Button size="icon-sm" title="采纳" disabled={busy || acceptDisabled} onClick={onAccept}>
        {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
      </Button>
      <Button size="icon-sm" variant="ghost" title="拒绝" disabled={busy} onClick={onReject}>
        <X className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}
