"use client";

import { useEffect, useState } from "react";
import { AlertOctagon, Inbox, ShieldCheck } from "lucide-react";
import { ConflictsTab } from "@/components/review/conflicts-tab";
import { EventsReviewTab } from "@/components/review/events-review-tab";
import { SourcesReviewTab } from "@/components/review/sources-review-tab";
import { SidebarToggleButton } from "@/components/layout/sidebar-toggle-button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useUnifiedReview } from "@/lib/hooks";
import { useT } from "@/lib/i18n/provider";

type ReviewTab = "events" | "sources" | "conflicts";

export default function ReviewCenterPage() {
  const t = useT();
  const { data } = useUnifiedReview();
  const [tab, setTab] = useState<ReviewTab>("events");
  const counts = data?.counts;
  const total = counts
    ? (counts.events ?? 0) +
      (counts.source_proposals ?? 0) +
      (counts.pending_sources ?? 0) +
      (counts.risk_proposals ?? 0) +
      (counts.conflicts ?? 0)
    : 0;

  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get("tab");
    if (requested === "events" || requested === "sources" || requested === "conflicts") {
      setTab(requested);
    }
  }, []);

  function changeTab(next: string) {
    const value = next as ReviewTab;
    setTab(value);
    const url = new URL(window.location.href);
    url.searchParams.set("tab", value);
    window.history.replaceState(null, "", url);
  }

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 animate-fade-in min-w-0">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold text-foreground flex items-center gap-2">
            <SidebarToggleButton />
            <Inbox className="h-6 w-6 text-brand-500" />
            {t("review.title")}
          </h1>
          <p className="text-sm text-muted-foreground mt-1">{t("review.subtitle")}</p>
        </div>
        <Badge variant="risk" riskLevel={total > 0 ? "high" : "low"}>
          {t("review.queueCount", { n: total })}
        </Badge>
      </header>

      <Tabs value={tab} onValueChange={changeTab} className="min-w-0">
        <div className="max-w-full overflow-x-auto pb-1">
          <TabsList className="w-max min-w-full justify-start">
            <ReviewTabButton value="events" icon={Inbox} label={t("review.tab.events")} count={counts ? (counts.events ?? 0) + (counts.source_proposals ?? 0) + (counts.risk_proposals ?? 0) : 0} />
            <ReviewTabButton value="sources" icon={ShieldCheck} label={t("review.tab.sources")} count={counts?.pending_sources ?? 0} />
            <ReviewTabButton value="conflicts" icon={AlertOctagon} label={t("review.tab.conflicts")} count={counts?.conflicts ?? 0} />
          </TabsList>
        </div>
        <TabsContent value="events" className="space-y-6"><EventsReviewTab /></TabsContent>
        <TabsContent value="sources"><SourcesReviewTab /></TabsContent>
        <TabsContent value="conflicts"><ConflictsTab /></TabsContent>
      </Tabs>
    </div>
  );
}

function ReviewTabButton({ value, icon: Icon, label, count }: {
  value: ReviewTab;
  icon: typeof Inbox;
  label: string;
  count: number;
}) {
  return (
    <TabsTrigger value={value} className="gap-1.5">
      <Icon className="h-3.5 w-3.5" />
      {label}
      {count > 0 && <span className="ml-1 min-w-4 rounded-full bg-amber-500 px-1 text-[9px] text-white">{count}</span>}
    </TabsTrigger>
  );
}
