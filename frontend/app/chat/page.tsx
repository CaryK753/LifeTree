"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { History, Sparkles, Plus } from "lucide-react";
import { ChatPanel, EditableTitle } from "@/components/chat/chat-panel";
import { ConversationList } from "@/components/chat/conversation-list";
import { useGoals, useScenarios } from "@/lib/hooks";
import { useRuntimeCatalog } from "@/lib/hooks";
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
  createConversation,
} from "@/lib/chat-store";
import { SidebarToggleButton } from "@/components/layout/sidebar-toggle-button";
import { useSidebarDrawerMode } from "@/lib/use-sidebar-drawer-mode";
import { useChatShortcuts } from "@/lib/use-chat-shortcuts";
import { ChatModelSelector } from "@/components/chat/chat-model-selector";

const SIDEBAR_KEY = "lifetree.chat.sidebarCollapsed";

export default function ChatPage() {
  const t = useT();
  const { data: goals } = useGoals();
  const [goalId, setGoalId] = useState<string | undefined>();
  const [scenarioId, setScenarioId] = useState<string | undefined>();
  const { data: scenarios } = useScenarios(goalId);
  const { data: runtimeCatalog } = useRuntimeCatalog();
  const [modelId, setModelId] = useState<string | undefined>();

  // Auto-bind the primary goal on first load — if the user hasn't picked
  // one yet (no localStorage override, no URL param), default to the first
  // goal in the list. Same for the scenario: when a goal is bound and
  // scenarios are loaded, auto-select the first active scenario as the
  // "default scenario" so the intelligent assistant has context to work with.
  // The user can still switch or clear via the selectors.
  useEffect(() => {
    if (goalId || !goals) return;
    const list = goals as any[];
    if (list.length === 0) return;
    setGoalId(list[0].id);
  }, [goals, goalId]);

  useEffect(() => {
    if (scenarioId || !goalId || !scenarios) return;
    const list = scenarios as any[];
    if (list.length === 0) return;
    // Prefer the first active scenario as the "default"
    const active = list.find((s) => s.status === "active") ?? list[0];
    setScenarioId(active.id);
  }, [scenarios, goalId, scenarioId]);

  // Subscribe to the chat store so the title bar re-renders when the
  // active conversation changes (new conversation selected, first message
  // auto-titled, etc.). Previously this lived inside ChatPanel's toolbar.
  const state = useChatStore();
  const activeConv = getActiveConversation();

  useEffect(() => {
    if (!runtimeCatalog || modelId) return;
    const saved = activeConv?.id
      ? window.localStorage.getItem(`lifetree.chat.model.${activeConv.id}`)
      : null;
    setModelId(saved || runtimeCatalog.role_assignments.chat);
  }, [activeConv?.id, modelId, runtimeCatalog]);

  const handleModelChange = useCallback((nextModelId: string) => {
    setModelId(nextModelId);
    if (activeConv?.id) {
      window.localStorage.setItem(`lifetree.chat.model.${activeConv.id}`, nextModelId);
    }
  }, [activeConv?.id]);

  // Ref to the conversation-list search input — used by the ⌘K shortcut
  // to focus the search box without requiring a mouse click.
  const searchInputRef = useRef<HTMLInputElement>(null);

  // Sidebar collapse — persisted across reloads. Defaults to collapsed
  // (hidden) so the chat area gets maximum space on first visit. The
  // user can expand it via the History button; their choice is then
  // remembered across reloads.
  const [collapsed, setCollapsed] = useState(true);
  const drawerMode = useSidebarDrawerMode();
  // In drawer mode (PWA or narrow viewport) the conversation history
  // sidebar is a drawer (hidden by default, opened via the History
  // button). Otherwise it's a persistent column that collapses to w-0.
  const [historyDrawerOpen, setHistoryDrawerOpen] = useState(false);

  const handleRename = useCallback(
    (title: string) => {
      if (!state.activeId) return;
      renameConversation(state.activeId, title.trim());
    },
    [state.activeId]
  );

  // New conversation — used by the toolbar button and the ⌘N shortcut.
  const handleNewChat = useCallback(() => {
    createConversation({ goalId, scenarioId, activate: true });
  }, [goalId, scenarioId]);

  // Focus the search input — used by the ⌘K shortcut. In drawer mode we
  // also need to open the drawer first so the input is visible.
  const handleFocusSearch = useCallback(() => {
    if (drawerMode) setHistoryDrawerOpen(true);
    // Defer focus until after the drawer animation starts so the input
    // is actually in the DOM and focusable.
    setTimeout(() => searchInputRef.current?.focus(), 50);
  }, [drawerMode]);

  useChatShortcuts({
    onNewChat: handleNewChat,
    onFocusSearch: handleFocusSearch,
  });

  useEffect(() => {
    if (typeof window === "undefined") return;
    // Only un-collapse if the user explicitly set it to "0" in a
    // previous session. Default (no stored value) stays collapsed.
    const v = window.localStorage.getItem(SIDEBAR_KEY);
    if (v === "0") setCollapsed(false);
  }, []);
  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(SIDEBAR_KEY, collapsed ? "1" : "0");
  }, [collapsed]);

  return (
    <div className="flex h-full relative">
      {/* Conversation history sidebar.
          - Drawer mode (PWA / narrow viewport): hidden by default;
            opens as a slide-in drawer via the History button.
          - Otherwise: persistent column that collapses to w-0. */}
      {drawerMode ? (
        <>
          {/* Drawer backdrop */}
          <div
            className={cn(
              "fixed inset-0 z-40 bg-black/60 backdrop-blur-sm transition-opacity duration-200",
              historyDrawerOpen
                ? "opacity-100 pointer-events-auto"
                : "opacity-0 pointer-events-none"
            )}
            onClick={() => setHistoryDrawerOpen(false)}
            aria-hidden="true"
          />
          {/* Drawer */}
          <aside
            className={cn(
              "fixed inset-y-0 left-0 z-50 w-72 max-w-[85vw]",
              "bg-[#0d1015] border-r border-white/5 shadow-2xl",
              "transition-transform duration-300 ease-out",
              "safe-top safe-bottom",
              historyDrawerOpen ? "translate-x-0" : "-translate-x-full"
            )}
          >
            <ConversationList
              goalId={goalId}
              scenarioId={scenarioId}
              searchInputRef={searchInputRef}
            />
          </aside>
        </>
      ) : (
        <aside
          className={cn(
            "sidebar-rail shrink-0 transition-[width] duration-300 ease-out overflow-hidden border-r border-white/5",
            collapsed ? "w-0" : "w-64 sm:w-72"
          )}
          aria-hidden={collapsed}
        >
          {!collapsed && (
            <ConversationList
              goalId={goalId}
              scenarioId={scenarioId}
              searchInputRef={searchInputRef}
            />
          )}
        </aside>
      )}

      {/* Main chat column */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top title bar — sidebar toggle + advisor label + editable
            conversation title on the left, goal/scenario selectors on
            the right. Migrated here from ChatPanel's internal toolbar. */}
        <div className="flex items-center justify-between gap-3 px-4 py-2 border-b border-white/5 bg-surface/30 backdrop-blur-sm shrink-0">
          <div className="flex items-center gap-2 min-w-0 flex-1">
            <SidebarToggleButton />
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 shrink-0"
              onClick={() =>
                drawerMode
                  ? setHistoryDrawerOpen((v) => !v)
                  : setCollapsed((v) => !v)
              }
              title={
                drawerMode
                  ? t("chat.history.expand")
                  : collapsed
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
            <ChatModelSelector
              catalog={runtimeCatalog}
              value={modelId}
              onValueChange={handleModelChange}
            />
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
            <Button
              variant="outline"
              size="sm"
              className="h-8 gap-1.5 text-xs shrink-0"
              onClick={handleNewChat}
              title={t("chatPage.newChat")}
            >
              <Plus className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">{t("chatPage.newChat")}</span>
            </Button>
          </div>
        </div>

        {/* Chat fills remaining vertical space */}
        <div className="flex-1 min-h-0">
          <ChatPanel
            goalId={goalId}
            scenarioId={scenarioId}
            modelId={modelId}
          />
        </div>
      </div>
    </div>
  );
}
