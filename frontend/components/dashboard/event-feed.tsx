"use client";

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";

interface EventItem {
  id: string;
  subject: string;
  action: string;
  object?: string | null;
  occurred_at?: string | null;
  risk_flag_level?: "low" | "medium" | "high" | null;
  risk_flag_type?: string | null;
}

interface Props {
  events: EventItem[];
}

export function EventFeed({ events }: Props) {
  const t = useT();
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("eventFeed.title")}</CardTitle>
        <CardDescription>{t("eventFeed.subtitle")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {events.length === 0 && (
          <div className="text-xs text-zinc-500 py-4 text-center">{t("eventFeed.empty")}</div>
        )}
        {events.map((ev) => (
          <div key={ev.id} className="flex items-start gap-3 border-b border-white/5 pb-3 last:border-0 last:pb-0">
            <div className="mt-0.5">
              <Badge variant="risk" riskLevel={ev.risk_flag_level ?? undefined}>
                {ev.risk_flag_level ?? "—"}
              </Badge>
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-sm text-zinc-200 truncate">
                <span className="font-medium">{ev.subject}</span>
                <span className="text-zinc-400"> · {ev.action}</span>
                {ev.object && <span className="text-zinc-500"> · {ev.object}</span>}
              </div>
              <div className="mt-1 text-[10px] text-zinc-500 flex items-center gap-2">
                {ev.risk_flag_type && <span className="capitalize">{ev.risk_flag_type}</span>}
                <span>· {formatDate(ev.occurred_at)}</span>
              </div>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
