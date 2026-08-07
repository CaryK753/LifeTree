/**
 * Client-side chat conversation store.
 *
 * Each conversation is a self-contained record with:
 *   - id (uuid)
 *   - title (auto-generated after first user message)
 *   - goalId? / scenarioId? (context, locked at creation)
 *   - messages[]
 *   - createdAt / updatedAt
 *
 * All conversations are persisted to localStorage under CONVERSATIONS_KEY.
 * The active conversation id is persisted under ACTIVE_KEY so a page reload
 * reopens the same conversation.
 *
 * The store is framework-agnostic; React components subscribe via the
 * `useChatStore` hook (uses useSyncExternalStore for cheap, tear-free reads).
 */

import { useSyncExternalStore } from "react";
import { api, streamChat, resumeChatStream, type ChatChunk } from "@/lib/api";

// ---------- Types ----------

export interface ToolCall {
  id: string;
  name: string;
  args: Record<string, unknown>;
  result: unknown | null;
  startedAt: number;
  endedAt?: number;
  error?: string;
  /**
   * Character offset into `message.content` at the moment this tool call
   * was invoked during streaming. Used by the renderer to interleave
   * tool calls inline with the text body (text → tool → text → tool → …)
   * instead of dumping them all at the top or bottom.
   *
   * Optional for backward compatibility with older persisted messages;
   * when absent, the renderer falls back to appending the tool call
   * after the full body.
   */
  contentOffset?: number;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  reasoning?: string; // chain-of-thought (if model emits it)
  toolCalls?: ToolCall[];
  attachments?: {
    filename: string;
    sourceId: string;
    mime: string;
    isImage: boolean;
    previewUrl?: string;
  }[];
  streaming?: boolean;
  /**
   * Persistent stream ID assigned by the backend. When non-null, this
   * assistant message is backed by a ``ChatStream`` row that continues
   * running in the background even if the browser tab is closed.
   *
   * On page reload, the chat panel checks for messages with
   * ``streaming: true`` and a non-empty ``streamId``, then calls
   * ``resumeChatStream(streamId)`` to reconnect and pick up where the
   * stream left off.
   */
  streamId?: string;
  createdAt: number;
  /**
   * Previous assistant replies for the same user message.
   * Populated by `retryAssistant` when the user clicks "重试" on an
   * assistant message — the previous reply is preserved here (newest
   * first) instead of being discarded, so the user can flip through
   * alternative responses to the same prompt.
   *
   * Also used for user messages: when the user edits their own message,
   * the previous content is preserved here so they can flip back.
   */
  previousVersions?: PreviousReply[];
}

export interface PreviousReply {
  content: string;
  reasoning?: string;
  toolCalls?: ToolCall[];
  createdAt: number;
}

export interface Conversation {
  id: string;
  title: string;
  goalId?: string;
  scenarioId?: string;
  messages: ChatMessage[];
  createdAt: number;
  updatedAt: number;
}

// ---------- Constants ----------

/**
 * Conversation storage is namespaced by user id so that multiple users
 * sharing the same browser don't see each other's chats.
 *
 *   lifetree.chat.conversations.v2.<userId>
 *   lifetree.chat.activeId.v2.<userId>
 *
 * Before login, the scope falls back to ``"default"``. The legacy unscoped keys
 * (``lifetree.chat.conversations.v2``) are migrated to the ``default``
 * scope on first load so existing single-user deployments keep their
 * chat history.
 */
const LEGACY_CONVERSATIONS_KEY = "lifetree.chat.conversations.v2";
const LEGACY_ACTIVE_KEY = "lifetree.chat.activeId.v2";
const STORAGE_PREFIX = "lifetree.chat";
const DEFAULT_SCOPE = "default";
const TITLE_GEN_THRESHOLD = 1; // generate title after first user-assistant pair

/** Current user scope. ``null`` → ``"default"`` (single-user / not logged in). */
let currentScope: string = DEFAULT_SCOPE;

function conversationsKey(scope: string = currentScope): string {
  return `${STORAGE_PREFIX}.conversations.v2.${scope}`;
}

function activeKey(scope: string = currentScope): string {
  return `${STORAGE_PREFIX}.activeId.v2.${scope}`;
}

/**
 * Switch the active user scope. Saves the current state to the old
 * scope's keys, loads from the new scope's keys, and emits so React
 * components re-render with the new user's conversations.
 *
 * Safe to call with the same scope repeatedly (no-op).
 */
export function setChatUserScope(userId: string | null): void {
  const next = userId || DEFAULT_SCOPE;
  if (next === currentScope) return;
  // Persist current state under the OLD scope before switching.
  persist();
  currentScope = next;
  // Load from the NEW scope.
  state = load();
  emit();
}

// ---------- Utility ----------

function uid(): string {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

function now(): number {
  return Date.now();
}

function safeReadJSON<T>(key: string, fallback: T): T {
  if (typeof window === "undefined") return fallback;
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function safeWriteJSON(key: string, value: unknown) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Quota / private mode — ignore.
  }
}

/**
 * Generate a short title for a conversation based on its first user message.
 * Uses the chat model via a non-streaming API call; falls back to a truncated
 * copy of the user message if the model is unavailable or errors out.
 */
async function generateTitle(firstUserMessage: string): Promise<string> {
  const fallback = firstUserMessage.slice(0, 40).trim() || "New Chat";
  try {
    // We piggyback on the streaming endpoint with a one-shot prompt; the
    // server returns SSE chunks but we just concatenate the deltas.
    let acc = "";
    const stream = streamChat({
      messages: [
        {
          role: "user",
          content:
            "Summarize the following user message as a very short conversation title (max 6 words, no quotes, no punctuation at the end). Reply with the title only.\n\nUser message:\n" +
            firstUserMessage.slice(0, 500),
        },
      ],
      // Title generation is ephemeral — no need to persist a ChatStream
      // record or support reconnection.
      persist: false,
    });
    for await (const chunk of stream as AsyncGenerator<ChatChunk>) {
      if (chunk.delta) acc += chunk.delta;
      if (chunk.finish_reason) break;
    }
    const cleaned = acc.replace(/^["'\s]+|["'\s]+$/g, "").slice(0, 60);
    return cleaned || fallback;
  } catch {
    return fallback;
  }
}

// ---------- Store ----------

interface StoreState {
  conversations: Conversation[];
  activeId: string | null;
}

let state: StoreState = { conversations: [], activeId: null };
const listeners = new Set<() => void>();

function setState(next: StoreState) {
  state = next;
  persist();
  emit();
}

function emit() {
  for (const l of listeners) l();
}

function persist() {
  safeWriteJSON(conversationsKey(), state.conversations);
  if (state.activeId) {
    safeWriteJSON(activeKey(), state.activeId);
  } else if (typeof window !== "undefined") {
    window.localStorage.removeItem(activeKey());
  }
}

function load(): StoreState {
  // One-time migration: if the scoped keys don't exist yet but the
  // legacy unscoped keys do, copy them over so existing single-user
  // deployments keep their chat history.
  if (typeof window !== "undefined" && currentScope === DEFAULT_SCOPE) {
    const scopedConv = window.localStorage.getItem(conversationsKey());
    if (scopedConv === null) {
      const legacyConv = window.localStorage.getItem(LEGACY_CONVERSATIONS_KEY);
      const legacyActive = window.localStorage.getItem(LEGACY_ACTIVE_KEY);
      if (legacyConv !== null) {
        window.localStorage.setItem(conversationsKey(), legacyConv);
        if (legacyActive !== null) {
          window.localStorage.setItem(activeKey(), legacyActive);
        }
      }
    }
  }

  const conversations = safeReadJSON<Conversation[]>(conversationsKey(), []);
  const activeId = safeReadJSON<string | null>(activeKey(), null);
  // Handle half-finished streaming messages from a previous session.
  //
  // Messages with a ``streamId`` are backed by a persistent ChatStream on
  // the backend — keep them in ``streaming: true`` state so the chat panel
  // can resume them via ``resumeChatStream(streamId)`` on mount. The
  // content accumulated so far is preserved (it was written to localStorage
  // on the final patch before the page closed).
  //
  // Messages without a ``streamId`` are from the old (pre-background-task)
  // streaming model where the generation died with the tab — finalize them
  // and remove empty placeholders.
  for (const c of conversations) {
    for (const m of c.messages) {
      if (m.streaming && !m.streamId) {
        m.streaming = false;
        if (!m.content && (m.toolCalls?.length ?? 0) === 0) {
          // Empty assistant placeholder from a crashed stream — remove it.
          c.messages = c.messages.filter((x) => x.id !== m.id);
        }
      }
    }
  }
  return { conversations, activeId };
}

// Initialize from localStorage on the client.
if (typeof window !== "undefined") {
  state = load();
}

// ---------- Public actions ----------

export function listConversations(): Conversation[] {
  return [...state.conversations].sort((a, b) => b.updatedAt - a.updatedAt);
}

export function getActiveConversation(): Conversation | null {
  if (!state.activeId) return null;
  return state.conversations.find((c) => c.id === state.activeId) ?? null;
}

export function createConversation(opts?: {
  goalId?: string;
  scenarioId?: string;
  activate?: boolean;
}): Conversation {
  const conv: Conversation = {
    id: uid(),
    title: "", // will be filled in after the first exchange
    goalId: opts?.goalId,
    scenarioId: opts?.scenarioId,
    messages: [],
    createdAt: now(),
    updatedAt: now(),
  };
  const next = {
    conversations: [conv, ...state.conversations],
    activeId: opts?.activate === false ? state.activeId : conv.id,
  };
  setState(next);
  return conv;
}

export function selectConversation(id: string) {
  setState({ ...state, activeId: id });
}

export function renameConversation(id: string, title: string) {
  const conversations = state.conversations.map((c) =>
    c.id === id ? { ...c, title: title.slice(0, 100), updatedAt: now() } : c
  );
  setState({ ...state, conversations });
}

export function deleteConversation(id: string) {
  const conversations = state.conversations.filter((c) => c.id !== id);
  const activeId =
    state.activeId === id ? (conversations[0]?.id ?? null) : state.activeId;
  setState({ conversations, activeId });
}

export function clearAllConversations() {
  setState({ conversations: [], activeId: null });
}

/**
 * Export a conversation to a downloadable format.
 *
 * - ``markdown``: human-readable transcript with role headers. Good for
 *   sharing or pasting into a note.
 * - ``json``: full structured data including tool calls, attachments,
 *   and previousVersions. Good for backup or re-import.
 *
 * Returns the serialized string; the caller is responsible for triggering
 * the browser download (e.g. via a Blob + anchor click).
 */
export function exportConversation(
  convId: string,
  format: "markdown" | "json"
): string | null {
  const conv = state.conversations.find((c) => c.id === convId);
  if (!conv) return null;

  if (format === "json") {
    return JSON.stringify(conv, null, 2);
  }

  // Markdown transcript
  const lines: string[] = [];
  const title = conv.title?.trim() || "Untitled";
  lines.push(`# ${title}`);
  lines.push("");
  lines.push(`> Exported from LifeTree on ${new Date().toISOString()}`);
  lines.push("");

  for (const m of conv.messages) {
    const role = m.role === "user" ? "🧑 You" : "🤖 AI Advisor";
    const time = new Date(m.createdAt).toLocaleString();
    lines.push(`## ${role}`);
    lines.push(`*${time}*`);
    lines.push("");
    lines.push(m.content || "(empty)");
    if (m.toolCalls && m.toolCalls.length > 0) {
      lines.push("");
      lines.push("**Tool calls:**");
      for (const tc of m.toolCalls) {
        lines.push(`- \`${tc.name}\``);
      }
    }
    lines.push("");
  }

  return lines.join("\n");
}

/**
 * Delete a single message from a conversation.
 */
export function deleteMessage(convId: string, messageId: string) {
  const conversations = state.conversations.map((c) =>
    c.id === convId
      ? {
          ...c,
          messages: c.messages.filter((m) => m.id !== messageId),
          updatedAt: now(),
        }
      : c
  );
  setState({ ...state, conversations });
}

/**
 * Delete a single version of an assistant message.
 *
 * - If `versionIndex === 0` (the current/newest reply) and there are
 *   previous versions, the most recent previous version is promoted to
 *   be the current reply (its content/reasoning/toolCalls move into
 *   `message.content` etc.) and is removed from `previousVersions`.
 * - If `versionIndex === 0` and there are NO previous versions, the
 *   entire message is deleted (delegates to `deleteMessage`).
 * - If `versionIndex > 0`, that entry is removed from `previousVersions`
 *   and the current reply is untouched.
 *
 * Returns true if the message still exists after the operation (false if
 * the whole message was deleted).
 */
export function deleteAssistantVersion(
  convId: string,
  messageId: string,
  versionIndex: number
): boolean {
  let messageStillExists = true;

  const conversations = state.conversations.map((c) => {
    if (c.id !== convId) return c;
    const idx = c.messages.findIndex((m) => m.id === messageId);
    if (idx < 0) return c;
    const msg = c.messages[idx];
    if (msg.role !== "assistant") return c;

    const prevVersions = msg.previousVersions ?? [];

    if (versionIndex === 0) {
      // Deleting the current reply.
      if (prevVersions.length === 0) {
        // No history — delete the whole message.
        messageStillExists = false;
        return {
          ...c,
          messages: c.messages.filter((m) => m.id !== messageId),
          updatedAt: now(),
        };
      }
      // Promote the most recent previous version to current.
      const [promoted, ...rest] = prevVersions;
      const updated: ChatMessage = {
        ...msg,
        content: promoted.content,
        reasoning: promoted.reasoning,
        toolCalls: promoted.toolCalls,
        previousVersions: rest,
      };
      const messages = [...c.messages];
      messages[idx] = updated;
      return { ...c, messages, updatedAt: now() };
    }

    // versionIndex > 0: remove that historical entry.
    const newPrev = prevVersions.filter((_, i) => i !== versionIndex - 1);
    const updated: ChatMessage = {
      ...msg,
      previousVersions: newPrev,
    };
    const messages = [...c.messages];
    messages[idx] = updated;
    return { ...c, messages, updatedAt: now() };
  });

  setState({ ...state, conversations });
  return messageStillExists;
}

/**
 * Remove all messages after (but not including) the given message id.
 * Used by the "retry" action: drop the assistant reply and any subsequent
 * messages, then re-stream from the given message (typically the user
 * message whose reply we want to regenerate).
 *
 * Returns the messages that were kept (including the target message) so
 * the caller can build the API payload.
 */
export function truncateAfterMessage(
  convId: string,
  messageId: string
): ChatMessage[] | null {
  let kept: ChatMessage[] | null = null;
  const conversations = state.conversations.map((c) => {
    if (c.id !== convId) return c;
    const idx = c.messages.findIndex((m) => m.id === messageId);
    if (idx < 0) return c;
    kept = c.messages.slice(0, idx + 1);
    return { ...c, messages: kept, updatedAt: now() };
  });
  setState({ ...state, conversations });
  return kept;
}

/**
 * Retry an assistant message while preserving the previous reply.
 *
 * The old assistant message (at `assistantId`) is collapsed into a
 * `previousVersions` entry on the new placeholder — the user can flip
 * through earlier responses to the same user prompt instead of losing
 * them. Any messages after the assistant message are also dropped.
 *
 * Returns the new assistant placeholder id (so the caller can stream
 * into it), or null if the assistant message or its preceding user
 * message can't be found.
 */
export function retryAssistant(
  convId: string,
  assistantId: string
): { assistantId: string; userApiContent?: string } | null {
  let newAssistantId: string | null = null;
  let userApiContent: string | undefined;

  const conversations = state.conversations.map((c) => {
    if (c.id !== convId) return c;
    const idx = c.messages.findIndex((m) => m.id === assistantId);
    if (idx < 0) return c;
    const prevUser = c.messages[idx - 1];
    if (!prevUser || prevUser.role !== "user") return c;
    const oldAssistant = c.messages[idx];

    // Build the previous-reply snapshot (only if it had real content).
    const prevSnapshot: PreviousReply | null =
      oldAssistant.content || (oldAssistant.toolCalls?.length ?? 0) > 0
        ? {
            content: oldAssistant.content,
            reasoning: oldAssistant.reasoning,
            toolCalls: oldAssistant.toolCalls,
            createdAt: oldAssistant.createdAt,
          }
        : null;

    // Merge any earlier previousVersions (in order) so history is retained
    // across multiple retries — newest first.
    const previousVersions: PreviousReply[] = [
      ...(prevSnapshot ? [prevSnapshot] : []),
      ...(oldAssistant.previousVersions ?? []),
    ];

    newAssistantId = uid();
    const newAssistant: ChatMessage = {
      id: newAssistantId,
      role: "assistant",
      content: "",
      streaming: true,
      createdAt: now(),
      previousVersions,
    };

    // Augment the user message content with attachment refs (if any) so
    // the caller doesn't have to rebuild it.
    userApiContent =
      prevUser.attachments && prevUser.attachments.length > 0
        ? `${prevUser.content}\n\n${prevUser.attachments
            .map((a) => `[attachment:${a.filename}|source:${a.sourceId}]`)
            .join("\n")}`
        : prevUser.content;

    // Keep everything up to (and including) the previous user message,
    // then append the new assistant placeholder with the history attached.
    const kept = c.messages.slice(0, idx);
    return {
      ...c,
      messages: [...kept, newAssistant],
      updatedAt: now(),
    };
  });
  setState({ ...state, conversations });
  if (!newAssistantId) return null;
  return { assistantId: newAssistantId, userApiContent };
}

/**
 * Edit a user message in-place, preserving the previous content as a
 * `previousVersions` entry (mirroring the assistant retry pattern).
 *
 * After editing the user message, any messages after it (including the
 * old assistant reply) are truncated — the caller is expected to re-stream
 * a fresh assistant reply. Returns the kept messages (ending with the
 * edited user message) so the caller can build the API payload, or null
 * if the message wasn't found.
 */
export function editUserMessage(
  convId: string,
  messageId: string,
  newContent: string
): ChatMessage[] | null {
  let kept: ChatMessage[] | null = null;
  const conversations = state.conversations.map((c) => {
    if (c.id !== convId) return c;
    const idx = c.messages.findIndex((m) => m.id === messageId);
    if (idx < 0) return c;
    const old = c.messages[idx];
    if (old.role !== "user") return c;

    // Snapshot the old content (only if non-empty) so the user can flip
    // back to the original wording via the version navigator.
    const prevSnapshot: PreviousReply | null = old.content
      ? {
          content: old.content,
          createdAt: old.createdAt,
        }
      : null;
    const previousVersions: PreviousReply[] = [
      ...(prevSnapshot ? [prevSnapshot] : []),
      ...(old.previousVersions ?? []),
    ];

    const edited: ChatMessage = {
      ...old,
      content: newContent,
      createdAt: now(),
      previousVersions,
    };

    // Truncate everything after the edited user message — the caller
    // will push a fresh assistant placeholder and re-stream.
    kept = [...c.messages.slice(0, idx), edited];
    return { ...c, messages: kept, updatedAt: now() };
  });
  setState({ ...state, conversations });
  return kept;
}

/**
 * Append a user message to the active conversation (creating one if needed).
 * Returns the conversation id and the new message id so the caller can
 * stream the assistant reply.
 */
export function pushUserMessage(
  convId: string | null,
  content: string,
  attachments?: ChatMessage["attachments"],
  context?: { goalId?: string; scenarioId?: string }
): { convId: string; messageId: string } {
  let conv: Conversation | undefined;
  if (convId) {
    conv = state.conversations.find((c) => c.id === convId);
  }
  if (!conv) {
    conv = createConversation({
      goalId: context?.goalId,
      scenarioId: context?.scenarioId,
      activate: true,
    });
  }
  const messageId = uid();
  const userMsg: ChatMessage = {
    id: messageId,
    role: "user",
    content,
    attachments: attachments?.length ? attachments : undefined,
    createdAt: now(),
  };
  const conversations = state.conversations.map((c) =>
    c.id === conv!.id
      ? { ...c, messages: [...c.messages, userMsg], updatedAt: now() }
      : c
  );
  setState({ ...state, conversations });
  return { convId: conv.id, messageId };
}

/**
 * Append an empty assistant placeholder (streaming=true) and return its id.
 */
export function pushAssistantPlaceholder(convId: string): string {
  const messageId = uid();
  const conversations = state.conversations.map((c) =>
    c.id === convId
      ? {
          ...c,
          messages: [
            ...c.messages,
            {
              id: messageId,
              role: "assistant" as const,
              content: "",
              streaming: true,
              createdAt: now(),
            },
          ],
          updatedAt: now(),
        }
      : c
  );
  setState({ ...state, conversations });
  return messageId;
}

/**
 * Patch a specific message in a conversation. Used for streaming token
 * appends, tool-call updates, and finalizing streaming state.
 *
 * Streaming performance note: when the patched message remains in
 * `streaming: true` state, we skip the localStorage write — serializing
 * the entire conversations array on every token would block the main
 * thread and make the typewriter effect appear batched/non-streaming.
 * Persistence is restored the moment a patch lands with `streaming: false`.
 */
export function patchMessage(
  convId: string,
  messageId: string,
  patch: Partial<ChatMessage> | ((m: ChatMessage) => Partial<ChatMessage>)
) {
  let stillStreaming = false;
  const conversations = state.conversations.map((c) => {
    if (c.id !== convId) return c;
    const messages = c.messages.map((m) => {
      if (m.id !== messageId) return m;
      const p = typeof patch === "function" ? patch(m) : patch;
      const merged = { ...m, ...p };
      if (merged.streaming) stillStreaming = true;
      return merged;
    });
    return { ...c, messages, updatedAt: now() };
  });
  state = { ...state, conversations };
  // Skip the expensive localStorage write while streaming; persist only on
  // the final patch (and on any non-streaming patch).
  if (!stillStreaming) {
    persist();
  }
  emit();
}

/**
 * Add or update a tool call on a message. If `toolId` matches an existing
 * tool call, it is updated; otherwise a new one is appended.
 *
 * `contentOffset` is only meaningful on first insertion (when the tool
 * call is invoked during streaming) and is preserved on subsequent
 * updates (e.g. when the result arrives).
 */
export function upsertToolCall(
  convId: string,
  messageId: string,
  tool: { id: string; name: string; args?: Record<string, unknown>; result?: unknown; error?: string; endedAt?: number; contentOffset?: number }
) {
  patchMessage(convId, messageId, (m) => {
    const calls = [...(m.toolCalls ?? [])];
    const idx = calls.findIndex((c) => c.id === tool.id);
    if (idx >= 0) {
      // Preserve the original contentOffset — the offset is set when the
      // tool call is first invoked and never changes afterward.
      calls[idx] = { ...calls[idx], ...tool };
    } else {
      calls.push({
        id: tool.id,
        name: tool.name,
        args: tool.args ?? {},
        result: tool.result ?? null,
        startedAt: Date.now(),
        endedAt: tool.endedAt,
        error: tool.error,
        contentOffset: tool.contentOffset,
      });
    }
    return { toolCalls: calls };
  });
}

/**
 * After the first user→assistant exchange, if the conversation is still
 * untitled, ask the chat model for a title and persist it.
 */
export async function maybeAutoTitle(convId: string) {
  const conv = state.conversations.find((c) => c.id === convId);
  if (!conv || conv.title) return;
  const userMsgs = conv.messages.filter((m) => m.role === "user");
  if (userMsgs.length < TITLE_GEN_THRESHOLD) return;
  const title = await generateTitle(userMsgs[0].content);
  renameConversation(convId, title);
}

// ---------- React binding ----------

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot(): StoreState {
  return state;
}

export function useChatStore(): StoreState {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

// Re-export api for components that need direct access
export { api, streamChat, resumeChatStream };
