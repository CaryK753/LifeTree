"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type EventRead } from "@/lib/api";
import { usePendingReview } from "@/lib/hooks";
import { useT } from "@/lib/i18n/provider";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { useToast } from "@/components/ui/toast";

export type ReviewAction = "approve" | "sink" | "keep_sunk";
export type RiskFilter = "all" | "high" | "medium" | "low";

export function useEventReviewQueue() {
  const t = useT();
  const toast = useToast();
  const { confirm, ConfirmRoot } = useConfirm();
  const { data, mutate, isLoading } = usePendingReview();
  const [actingId, setActingId] = useState<string | null>(null);
  const [filter, setFilter] = useState<RiskFilter>("all");
  const [batchRunning, setBatchRunning] = useState(false);
  const items = (data as EventRead[] | undefined) ?? [];
  const filteredItems = useMemo(
    () => filter === "all"
      ? items
      : items.filter((item) => (item.risk_flag_level ?? "low") === filter),
    [items, filter]
  );
  const counts = useMemo(() => {
    const result = { all: items.length, high: 0, medium: 0, low: 0 };
    for (const item of items) {
      const level = item.risk_flag_level ?? "low";
      if (level === "high" || level === "medium" || level === "low") result[level]++;
    }
    return result;
  }, [items]);

  const handleAction = useCallback(async (eventId: string, action: ReviewAction) => {
    if (actingId) return;
    if (action === "approve") {
      const approved = await confirm({
        title: t("review.approveConfirm.title"),
        description: t("review.approveConfirm.body"),
        confirmLabel: t("review.approve"),
        cancelLabel: t("common.cancel"),
      });
      if (!approved) return;
    }
    setActingId(eventId);
    try {
      await api.updateEventStatus(eventId, action);
      await mutate();
      toast({
        title: t(action === "approve" ? "review.toast.approveWithBranch" : `review.toast.${action}`),
        variant: "success",
        ...(action === "approve" && { description: t("review.emptyBranchesHint") }),
      });
    } catch (error: any) {
      toast({ title: t("review.toast.failed"), description: error?.message, variant: "error" });
    } finally {
      setActingId(null);
    }
  }, [actingId, confirm, mutate, t, toast]);

  const handleBatch = useCallback(async (action: ReviewAction) => {
    if (batchRunning || filteredItems.length === 0) return;
    const approved = await confirm({
      title: t("review.batch.title"),
      description: t(action === "approve" ? "review.batch.approveConfirm" : "review.batch.sinkConfirm", { n: filteredItems.length }),
      confirmLabel: t(action === "approve" ? "review.batch.approveAll" : "review.batch.sinkAll"),
      cancelLabel: t("common.cancel"),
      variant: action === "approve" ? "default" : "danger",
    });
    if (!approved) return;
    setBatchRunning(true);
    let success = 0;
    let fail = 0;
    for (const item of filteredItems) {
      try {
        await api.updateEventStatus(item.id, action);
        success++;
      } catch {
        fail++;
      }
    }
    await mutate();
    setBatchRunning(false);
    toast({ title: t("review.batch.done", { success, fail }), variant: fail ? "warning" : "success" });
  }, [batchRunning, confirm, filteredItems, mutate, t, toast]);

  useEffect(() => {
    if (!filteredItems.length || actingId || batchRunning) return;
    const handler = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable || target.closest("[role=dialog]")) return;
      const actions: Record<string, ReviewAction> = { a: "approve", s: "sink", k: "keep_sunk" };
      const action = actions[event.key.toLowerCase()];
      if (!action) return;
      event.preventDefault();
      handleAction(filteredItems[0].id, action);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [actingId, batchRunning, filteredItems, handleAction]);

  return {
    ConfirmRoot,
    actingId,
    batchRunning,
    counts,
    filter,
    filteredItems,
    handleAction,
    handleBatch,
    isLoading,
    items,
    setFilter,
  };
}
