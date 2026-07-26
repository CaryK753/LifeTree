"use client";

import { useMemo, useState } from "react";
import { useNotifications } from "@/lib/hooks";
import { api, type NotificationRead, type NotificationSeverity } from "@/lib/api";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { cn, formatDate } from "@/lib/utils";
import {
  Bell,
  BellOff,
  CheckCheck,
  Loader2,
  AlertTriangle,
  Info,
  AlertOctagon,
  Mail,
  MessageSquare,
  Smartphone,
  Radio,
} from "lucide-react";
import { useT } from "@/lib/i18n/provider";

type SeverityFilter = "all" | NotificationSeverity;
type ReadFilter = "all" | "unread" | "read";

const SEVERITY_META: Record<
  string,
  { labelKey: string; icon: typeof Info; pill: string; dot: string }
> = {
  info: {
    labelKey: "severity.info",
    icon: Info,
    pill: "border-sky-500/30 bg-sky-500/10 text-sky-700 dark:text-sky-300",
    dot: "bg-sky-400",
  },
  warning: {
    labelKey: "severity.warning",
    icon: AlertTriangle,
    pill: "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300",
    dot: "bg-amber-400",
  },
  critical: {
    labelKey: "severity.critical",
    icon: AlertOctagon,
    pill: "border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300",
    dot: "bg-red-400",
  },
};

const CHANNEL_META: Record<
  string,
  { labelKey: string; icon: typeof Mail }
> = {
  in_app: { labelKey: "channel.in_app", icon: MessageSquare },
  email: { labelKey: "channel.email", icon: Mail },
  sms: { labelKey: "channel.sms", icon: Smartphone },
  push: { labelKey: "channel.push", icon: Radio },
};

function sevMeta(s?: string) {
  return SEVERITY_META[s ?? "info"] ?? SEVERITY_META.info;
}

function chanMeta(c?: string) {
  return CHANNEL_META[c ?? "in_app"] ?? CHANNEL_META.in_app;
}

export default function NotificationsPage() {
  const t = useT();
  const { data, mutate, isLoading } = useNotifications();
  const toast = useToast();
  const [sevFilter, setSevFilter] = useState<SeverityFilter>("all");
  const [readFilter, setReadFilter] = useState<ReadFilter>("all");
  const [markingAll, setMarkingAll] = useState(false);

  const notifications = (data ?? []) as NotificationRead[];

  const unreadCount = useMemo(
    () => notifications.filter((n) => !n.read_at).length,
    [notifications]
  );

  const filtered = useMemo(() => {
    return notifications.filter((n) => {
      if (sevFilter !== "all" && n.severity !== sevFilter) return false;
      if (readFilter === "unread" && n.read_at) return false;
      if (readFilter === "read" && !n.read_at) return false;
      return true;
    });
  }, [notifications, sevFilter, readFilter]);

  async function handleMarkOne(id: string) {
    try {
      const updated = await api.markRead(id);
      mutate(
        (prev) =>
          (prev ?? []).map((n) => (n.id === id ? updated : n)),
        { revalidate: false }
      );
    } catch (e: any) {
      toast({ title: t("notifications.toast.markFailed"), description: e?.message, variant: "error" });
    }
  }

  async function handleMarkAll() {
    if (unreadCount === 0) return;
    setMarkingAll(true);
    try {
      // Mark unread notifications sequentially; backend exposes single-id endpoint.
      const targets = notifications.filter((n) => !n.read_at);
      const updated: NotificationRead[] = [];
      for (const n of targets) {
        try {
          updated.push(await api.markRead(n.id));
        } catch {
          // Skip individual failures.
        }
      }
      if (updated.length > 0) {
        mutate(
          (prev) =>
            (prev ?? []).map(
              (n) => updated.find((u) => u.id === n.id) ?? n
            ),
          { revalidate: false }
        );
        toast({
          title: t("notifications.toast.markedN", { n: updated.length }),
          variant: "success",
        });
      }
    } finally {
      setMarkingAll(false);
    }
  }

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 w-full max-w-[1600px] mx-auto animate-fade-in">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold text-zinc-100 flex items-center gap-2">
            <Bell className="h-6 w-6 text-brand-600 dark:text-brand-400" />
            {t("notifications.title")}
          </h1>
          <p className="text-sm text-zinc-500 mt-1">{t("notifications.subtitle")}</p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={handleMarkAll}
          disabled={markingAll || unreadCount === 0}
        >
          {markingAll ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />
          ) : (
            <CheckCheck className="h-3.5 w-3.5 mr-1.5" />
          )}
          {t("notifications.markAllRead")}
          {unreadCount > 0 && (
            <span className="ml-1.5 text-[10px] text-zinc-500">
              ({unreadCount})
            </span>
          )}
        </Button>
      </header>

      {/* Filter bar */}
      <div className="flex items-center gap-2 flex-wrap">
        <FilterGroup
          label={t("notifications.filter.severity")}
          value={sevFilter}
          onChange={(v) => setSevFilter(v as SeverityFilter)}
          options={[
            { value: "all", label: t("notifications.filter.all") },
            { value: "critical", label: t("severity.critical") },
            { value: "warning", label: t("severity.warning") },
            { value: "info", label: t("severity.info") },
          ]}
        />
        <div className="h-4 w-px bg-white/10 mx-1" />
        <FilterGroup
          label={t("notifications.filter.status")}
          value={readFilter}
          onChange={(v) => setReadFilter(v as ReadFilter)}
          options={[
            { value: "all", label: t("notifications.filter.all") },
            {
              value: "unread",
              label:
                unreadCount > 0
                  ? t("notifications.filter.unreadN", { n: unreadCount })
                  : t("notifications.filter.unread"),
            },
            { value: "read", label: t("notifications.filter.read") },
          ]}
        />
      </div>

      {/* List */}
      <Card>
        <CardHeader>
          <div>
            <CardTitle className="text-base">{t("notifications.list.title")}</CardTitle>
            <CardDescription className="mt-1">
              {isLoading
                ? t("common.loading")
                : filtered.length !== notifications.length
                ? t("notifications.list.countFiltered", {
                    n: filtered.length,
                    total: notifications.length,
                  })
                : t("notifications.list.count", { n: filtered.length })}
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="text-xs text-zinc-500 py-6 flex items-center gap-2">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> {t("common.loading")}
            </div>
          ) : filtered.length === 0 ? (
            <EmptyState unreadCount={unreadCount} />
          ) : (
            <ul className="divide-y divide-white/5">
              {filtered.map((n) => (
                <NotificationRow
                  key={n.id}
                  n={n}
                  onMark={() => handleMarkOne(n.id)}
                />
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function FilterGroup({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[10px] text-zinc-600 dark:text-zinc-500 uppercase tracking-wide mr-1">
        {label}
      </span>
      <div className="flex items-center gap-0.5 rounded-md bg-black/[0.04] dark:bg-white/[0.03] border border-black/10 dark:border-white/5 p-0.5">
        {options.map((opt) => {
          const active = value === opt.value;
          return (
            <button
              key={opt.value}
              type="button"
              onClick={() => onChange(opt.value)}
              className={cn(
                "text-xs px-2.5 py-1 rounded transition-colors",
                active
                  ? "bg-brand-500/15 dark:bg-brand-500/20 text-brand-700 dark:text-brand-200 border border-brand-500/30"
                  : "text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200 hover:bg-black/5 dark:hover:bg-white/5 border border-transparent"
              )}
            >
              {opt.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function NotificationRow({
  n,
  onMark,
}: {
  n: NotificationRead;
  onMark: () => void;
}) {
  const t = useT();
  const sm = sevMeta(n.severity);
  const cm = chanMeta(n.channel);
  const SevIcon = sm.icon;
  const ChanIcon = cm.icon;
  const isUnread = !n.read_at;

  const impactEntries = Object.entries(n.impact_summary ?? {}).filter(
    ([k, v]) => v != null && k !== "personalized_level"
  );
  const personalizedLevel = (n.impact_summary as any)?.personalized_level as
    | string
    | undefined;

  return (
    <li
      className={cn(
        "group py-3 px-1 transition-colors",
        isUnread && "bg-brand-500/[0.03]"
      )}
    >
      <div className="flex items-start gap-3">
        {/* Severity icon + unread dot */}
        <div className="relative shrink-0 mt-0.5">
          <span
            className={cn(
              "h-7 w-7 rounded-md flex items-center justify-center border",
              sm.pill
            )}
          >
            <SevIcon className="h-3.5 w-3.5" />
          </span>
          {isUnread && (
            <span
              className={cn(
                "absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full ring-2 ring-[rgb(var(--surface))]",
                sm.dot
              )}
            />
          )}
        </div>

        {/* Body */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className={cn(
                "text-sm font-medium",
                isUnread ? "text-zinc-100" : "text-zinc-300"
              )}
            >
              {n.title}
            </span>
            <span
              className={cn(
                "text-[10px] px-1.5 py-0.5 rounded border",
                sm.pill
              )}
            >
              {t(sm.labelKey)}
            </span>
            <span className="text-[10px] text-zinc-500 inline-flex items-center gap-1">
              <ChanIcon className="h-3 w-3" />
              {t(cm.labelKey)}
            </span>
            {personalizedLevel && (
              <span className="text-[10px] text-zinc-500">
                · {t("notifications.personalizedLevel")}
                <span className="ml-1 text-zinc-300">
                  {personalizedLevel}
                </span>
              </span>
            )}
          </div>

          <p className="text-xs text-zinc-400 mt-1 leading-relaxed break-words">
            {n.body}
          </p>

          {impactEntries.length > 0 && (
            <div className="mt-2 rounded-md bg-white/[0.02] border border-white/5 px-2.5 py-1.5 text-[11px] text-zinc-400 space-y-0.5">
              {impactEntries.slice(0, 4).map(([k, v]) => (
                <div key={k} className="flex gap-2">
                  <span className="text-zinc-500 shrink-0">{k}:</span>
                  <span className="text-zinc-300 break-words">
                    {typeof v === "object" ? JSON.stringify(v) : String(v)}
                  </span>
                </div>
              ))}
              {impactEntries.length > 4 && (
                <div className="text-[10px] text-zinc-600">
                  {t("notifications.moreDetails", { n: impactEntries.length - 4 })}
                </div>
              )}
            </div>
          )}

          <div className="mt-1.5 flex items-center gap-2 text-[10px] text-zinc-600">
            <span>{t("notifications.sentAt", { date: formatDate(n.sent_at ?? n.created_at) })}</span>
            {n.read_at && (
              <>
                <span>·</span>
                <span>{t("notifications.readAt", { date: formatDate(n.read_at) })}</span>
              </>
            )}
          </div>
        </div>

        {/* Mark-as-read action */}
        <div className="shrink-0">
          {isUnread ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={onMark}
              className="h-7 text-xs opacity-60 group-hover:opacity-100"
              title={t("notifications.markRead")}
            >
              <CheckCheck className="h-3.5 w-3.5 mr-1" />
              {t("notifications.read")}
            </Button>
          ) : (
            <span className="text-[10px] text-zinc-600 inline-flex items-center gap-1 pr-1">
              <CheckCheck className="h-3 w-3" />
              {t("notifications.read")}
            </span>
          )}
        </div>
      </div>
    </li>
  );
}

function EmptyState({ unreadCount }: { unreadCount: number }) {
  const t = useT();
  return (
    <div className="py-10 text-center space-y-3">
      <div className="mx-auto h-12 w-12 rounded-full bg-white/[0.03] border border-white/5 flex items-center justify-center">
        {unreadCount === 0 ? (
          <BellOff className="h-5 w-5 text-zinc-500" />
        ) : (
          <Bell className="h-5 w-5 text-zinc-500" />
        )}
      </div>
      <div className="text-sm text-zinc-400">
        {unreadCount === 0
          ? t("notifications.empty.noUnread")
          : t("notifications.empty.filtered")}
      </div>
      <p className="text-xs text-zinc-600 max-w-sm mx-auto">
        {t("notifications.empty.hint")}
      </p>
    </div>
  );
}
