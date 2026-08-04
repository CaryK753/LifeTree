"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import useSWRInfinite from "swr/infinite";
import {
  useUnreadCount,
  type NotificationFilter,
} from "@/lib/hooks";
import {
  api,
  type NotificationChannel,
  type NotificationRead,
  type NotificationSeverity,
} from "@/lib/api";
import { swrConfig } from "@/lib/api";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";
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
  ChevronRight,
  Inbox,
} from "lucide-react";
import { useI18n, useT } from "@/lib/i18n/provider";
import type { Locale } from "@/lib/i18n/messages";
import { formatDistanceToNow } from "date-fns";
import { zhCN, zhTW, enUS, es, de, fr as frLocale } from "date-fns/locale";
import { SidebarToggleButton } from "@/components/layout/sidebar-toggle-button";

type SeverityFilter = "all" | NotificationSeverity;
type ReadFilter = "all" | "unread" | "read";
type ChannelFilter = "all" | NotificationChannel;

const PAGE_SIZE = 50;

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

// Map LifeTree i18n locale → date-fns locale for relative-time formatting.
const DATE_FNS_LOCALES: Record<Locale, typeof zhCN> = {
  "zh-CN": zhCN,
  "zh-TW": zhTW,
  en: enUS,
  es,
  de,
  fr: frLocale,
};

function sevMeta(s?: string) {
  return SEVERITY_META[s ?? "info"] ?? SEVERITY_META.info;
}

function chanMeta(c?: string) {
  return CHANNEL_META[c ?? "in_app"] ?? CHANNEL_META.in_app;
}

/**
 * Resolve the deep-link target for a notification, if any.
 *
 * - `event_id` present → `/sources?event={event_id}`
 * - `risk_factor_id` starts with `risk_transition:` → `/goals/{goal_id}`
 *   (goal_id is taken from a `goal_id` field if present, otherwise
 *   extracted from the suffix of `risk_factor_id`).
 */
function getDeepLink(n: NotificationRead): string | null {
  if (n.event_id) {
    return `/sources?event=${encodeURIComponent(n.event_id)}`;
  }
  const rfid = n.risk_factor_id;
  if (rfid && rfid.startsWith("risk_transition:")) {
    const suffix = rfid.slice("risk_transition:".length);
    const fromImpact = (n.impact_summary as Record<string, unknown> | null)?.goal_id;
    const goalId =
      (typeof fromImpact === "string" && fromImpact) ||
      (n as NotificationRead & { goal_id?: string }).goal_id ||
      suffix;
    if (goalId) return `/goals/view?id=${encodeURIComponent(goalId)}`;
  }
  return null;
}

function formatRelative(
  value: string | Date | null | undefined,
  locale: Locale
): string {
  if (!value) return "—";
  const d = typeof value === "string" ? new Date(value) : value;
  if (Number.isNaN(d.getTime())) return "—";
  return formatDistanceToNow(d, {
    addSuffix: true,
    locale: DATE_FNS_LOCALES[locale] ?? zhCN,
  });
}

export default function NotificationsPage() {
  const t = useT();
  const { locale } = useI18n();
  const router = useRouter();
  const toast = useToast();

  const [sevFilter, setSevFilter] = useState<SeverityFilter>("all");
  const [readFilter, setReadFilter] = useState<ReadFilter>("all");
  const [chanFilter, setChanFilter] = useState<ChannelFilter>("all");
  const [markingAll, setMarkingAll] = useState(false);

  // Server-side filter params — sent to the API as query string.
  const filter: NotificationFilter = useMemo(
    () => ({
      severity: sevFilter !== "all" ? sevFilter : undefined,
      status:
        readFilter === "unread"
          ? "unread"
          : readFilter === "read"
          ? "read"
          : undefined,
      channel: chanFilter !== "all" ? chanFilter : undefined,
    }),
    [sevFilter, readFilter, chanFilter]
  );

  // useSWRInfinite handles "Load more" pagination cleanly: each page has
  // its own cache key `["notifications", filter, pageIndex]`, so the
  // SSEProvider's function matcher (which matches any array key whose
  // first element is "notifications") revalidates every loaded page on
  // `risk_alert` / `notification` events.
  type NotificationPageKey = ["notifications", string, number];
  const filterKey = JSON.stringify(filter);
  const {
    data: pages,
    size,
    setSize,
    isLoading,
    isValidating,
    mutate: mutatePages,
  } = useSWRInfinite<NotificationRead[]>(
    (pageIndex, prevPage): NotificationPageKey | null => {
      if (prevPage && prevPage.length < PAGE_SIZE) return null;
      return ["notifications", filterKey, pageIndex];
    },
    ([, , pageIndex]: NotificationPageKey) =>
      api.listNotifications({
        ...filter,
        limit: PAGE_SIZE,
        offset: pageIndex * PAGE_SIZE,
      }),
    {
      ...swrConfig,
      refreshInterval: 60000,
      // When the filter changes, reset to the first page so we don't
      // carry over stale pages from the previous filter.
      revalidateFirstPage: true,
    }
  );

  // Reset to the first page whenever the filter changes.
  useEffect(() => {
    setSize(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey]);

  const items = useMemo(
    () => (pages ?? []).flat() as NotificationRead[],
    [pages]
  );

  const lastPage = pages?.[pages.length - 1];
  const hasMore = !lastPage ? false : lastPage.length >= PAGE_SIZE;
  const loadingMore = isValidating && size > 1 && !isLoading;

  // Efficient unread badge from `GET /notifications/unread-count`,
  // polled every 30s. Also revalidated by SSE events thanks to the
  // array SWR key whose first element is "notifications".
  const { data: unreadData, mutate: mutateUnreadCount } = useUnreadCount();
  const unreadCount = unreadData?.count ?? 0;

  // Track newly-arrived IDs so we can pulse those rows briefly.
  // On the very first load we skip the pulse (would be noisy for 50 rows).
  const [freshIds, setFreshIds] = useState<Set<string>>(new Set());
  const prevIdsRef = useRef<Set<string> | null>(null);
  const freshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (items.length === 0) {
      prevIdsRef.current = new Set();
      return;
    }
    const currentIds = new Set(items.map((n) => n.id));
    if (prevIdsRef.current === null) {
      // First load — initialize without pulsing.
      prevIdsRef.current = currentIds;
      return;
    }
    const newIds = new Set<string>();
    for (const id of currentIds) {
      if (!prevIdsRef.current.has(id)) newIds.add(id);
    }
    prevIdsRef.current = currentIds;
    if (newIds.size === 0) return;
    setFreshIds(newIds);
    if (freshTimerRef.current) clearTimeout(freshTimerRef.current);
    freshTimerRef.current = setTimeout(() => setFreshIds(new Set()), 1700);
    return () => {
      if (freshTimerRef.current) clearTimeout(freshTimerRef.current);
    };
  }, [items]);

  async function handleMarkOne(id: string) {
    try {
      const updated = await api.markRead(id);
      mutatePages(
        (prev) =>
          (prev ?? []).map((page) =>
            page.map((n) => (n.id === id ? updated : n))
          ),
        { revalidate: false }
      );
      mutateUnreadCount();
    } catch (e: any) {
      toast({
        title: t("notifications.toast.markFailed"),
        description: e?.message,
        variant: "error",
      });
    }
  }

  async function handleMarkAll() {
    const unreadIds = items.filter((n) => !n.read_at).map((n) => n.id);
    if (unreadIds.length === 0) return;
    setMarkingAll(true);
    try {
      const result = await api.bulkMarkRead(unreadIds);
      const nowIso = new Date().toISOString();
      const idSet = new Set(unreadIds);
      mutatePages(
        (prev) =>
          (prev ?? []).map((page) =>
            page.map((n) =>
              idSet.has(n.id) ? { ...n, read_at: nowIso, status: "read" } : n
            )
          ),
        { revalidate: false }
      );
      mutateUnreadCount();
      toast({
        title: t("notifications.markAllReadSuccess", { n: result.updated }),
        variant: "success",
      });
    } catch (e: any) {
      toast({
        title: t("notifications.toast.markFailed"),
        description: e?.message,
        variant: "error",
      });
    } finally {
      setMarkingAll(false);
    }
  }

  function handleRowClick(n: NotificationRead) {
    const link = getDeepLink(n);
    if (link) router.push(link);
  }

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 w-full max-w-[1600px] mx-auto animate-fade-in">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold text-zinc-100 flex items-center gap-2">
            <SidebarToggleButton />
            <Bell className="h-6 w-6 text-brand-600 dark:text-brand-400" />
            {t("notifications.title")}
            {unreadCount > 0 && (
              <span className="ml-1.5 text-xs font-medium px-2 py-0.5 rounded-full bg-brand-500/15 text-brand-700 dark:text-brand-300 border border-brand-500/30">
                {t("notifications.unreadBadge", { n: unreadCount })}
              </span>
            )}
          </h1>
          <p className="text-sm text-zinc-500 mt-1">
            {t("notifications.subtitle")}
          </p>
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
        <div className="h-4 w-px bg-black/10 dark:bg-white/10 mx-1" />
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
        <div className="h-4 w-px bg-black/10 dark:bg-white/10 mx-1" />
        <FilterGroup
          label={t("notifications.filter.channel")}
          value={chanFilter}
          onChange={(v) => setChanFilter(v as ChannelFilter)}
          options={[
            { value: "all", label: t("notifications.filter.all") },
            { value: "in_app", label: t("channel.in_app") },
            { value: "email", label: t("channel.email") },
            { value: "sms", label: t("channel.sms") },
            { value: "push", label: t("channel.push") },
          ]}
        />
      </div>

      {/* List */}
      <Card>
        <CardHeader>
          <div>
            <CardTitle className="text-base">
              {t("notifications.list.title")}
            </CardTitle>
            <CardDescription className="mt-1">
              {isLoading
                ? t("common.loading")
                : t("notifications.list.count", { n: items.length })}
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="text-xs text-zinc-500 py-6 flex items-center gap-2">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />{" "}
              {t("common.loading")}
            </div>
          ) : items.length === 0 ? (
            <EmptyState hasFilters={readFilter !== "all" || sevFilter !== "all" || chanFilter !== "all"} />
          ) : (
            <>
              <ul className="divide-y divide-black/5 dark:divide-white/5">
                {items.map((n) => (
                  <NotificationRow
                    key={n.id}
                    n={n}
                    fresh={freshIds.has(n.id)}
                    onMark={() => handleMarkOne(n.id)}
                    onClick={() => handleRowClick(n)}
                  />
                ))}
              </ul>
              <div className="mt-3 flex items-center justify-center">
                {hasMore ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setSize(size + 1)}
                    disabled={loadingMore}
                  >
                    {loadingMore ? (
                      <>
                        <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />
                        {t("notifications.loadingMore")}
                      </>
                    ) : (
                      t("notifications.loadMore")
                    )}
                  </Button>
                ) : (
                  <span className="text-[10px] text-zinc-500">
                    {t("notifications.noMore")}
                  </span>
                )}
              </div>
            </>
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
  fresh,
  onMark,
  onClick,
}: {
  n: NotificationRead;
  fresh: boolean;
  onMark: () => void;
  onClick: () => void;
}) {
  const t = useT();
  const { locale } = useI18n();
  const sm = sevMeta(n.severity);
  const cm = chanMeta(n.channel);
  const SevIcon = sm.icon;
  const ChanIcon = cm.icon;
  const isUnread = !n.read_at;
  const deepLink = getDeepLink(n);
  const clickable = !!deepLink;

  const impactEntries = Object.entries(n.impact_summary ?? {}).filter(
    ([k, v]) => v != null && k !== "personalized_level" && k !== "goal_id"
  );
  const personalizedLevel = (n.impact_summary as any)?.personalized_level as
    | string
    | undefined;

  const sentAtRelative = formatRelative(n.sent_at ?? n.created_at, locale);
  const readAtRelative = formatRelative(n.read_at, locale);

  return (
    <li
      onClick={clickable ? onClick : undefined}
      role={clickable ? "button" : undefined}
      tabIndex={clickable ? 0 : undefined}
      onKeyDown={
        clickable
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onClick();
              }
            }
          : undefined
      }
      className={cn(
        "group py-3 px-1 transition-colors",
        isUnread && "bg-brand-500/[0.04]",
        fresh && "animate-row-pulse",
        clickable &&
          "cursor-pointer hover:bg-black/[0.02] dark:hover:bg-white/[0.02] focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/40 rounded"
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
                <span className="ml-1 text-zinc-300">{personalizedLevel}</span>
              </span>
            )}
            {clickable && (
              <ChevronRight className="h-3 w-3 text-zinc-500 opacity-0 group-hover:opacity-100 transition-opacity ml-auto" />
            )}
          </div>

          <p className="text-xs text-zinc-400 mt-1 leading-relaxed break-words">
            {n.body}
          </p>

          {impactEntries.length > 0 && (
            <div className="mt-2 rounded-md bg-black/[0.02] dark:bg-white/[0.02] border border-black/5 dark:border-white/5 px-2.5 py-1.5 text-[11px] text-zinc-400 space-y-0.5">
              {impactEntries.slice(0, 4).map(([k, v]) => (
                <div key={k} className="flex gap-2">
                  <span className="text-zinc-500 shrink-0">{k}:</span>
                  <span className="text-zinc-300 dark:text-zinc-200 break-words">
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

          <div className="mt-1.5 flex items-center gap-2 text-[10px] text-zinc-600 dark:text-zinc-500">
            <span>{sentAtRelative}</span>
            {n.read_at && (
              <>
                <span>·</span>
                <span>
                  {t("notifications.readAt", { date: readAtRelative })}
                </span>
              </>
            )}
          </div>
        </div>

        {/* Mark-as-read action */}
        <div className="shrink-0" onClick={(e) => e.stopPropagation()}>
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
            <span className="text-[10px] text-zinc-600 dark:text-zinc-500 inline-flex items-center gap-1 pr-1">
              <CheckCheck className="h-3 w-3" />
              {t("notifications.read")}
            </span>
          )}
        </div>
      </div>
    </li>
  );
}

function EmptyState({ hasFilters }: { hasFilters: boolean }) {
  const t = useT();
  return (
    <div className="py-12 text-center space-y-3">
      <div className="mx-auto h-14 w-14 rounded-full bg-brand-500/10 border border-brand-500/20 flex items-center justify-center">
        {hasFilters ? (
          <BellOff className="h-6 w-6 text-zinc-500 dark:text-zinc-400" />
        ) : (
          <Inbox className="h-6 w-6 text-brand-600 dark:text-brand-400" />
        )}
      </div>
      <div className="text-sm text-zinc-400 dark:text-zinc-300">
        {hasFilters
          ? t("notifications.empty.filtered")
          : t("notifications.noNew")}
      </div>
      <p className="text-xs text-zinc-600 dark:text-zinc-500 max-w-sm mx-auto">
        {hasFilters ? t("notifications.empty.hint") : t("notifications.noNewHint")}
      </p>
    </div>
  );
}
