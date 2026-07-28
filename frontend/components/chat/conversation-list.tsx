"use client";

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  Plus,
  Search,
  Trash2,
  Pencil,
  Check,
  X,
  MoreHorizontal,
  Download,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";
import { useConfirm } from "@/components/ui/confirm-dialog";
import {
  useChatStore,
  listConversations,
  selectConversation,
  renameConversation,
  deleteConversation,
  createConversation,
  clearAllConversations,
  exportConversation,
  type Conversation,
} from "@/lib/chat-store";

interface Props {
  goalId?: string;
  scenarioId?: string;
  onPick?: () => void;
  /** Ref to the search input — exposed so the parent can focus it via ⌘K. */
  searchInputRef?: React.RefObject<HTMLInputElement | null>;
}

/**
 * Conversation history sidebar.
 *
 * Lists all conversations sorted by updatedAt desc, grouped by relative date
 * (today / yesterday / this week / earlier). Supports:
 *   - New conversation
 *   - Click to switch
 *   - Inline rename (Enter to save, Esc to cancel)
 *   - Delete with confirm
 *   - Clear all
 *   - Export (Markdown / JSON)
 *   - Full-text search across all messages
 *
 * The sidebar reads from the global chat-store (useSyncExternalStore) so any
 * change — including new messages streamed in by the chat panel — is
 * reflected immediately.
 */
export function ConversationList({ goalId, scenarioId, onPick, searchInputRef }: Props) {
  const t = useT();
  const state = useChatStore();
  const { confirm, ConfirmRoot } = useConfirm();
  const [query, setQuery] = useState("");
  const [menuOpenFor, setMenuOpenFor] = useState<string | null>(null);
  const [renameId, setRenameId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  // Defer localStorage-derived data until after hydration to avoid SSR mismatch.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const all = useMemo(() => listConversations(), [state]);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return all;
    // Search across title AND all message contents (user + assistant).
    // The previous implementation only matched the title and the first
    // user message, which made it impossible to find a conversation by
    // something the AI said. Searching all messages is cheap because
    // conversations live in localStorage and the typical user has < 1000.
    return all.filter((c) => {
      const title = c.title.toLowerCase();
      if (title.includes(q)) return true;
      // Search all messages — both user and assistant content.
      for (const m of c.messages) {
        if (m.content?.toLowerCase().includes(q)) return true;
      }
      return false;
    });
  }, [all, query, state]);

  const groups = useMemo(() => groupByDate(filtered), [filtered, state]);

  const handleNew = () => {
    createConversation({ goalId, scenarioId, activate: true });
    onPick?.();
  };

  const handleSelect = (id: string) => {
    selectConversation(id);
    onPick?.();
  };

  const startRename = (c: Conversation) => {
    setRenameId(c.id);
    setRenameValue(c.title || "");
    setMenuOpenFor(null);
  };

  const commitRename = () => {
    if (renameId) {
      const v = renameValue.trim();
      if (v) renameConversation(renameId, v);
    }
    setRenameId(null);
    setRenameValue("");
  };

  const cancelRename = () => {
    setRenameId(null);
    setRenameValue("");
  };

  const handleDelete = async (c: Conversation) => {
    setMenuOpenFor(null);
    const ok = await confirm({
      title: t("common.delete"),
      description: t("chat.history.confirmDelete"),
      confirmLabel: t("common.delete"),
      cancelLabel: t("common.cancel"),
      variant: "danger",
    });
    if (ok) {
      deleteConversation(c.id);
    }
  };

  const handleClearAll = async () => {
    if (all.length === 0) return;
    const ok = await confirm({
      title: t("chat.history.clearAll"),
      description: t("chat.history.clearAllConfirm"),
      confirmLabel: t("common.confirm"),
      cancelLabel: t("common.cancel"),
      variant: "danger",
    });
    if (ok) {
      clearAllConversations();
    }
  };

  /**
   * Trigger a browser download of the conversation in the chosen format.
   * Uses a Blob + temporary anchor so it works without any backend round-trip.
   */
  const handleExport = (conv: Conversation, format: "markdown" | "json") => {
    const content = exportConversation(conv.id, format);
    if (!content) return;
    const blob = new Blob([content], {
      type: format === "json" ? "application/json" : "text/markdown",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    const safeTitle = (conv.title?.trim() || "conversation").replace(
      /[^a-zA-Z0-9_-]/g,
      "_"
    );
    a.download = `${safeTitle}.${format === "json" ? "json" : "md"}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex flex-col h-full bg-surface/30 border-r border-white/5">
      {/* Header */}
      <div className="px-3 py-3 border-b border-white/5 shrink-0 space-y-2">
        <div className="flex items-center justify-between">
          <div className="text-[11px] uppercase tracking-wider text-zinc-500 font-semibold">
            {t("chat.history.title")}
          </div>
          <div className="text-[10px] text-zinc-600">
            {mounted ? t("chat.history.count", { n: all.length }) : ""}
          </div>
        </div>
        <button
          type="button"
          onClick={handleNew}
          className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md text-xs font-medium text-brand-200 bg-brand-500/10 hover:bg-brand-500/20 border border-brand-500/30 transition-colors"
        >
          <Plus className="h-3.5 w-3.5" />
          {t("chat.history.new")}
        </button>
        {/* Search */}
        <div className="relative">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-zinc-500" />
          <input
            ref={searchInputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("chat.history.searchPlaceholder")}
            className="w-full pl-7 pr-2 py-1.5 text-xs bg-white/[0.03] border border-white/10 rounded-md text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:ring-1 focus:ring-brand-500/40 focus:border-brand-500/30"
          />
        </div>
      </div>

      {/* List — deferred until mounted to avoid SSR/localStorage mismatch */}
      <div className="flex-1 overflow-y-auto py-1.5">
        {!mounted ? (
          <div className="px-3 py-6 text-center text-xs text-zinc-700">…</div>
        ) : filtered.length === 0 ? (
          <div className="px-3 py-6 text-center text-xs text-zinc-600">
            {query ? t("chat.history.noResults") : t("chat.history.empty")}
          </div>
        ) : (
          groups.map((group) => (
            <div key={group.label} className="mb-1.5">
              <div className="px-3 py-1 text-[10px] uppercase tracking-wider text-zinc-600 font-medium">
                {group.label}
              </div>
              {group.items.map((c) => (
                <ConversationRow
                  key={c.id}
                  conv={c}
                  active={c.id === state.activeId}
                  renaming={renameId === c.id}
                  renameValue={renameValue}
                  menuOpen={menuOpenFor === c.id}
                  onPick={() => handleSelect(c.id)}
                  onMenuToggle={() =>
                    setMenuOpenFor((cur) => (cur === c.id ? null : c.id))
                  }
                  onRenameStart={() => startRename(c)}
                  onRenameChange={setRenameValue}
                  onRenameCommit={commitRename}
                  onRenameCancel={cancelRename}
                  onDelete={() => handleDelete(c)}
                  onExport={(fmt) => handleExport(c, fmt)}
                />
              ))}
            </div>
          ))
        )}
      </div>

      {/* Footer — clear all */}
      {all.length > 0 && (
        <div className="px-3 py-2 border-t border-white/5 shrink-0">
          <button
            type="button"
            onClick={handleClearAll}
            className="w-full flex items-center justify-center gap-1.5 px-2 py-1.5 rounded text-[11px] text-zinc-500 hover:text-red-300 hover:bg-red-500/5 transition-colors"
          >
            <Trash2 className="h-3 w-3" />
            {t("chat.history.clearAll")}
          </button>
        </div>
      )}
      {ConfirmRoot}
    </div>
  );
}

interface RowProps {
  conv: Conversation;
  active: boolean;
  renaming: boolean;
  renameValue: string;
  menuOpen: boolean;
  onPick: () => void;
  onMenuToggle: () => void;
  onRenameStart: () => void;
  onRenameChange: (v: string) => void;
  onRenameCommit: () => void;
  onRenameCancel: () => void;
  onDelete: () => void;
  onExport: (format: "markdown" | "json") => void;
}

/**
 * Tiny helper that listens for the Escape key while mounted and calls
 * `onClose`. Used by the conversation-row dropdown menu so it closes
 * on ESC the same way a Radix Dialog would.
 */
function DropdownEscCloser({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return null;
}

function ConversationRow({
  conv,
  active,
  renaming,
  renameValue,
  menuOpen,
  onPick,
  onMenuToggle,
  onRenameStart,
  onRenameChange,
  onRenameCommit,
  onRenameCancel,
  onDelete,
  onExport,
}: RowProps) {
  const t = useT();
  const title =
    conv.title?.trim() ||
    conv.messages.find((m) => m.role === "user")?.content?.slice(0, 40) ||
    t("chat.history.untitled");
  const lastMsg = conv.messages[conv.messages.length - 1];
  const lastPreview =
    lastMsg?.content?.slice(0, 60) ||
    (lastMsg?.toolCalls?.length
      ? t("chat.tool.called")
      : "");

  // Ref + layout state for the dropdown menu. In PWA drawer mode the
  // conversation list lives inside a fixed-position drawer with
  // overflow-y-auto, so an absolute-positioned menu would be clipped.
  // We render the menu via portal to document.body and compute its
  // position from the trigger button's bounding rect.
  const menuBtnRef = useRef<HTMLButtonElement>(null);
  const [menuPos, setMenuPos] = useState<{ top: number; left: number } | null>(null);
  useLayoutEffect(() => {
    if (!menuOpen || !menuBtnRef.current) {
      setMenuPos(null);
      return;
    }
    const rect = menuBtnRef.current.getBoundingClientRect();
    // Align the menu's right edge with the button's right edge, place
    // it just below the button. Clamp to viewport so it never overflows.
    const menuW = 128; // w-32
    const left = Math.max(8, Math.min(rect.right - menuW, window.innerWidth - menuW - 8));
    const top = Math.min(rect.bottom + 4, window.innerHeight - 100);
    setMenuPos({ top, left });
  }, [menuOpen]);

  if (renaming) {
    return (
      <div className="px-2 py-1.5 mx-1.5 rounded-md bg-white/[0.04] border border-brand-500/30">
        <input
          autoFocus
          type="text"
          value={renameValue}
          onChange={(e) => onRenameChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              onRenameCommit();
            } else if (e.key === "Escape") {
              e.preventDefault();
              onRenameCancel();
            }
          }}
          placeholder={t("chat.history.editTitlePlaceholder")}
          className="w-full px-2 py-1 text-xs bg-white/5 border border-white/10 rounded text-zinc-100 focus:outline-none focus:ring-1 focus:ring-brand-500/40"
        />
        <div className="flex items-center justify-end gap-1 mt-1">
          <button
            onClick={onRenameCommit}
            className="p-1 rounded text-emerald-300 hover:bg-emerald-500/10"
            title={t("chat.history.save")}
          >
            <Check className="h-3 w-3" />
          </button>
          <button
            onClick={onRenameCancel}
            className="p-1 rounded text-zinc-400 hover:bg-white/5"
            title={t("chat.history.cancel")}
          >
            <X className="h-3 w-3" />
          </button>
        </div>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "group relative mx-1.5 px-2.5 py-2 rounded-md cursor-pointer transition-colors",
        active
          ? "bg-brand-500/10 border border-brand-500/30"
          : "hover:bg-white/[0.04] border border-transparent"
      )}
      onClick={onPick}
    >
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div
            className={cn(
              "text-xs font-medium truncate",
              active ? "text-brand-700 dark:text-brand-200" : "text-zinc-800 dark:text-zinc-200"
            )}
          >
            {title}
          </div>
          {lastPreview && (
            <div className="text-[10px] text-zinc-500 dark:text-zinc-400 truncate mt-0.5">
              {lastPreview}
            </div>
          )}
          <div className="text-[10px] text-zinc-500 dark:text-zinc-500 mt-0.5">
            {t("chat.history.messageCount", { n: conv.messages.length })}
          </div>
        </div>
        {/* Action menu trigger */}
        <button
          ref={menuBtnRef}
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onMenuToggle();
          }}
          className={cn(
            "p-0.5 rounded text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200 hover:bg-black/5 dark:hover:bg-white/5 transition-opacity",
            menuOpen
              ? "opacity-100"
              : "opacity-0 group-hover:opacity-100"
          )}
          title={t("chat.history.rename")}
        >
          <MoreHorizontal className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Dropdown menu — rendered via portal to document.body so it
          escapes the PWA drawer's overflow-y-auto clipping. Position
          is computed from the trigger button's bounding rect. */}
      {menuOpen && menuPos && createPortal(
        <>
          {/* Click-away catcher + ESC handler. The catcher div closes
              the menu on outside click; the useEffect below closes it
              on Escape — same UX as a modal dialog. */}
          <DropdownEscCloser onClose={onMenuToggle} />
          <div
            className="fixed inset-0 z-30"
            data-conv-menu="true"
            onClick={(e) => {
              e.stopPropagation();
              onMenuToggle();
            }}
          />
          <div
            className="fixed z-[70] w-36 rounded-md border border-white/10 bg-surface shadow-lg shadow-black/40 py-1 text-xs"
            style={{ top: menuPos.top, left: menuPos.left }}
          >
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onRenameStart();
              }}
              className="w-full flex items-center gap-2 px-2.5 py-1.5 text-zinc-200 hover:bg-white/5"
            >
              <Pencil className="h-3 w-3" />
              {t("chat.history.rename")}
            </button>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onExport("markdown");
                onMenuToggle();
              }}
              className="w-full flex items-center gap-2 px-2.5 py-1.5 text-zinc-200 hover:bg-white/5"
            >
              <Download className="h-3 w-3" />
              {t("chat.export.markdown")}
            </button>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onExport("json");
                onMenuToggle();
              }}
              className="w-full flex items-center gap-2 px-2.5 py-1.5 text-zinc-200 hover:bg-white/5"
            >
              <Download className="h-3 w-3" />
              {t("chat.export.json")}
            </button>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onDelete();
              }}
              className="w-full flex items-center gap-2 px-2.5 py-1.5 text-red-300 hover:bg-red-500/10"
            >
              <Trash2 className="h-3 w-3" />
              {t("chat.history.delete")}
            </button>
          </div>
        </>,
        document.body
      )}
    </div>
  );
}

// ---------- Helpers ----------

interface DateGroup {
  label: string;
  items: Conversation[];
}

function groupByDate(items: Conversation[]): DateGroup[] {
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const startOfYesterday = startOfToday - 24 * 60 * 60 * 1000;
  const startOfWeek = startOfToday - 6 * 24 * 60 * 60 * 1000;

  const t = (k: string) => {
    // Use the global i18n dictionary directly via window? No — the function
    // runs outside React. Instead, read from the cookie-stored locale.
    const locale =
      (typeof document !== "undefined" &&
        document.cookie.match(/lifetree\.locale=([^;]+)/)?.[1]) ||
      "zh-CN";
    // Inline mini dictionary so this stays self-contained.
    const dict: Record<string, Record<string, string>> = {
      "zh-CN": {
        "chat.history.today": "今天",
        "chat.history.yesterday": "昨天",
        "chat.history.thisWeek": "本周",
        "chat.history.earlier": "更早",
      },
      "zh-TW": {
        "chat.history.today": "今天",
        "chat.history.yesterday": "昨天",
        "chat.history.thisWeek": "本週",
        "chat.history.earlier": "更早",
      },
      en: {
        "chat.history.today": "Today",
        "chat.history.yesterday": "Yesterday",
        "chat.history.thisWeek": "This week",
        "chat.history.earlier": "Earlier",
      },
      es: {
        "chat.history.today": "Hoy",
        "chat.history.yesterday": "Ayer",
        "chat.history.thisWeek": "Esta semana",
        "chat.history.earlier": "Antes",
      },
      de: {
        "chat.history.today": "Heute",
        "chat.history.yesterday": "Gestern",
        "chat.history.thisWeek": "Diese Woche",
        "chat.history.earlier": "Früher",
      },
      fr: {
        "chat.history.today": "Aujourd'hui",
        "chat.history.yesterday": "Hier",
        "chat.history.thisWeek": "Cette semaine",
        "chat.history.earlier": "Plus tôt",
      },
    };
    return dict[locale]?.[k] ?? dict["zh-CN"][k] ?? k;
  };

  const buckets: Record<string, Conversation[]> = {
    [t("chat.history.today")]: [],
    [t("chat.history.yesterday")]: [],
    [t("chat.history.thisWeek")]: [],
    [t("chat.history.earlier")]: [],
  };
  const order = [
    t("chat.history.today"),
    t("chat.history.yesterday"),
    t("chat.history.thisWeek"),
    t("chat.history.earlier"),
  ];

  for (const c of items) {
    const ts = c.updatedAt;
    let key: string;
    if (ts >= startOfToday) key = t("chat.history.today");
    else if (ts >= startOfYesterday) key = t("chat.history.yesterday");
    else if (ts >= startOfWeek) key = t("chat.history.thisWeek");
    else key = t("chat.history.earlier");
    buckets[key].push(c);
  }

  return order
    .filter((label) => buckets[label].length > 0)
    .map((label) => ({ label, items: buckets[label] }));
}
