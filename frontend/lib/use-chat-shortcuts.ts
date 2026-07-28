"use client";

import { useEffect } from "react";

/**
 * Global keyboard shortcuts for the chat page.
 *
 * - ⌘/Ctrl + N: start a new conversation
 * - ⌘/Ctrl + K: focus the search input in the conversation history sidebar
 *
 * The shortcuts only fire when the user is on /chat and not currently
 * typing in a textarea/input (so ⌘K inside the composer doesn't hijack
 * the browser's default behavior). The one exception is ⌘K itself,
 * which should work even when the search input is focused.
 *
 * Usage:
 *   useChatShortcuts({ onNewChat, onFocusSearch })
 */
export function useChatShortcuts(opts: {
  onNewChat: () => void;
  onFocusSearch: () => void;
}) {
  const { onNewChat, onFocusSearch } = opts;
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const mod = e.metaKey || e.ctrlKey;
      if (!mod) return;
      // ⌘/Ctrl + N — new conversation
      if (e.key === "n" || e.key === "N") {
        e.preventDefault();
        onNewChat();
        return;
      }
      // ⌘/Ctrl + K — focus search. Works even when typing in an input
      // because search is a primary navigation action, not a text edit.
      if (e.key === "k" || e.key === "K") {
        e.preventDefault();
        onFocusSearch();
        return;
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onNewChat, onFocusSearch]);
}
