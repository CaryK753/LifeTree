"use client";

import { useState, useEffect, useCallback } from "react";
import { History, Sparkles } from "lucide-react";
import { ChatPanel, EditableTitle } from "@/components/chat/chat-panel";
import { ConversationList } from "@/components/chat/conversation-list";
import { useGoals, useScenarios } from "@/lib/hooks";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useT } from "@/lib/i18n/provider";
import { cn } from "@/lib/utils";
import {
  useChatStore,
  getActiveConversation,
  renameConversation,
} from "@/lib/chat-store";

const SIDEBAR_KEY = "lifetree.chat.sidebarCollapsed";

export default function ChatPage() {
  const t = useT();
  const { data: goals } = useGoals();
  const [goalId, setGoalId] = useState<string | undefined>();
  const [scenarioId, setScenarioId] = useState<string | undefined>();
  const { data: scenarios } = useScenarios(goalId);

  // Subscribe to the chat store so the title bar re-renders when the
  // active conversation changes (new conversation selected, first message
  // auto-titled, etc.). Previously this lived inside ChatPanel's toolbar.
  const state = useChatStore();
  const activeConv = getActiveConversation();

  const handleRename = useCallback(
    (title: string) => {
      if (!state.activeId) return;
      renameConversation(state.activeId, title.trim());
    },
    [state.activeId]
  );

  // Sidebar collapse — persisted across reloads. Completely collapses (not minibar).
  const [collapsed, setCollapsed] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined") return;
    const v = window.localStorage.getItem(SIDEBAR_KEY);
    if (v === "1") setCollapsed(true);
  }, []);
  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(SIDEBAR_KEY, collapsed ? "1" : "0");
  }, [collapsed]);

  return (
    <div className="flex h-full relative">
      {/* Conversation history sidebar — completely collapses to w-0.
          The toggle button lives in the top title bar so it remains
          accessible whether the sidebar is open or collapsed. */}
      <aside
        className={cn(
          "shrink-0 transition-[width] duration-300 ease-out overflow-hidden border-r border-white/5",
          collapsed ? "w-0" : "w-64 sm:w-72"
        )}
        aria-hidden={collapsed}
      >
        {!collapsed && (
          <ConversationList
            goalId={goalId}
            scenarioId={scenarioId}
          />
        )}
      </aside>

      {/* Main chat column */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top title bar — sidebar toggle + advisor label + editable
            conversation title on the left, goal/scenario selectors on
            the right. Migrated here from ChatPanel's internal toolbar. */}
        <div className="flex items-center justify-between gap-3 px-4 py-2 border-b border-white/5 bg-surface/30 backdrop-blur-sm shrink-0">
          <div className="flex items-center gap-2 min-w-0 flex-1">
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 shrink-0"
              onClick={() => setCollapsed((v) => !v)}
              title={
                collapsed
                  ? t("chat.history.expand")
                  : t("chat.history.collapse")
              }
            >
              <History className="h-3.5 w-3.5" />
            </Button>
            <div className="flex items-center gap-1.5 min-w-0">
              <Sparkles className="h-3.5 w-3.5 text-brand-500 dark:text-brand-400 shrink-0" />
              <span className="text-xs font-medium text-zinc-700 dark:text-zinc-200 shrink-0 hidden sm:inline">
                {t("chat.advisorTitle")}
              </span>
              <span className="text-zinc-300 dark:text-zinc-600 select-none hidden sm:inline">·</span>
              <EditableTitle
                value={activeConv?.title ?? ""}
                placeholder={t("chat.titlePlaceholder")}
                onCommit={handleRename}
                disabled={!state.activeId}
              />
            </div>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <Select
              value={goalId ?? "__none__"}
              onValueChange={(v) => {
                setGoalId(v === "__none__" ? undefined : v);
                setScenarioId(undefined);
              }}
            >
              <SelectTrigger className="h-8 w-36 text-xs">
                <SelectValue placeholder={t("chatPage.selectGoal")} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__none__">{t("chatPage.noGoal")}</SelectItem>
                {(goals as any[])?.map((g) => (
                  <SelectItem key={g.id} value={g.id}>
                    {g.title}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {goalId && (scenarios as any[])?.length > 0 && (
              <Select
                value={scenarioId ?? "__none__"}
                onValueChange={(v) =>
                  setScenarioId(v === "__none__" ? undefined : v)
                }
              >
                <SelectTrigger className="h-8 w-32 text-xs">
                  <SelectValue placeholder={t("chatPage.selectScenario")} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">
                    {t("chatPage.defaultScenario")}
                  </SelectItem>
                  {(scenarios as any[])?.map((s) => (
                    <SelectItem key={s.id} value={s.id}>
                      {s.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>
        </div>

        {/* Chat fills remaining vertical space */}
        <div className="flex-1 min-h-0">
          <ChatPanel
            goalId={goalId}
            scenarioId={scenarioId}
          />
        </div>
      </div>
    </div>
  );
}
