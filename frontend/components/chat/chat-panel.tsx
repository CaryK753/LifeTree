"use client";

import { useState, useRef, useEffect, useCallback, useMemo, memo } from "react";
import {
  Send,
  Loader2,
  Paperclip,
  X,
  FileText,
  ImageIcon,
  Sparkles,
  RotateCcw,
  Trash2,
  Copy,
  Check,
  Square,
  ChevronLeft,
  ChevronRight,
  Pencil,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { api, streamChat } from "@/lib/api";
import { useT } from "@/lib/i18n/provider";
import { useUserProfile, useSettings } from "@/lib/hooks";
import { useToast } from "@/components/ui/toast";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from "@/components/ui/dialog";
import {
  ResponseContainer,
  ResponseMarkdown,
  ToolInvocation,
  ThinkingDots,
  Thread,
  Message,
  Composer,
  StreamingCursor,
} from "@/components/chat/ai-elements";
import {
  useChatStore,
  getActiveConversation,
  pushUserMessage,
  pushAssistantPlaceholder,
  patchMessage,
  upsertToolCall,
  maybeAutoTitle,
  createConversation,
  deleteMessage,
  deleteAssistantVersion,
  truncateAfterMessage,
  retryAssistant,
  editUserMessage,
  type ChatMessage,
  type ToolCall,
  type PreviousReply,
} from "@/lib/chat-store";
import { AIAvatar } from "@/components/common/ai-avatar";

interface Attachment {
  filename: string;
  sourceId: string;
  mime: string;
  isImage: boolean;
  previewUrl?: string;
}

interface Props {
  goalId?: string;
  scenarioId?: string;
}

function uid() {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export function ChatPanel({ goalId, scenarioId }: Props) {
  const t = useT();
  const state = useChatStore(); // re-renders on store changes
  const activeConv = getActiveConversation();
  const { data: userProfile } = useUserProfile();
  const { data: settings } = useSettings();
  const userAvatarUrl = (userProfile as { avatar_url?: string | null } | undefined)?.avatar_url ?? null;
  const toast = useToast();

  // Resolve the current chat model + provider so we can show the model's
  // brand icon (e.g. DeepSeek, OpenAI, Anthropic) as the AI avatar instead
  // of a generic sparkles icon.
  const chatModelInfo = useMemo(() => {
    const chatModelId = settings?.role_assignments?.["chat"];
    const chatModel = settings?.models?.find((m) => m.id === chatModelId);
    const chatProvider = chatModel
      ? settings?.providers?.find((p) => p.id === chatModel.provider_id)
      : undefined;
    return {
      protocol: chatProvider?.protocol as string | undefined,
      name: chatModel?.name as string | undefined,
    };
  }, [settings]);

  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const suggestions = useMemo(
    () => [t("chat.suggest1"), t("chat.suggest2"), t("chat.suggest3")],
    [t]
  );

  // Ensure there is an active conversation. If none, create one lazily on
  // first user message — but we still need an empty state UI here.
  const messages: ChatMessage[] = activeConv?.messages ?? [];

  // Auto-scroll on new messages or streaming updates.
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, state]);

  // Auto-focus the textarea on mount and when the active conversation changes.
  useEffect(() => {
    textareaRef.current?.focus();
  }, [state.activeId]);

  // Auto-resize textarea.
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${Math.min(
        textareaRef.current.scrollHeight,
        160
      )}px`;
    }
  }, [input]);

  const handleFile = useCallback(
    async (file: File) => {
      // Reject oversized uploads early — the backend limit is ~25 MB but
      // we cap at 20 MB on the client to leave headroom for multipart
      // encoding overhead. Avoids a slow failed POST that the user has
      // to wait for.
      const MAX_BYTES = 20 * 1024 * 1024;
      if (file.size > MAX_BYTES) {
        toast({
          title: t("error.uploadFailed", { msg: "" }),
          description: t("chat.error.fileTooLarge", { mb: 20 }),
          variant: "error",
        });
        return;
      }
      setUploading(true);
      try {
        const isImage = file.type.startsWith("image/");
        const result = await api.ingestUpload(file, {
          title: file.name,
          skip_llm: "true",
          source_kind: "user_upload",
        });
        const att: Attachment = {
          filename: file.name,
          sourceId: result.source_id,
          mime: file.type,
          isImage,
        };
        if (isImage) {
          att.previewUrl = URL.createObjectURL(file);
        }
        setAttachments((prev) => [...prev, att]);
      } catch (err) {
        console.error("upload failed", err);
        // Use toast instead of native alert() — keeps the UX consistent
        // with the rest of the app and doesn't block the main thread.
        toast({
          title: t("error.uploadFailed", { msg: "" }),
          description: (err as Error).message,
          variant: "error",
        });
      } finally {
        setUploading(false);
      }
    },
    [t, toast]
  );

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    files.forEach(handleFile);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const files = Array.from(e.dataTransfer.files ?? []);
    files.forEach(handleFile);
  };

  const removeAttachment = (sourceId: string) => {
    setAttachments((prev) => {
      const target = prev.find((a) => a.sourceId === sourceId);
      if (target?.previewUrl) URL.revokeObjectURL(target.previewUrl);
      return prev.filter((a) => a.sourceId !== sourceId);
    });
  };

  async function handleSend() {
    const trimmed = input.trim();
    if ((!trimmed && attachments.length === 0) || busy) return;

    // Ensure there is an active conversation. If none, create one bound to
    // the current goal/scenario context.
    let convId = state.activeId;
    if (!convId) {
      const conv = createConversation({
        goalId,
        scenarioId,
        activate: true,
      });
      convId = conv.id;
    }

    const userAtts = [...attachments];
    const finalContent =
      trimmed || t("chat.attachmentOnly");
    const finalAttachments = userAtts.length > 0 ? userAtts : undefined;

    // Push user message + empty assistant placeholder.
    pushUserMessage(convId, finalContent, finalAttachments, {
      goalId,
      scenarioId,
    });
    const assistantId = pushAssistantPlaceholder(convId);

    // Augment user message content with attachment refs for the API.
    const userApiContent =
      userAtts.length > 0
        ? `${finalContent}\n\n${userAtts
            .map((a) =>
              t("chat.attachmentTemplate", {
                filename: a.filename,
                sourceId: a.sourceId,
              })
            )
            .join("\n")}`
        : finalContent;

    setInput("");
    setAttachments([]);
    setBusy(true);

    await streamAssistantReply(convId, assistantId, userApiContent);
  }

  /**
   * Stream an assistant reply into the given placeholder message.
   * Reused by both `handleSend` (fresh message) and `handleRetry`
   * (regenerate reply). The caller is responsible for pushing the user
   * message + assistant placeholder before invoking this.
   *
   * `lastUserApiContent` is the augmented content of the last user message
   * (with attachment refs); if omitted, we just use the stored content.
   */
  async function streamAssistantReply(
    convId: string,
    assistantId: string,
    lastUserApiContent?: string
  ) {
    setBusy(true);
    // Create a fresh AbortController for this stream so the user can
    // stop generation mid-flight via the stop button.
    const controller = new AbortController();
    abortRef.current = controller;
    // Declare outside `try` so the `catch` block can reference them when
    // finalizing an aborted / errored stream.
    let acc = "";
    try {
      const conv = getActiveConversation();
      const apiMessages = (conv?.messages ?? [])
        .filter((m) => m.id !== assistantId && !m.streaming)
        .map((m, i, arr) => {
          if (m.role === "user" && i === arr.length - 1) {
            return {
              role: m.role,
              content: lastUserApiContent ?? m.content,
            };
          }
          return { role: m.role, content: m.content };
        });

      const stream = streamChat(
        {
          goal_id: goalId,
          scenario_id: scenarioId,
          messages: apiMessages,
        },
        controller.signal
      );

      const toolCalls: Record<string, ToolCall> = {};

      // RAF-batched streaming: multiple SSE tokens often arrive in the same
      // network packet (same microtask). Without batching, React 18's
      // automatic batching groups all `patchMessage` calls into a single
      // render, making streaming appear batched/non-smooth.
      //
      // We accumulate tokens in `pendingContent` and flush via
      // requestAnimationFrame — one render per frame (≈60fps), regardless
      // of how many tokens arrive between frames. This produces smooth
      // typewriter-style streaming without overwhelming React.
      let pendingContent: string | null = null;
      let rafId: number | null = null;
      const flushPending = () => {
        rafId = null;
        if (pendingContent !== null) {
          patchMessage(convId, assistantId, {
            content: pendingContent,
            streaming: true,
          });
          pendingContent = null;
        }
      };

      try {
        for await (const chunk of stream) {
          const delta = chunk.delta ?? "";
          if (delta) {
            acc += delta;
            pendingContent = acc;
            if (rafId === null) {
              rafId = requestAnimationFrame(flushPending);
            }
          }

          if (chunk.tool_call) {
            // Flush any pending content before tool call updates so the
            // user sees the latest text alongside the tool invocation.
            if (rafId !== null) {
              cancelAnimationFrame(rafId);
              rafId = null;
            }
            if (pendingContent !== null) {
              patchMessage(convId, assistantId, {
                content: pendingContent,
                streaming: true,
              });
              pendingContent = null;
            }

            const tc = chunk.tool_call;
            const hasResult = tc.result !== null && tc.result !== undefined;
            if (!hasResult) {
              const id = uid();
              // Capture the current length of the streamed content so the
              // renderer can later insert this tool call at the position
              // where the model actually invoked it, rather than dumping
              // all tool calls at the top or bottom of the body.
              const contentOffset = acc.length;
              toolCalls[id] = {
                id,
                name: tc.name,
                args: tc.args ?? {},
                result: null,
                startedAt: Date.now(),
                contentOffset,
              };
              upsertToolCall(convId, assistantId, toolCalls[id]);
            } else {
              const matchId = Object.entries(toolCalls)
                .filter(
                  ([, v]) =>
                    v.name === tc.name && v.result === null && !v.error
                )
                .sort((a, b) => b[1].startedAt - a[1].startedAt)[0]?.[0];
              if (matchId) {
                upsertToolCall(convId, assistantId, {
                  id: matchId,
                  name: tc.name,
                  result: tc.result,
                  endedAt: Date.now(),
                });
              }
            }
          }

          if (chunk.finish_reason) break;
        }
      } finally {
        // Cancel any pending RAF and do a final flush so the last batch
        // of tokens is committed before we mark streaming as done.
        if (rafId !== null) {
          cancelAnimationFrame(rafId);
          rafId = null;
        }
        if (pendingContent !== null) {
          patchMessage(convId, assistantId, {
            content: pendingContent,
            streaming: true,
          });
          pendingContent = null;
        }
      }

      patchMessage(convId, assistantId, {
        streaming: false,
      });

      maybeAutoTitle(convId);
    } catch (err) {
      // User-initiated abort — keep whatever was streamed so far, just
      // mark the message as done. Don't show an error.
      if ((err as Error).name === "AbortError") {
        patchMessage(convId, assistantId, {
          streaming: false,
        });
        maybeAutoTitle(convId);
      } else {
        patchMessage(convId, assistantId, {
          content: t("error.generic", { msg: (err as Error).message }),
          streaming: false,
        });
      }
    } finally {
      abortRef.current = null;
      setBusy(false);
    }
  }

  /** Abort the in-flight stream (if any) and finalize the assistant message. */
  function handleStop() {
    if (abortRef.current) {
      abortRef.current.abort();
    }
  }

  const handleRetry = useCallback(
    async (message: ChatMessage) => {
      if (busy || !state.activeId) return;
      const convId = state.activeId;

    if (message.role === "user") {
      // Drop everything after this user message (including any stale
      // assistant reply), then re-stream.
      const kept = truncateAfterMessage(convId, message.id);
      if (!kept || kept.length === 0) return;
      // Augment with attachment refs if present.
      const lastUser = kept[kept.length - 1];
      const userApiContent =
        lastUser.attachments && lastUser.attachments.length > 0
          ? `${lastUser.content}\n\n${lastUser.attachments
              .map((a) =>
                t("chat.attachmentTemplate", {
                  filename: a.filename,
                  sourceId: a.sourceId,
                })
              )
              .join("\n")}`
          : lastUser.content;
      const assistantId = pushAssistantPlaceholder(convId);
      await streamAssistantReply(convId, assistantId, userApiContent);
    } else {
      // Assistant message: preserve the previous reply, then re-stream.
      // The old content is moved into `previousVersions` on the new
      // placeholder so the user can flip back to it later.
      const result = retryAssistant(convId, message.id);
      if (!result) return;
      await streamAssistantReply(convId, result.assistantId, result.userApiContent);
    }
  },
    [busy, state.activeId, goalId, scenarioId, t]
  );

  /**
   * Delete handler — opens a confirmation dialog first. The actual
   * deletion is performed in `confirmDelete` once the user confirms.
   *
   * For assistant messages with multiple versions, this deletes only
   * the currently-viewed version (the user navigates versions via the
   * `← n / total →` control). If the current version is the only one,
   * the whole message is deleted. For user messages, the entire message
   * (and its reply) is always deleted.
   */
  const [pendingDelete, setPendingDelete] = useState<
    | { message: ChatMessage; viewingVersion: number }
    | null
  >(null);

  const handleDelete = useCallback(
    (message: ChatMessage, viewingVersion: number = 0) => {
      if (busy || !state.activeId) return;
      setPendingDelete({ message, viewingVersion });
    },
    [busy, state.activeId]
  );

  const confirmDelete = useCallback(() => {
    if (!pendingDelete || !state.activeId) return;
    const { message, viewingVersion } = pendingDelete;
    if (message.role === "assistant") {
      deleteAssistantVersion(state.activeId, message.id, viewingVersion);
    } else {
      deleteMessage(state.activeId, message.id);
    }
    setPendingDelete(null);
  }, [pendingDelete, state.activeId]);

  const handleCopy = useCallback(
    async (content: string): Promise<boolean> => {
      try {
        await navigator.clipboard.writeText(content);
        return true;
      } catch {
        return false;
      }
    },
    []
  );

  /**
   * Edit a user message: saves the old content as a previousVersion,
   * truncates everything after it, then re-streams a fresh assistant reply.
   * This mirrors the ChatGPT "edit & regenerate" pattern — the user can
   * flip back to the original wording via the version navigator.
   */
  const [editingId, setEditingId] = useState<string | null>(null);

  const handleEdit = useCallback(
    async (message: ChatMessage, newContent: string) => {
      if (busy || !state.activeId) return;
      const convId = state.activeId;
      const trimmed = newContent.trim();
      if (!trimmed || trimmed === message.content) {
        setEditingId(null);
        return;
      }
      const kept = editUserMessage(convId, message.id, trimmed);
      if (!kept || kept.length === 0) return;
      setEditingId(null);
      const lastUser = kept[kept.length - 1];
      const userApiContent =
        lastUser.attachments && lastUser.attachments.length > 0
          ? `${lastUser.content}\n\n${lastUser.attachments
              .map((a) =>
                t("chat.attachmentTemplate", {
                  filename: a.filename,
                  sourceId: a.sourceId,
                })
              )
              .join("\n")}`
          : lastUser.content;
      const assistantId = pushAssistantPlaceholder(convId);
      await streamAssistantReply(convId, assistantId, userApiContent);
    },
    [busy, state.activeId, t]
  );

  const hasMessages = messages.length > 0;
  const isEmpty = !hasMessages && !busy;

  return (
    <div
      className="flex flex-col h-full relative"
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
    >
      {/* Messages — uses <Thread> from ai-elements.
          The sidebar toggle and conversation title have been migrated
          to the top-level title bar in app/chat/page.tsx. */}
      <Thread autoScrollRef={scrollRef}>
        {isEmpty ? (
          <EmptyState
            suggestions={suggestions}
            onPick={(s) => {
              setInput(s);
              textareaRef.current?.focus();
            }}
          />
        ) : (
          messages.map((m) => (
            <MessageBubble
              key={m.id}
              message={m}
              userAvatarUrl={userAvatarUrl}
              userDisplayName={userProfile?.display_name}
              aiProtocol={chatModelInfo.protocol}
              aiModelName={chatModelInfo.name}
              disabled={busy}
              isEditing={editingId === m.id}
              onEditStart={() => setEditingId(m.id)}
              onEditCancel={() => setEditingId(null)}
              onEdit={handleEdit}
              onRetry={handleRetry}
              onDelete={handleDelete}
              onCopy={handleCopy}
            />
          ))
        )}
      </Thread>

      {/* Attachment preview row */}
      {attachments.length > 0 && (
        <div className="px-4 pt-3 flex flex-wrap gap-2 border-t border-white/5">
          {attachments.map((a) => (
            <div
              key={a.sourceId}
              className="group relative flex items-center gap-2 bg-white/5 border border-white/10 rounded-md pl-1.5 pr-7 py-1.5"
            >
              {a.isImage && a.previewUrl ? (
                <img
                  src={a.previewUrl}
                  alt={a.filename}
                  className="h-7 w-7 rounded object-cover"
                />
              ) : (
                <div className="h-7 w-7 rounded bg-brand-500/15 flex items-center justify-center">
                  {a.isImage ? (
                    <ImageIcon className="h-3.5 w-3.5 text-brand-300" />
                  ) : (
                    <FileText className="h-3.5 w-3.5 text-brand-300" />
                  )}
                </div>
              )}
              <span className="text-xs text-zinc-300 max-w-[160px] truncate">
                {a.filename}
              </span>
              <button
                onClick={() => removeAttachment(a.sourceId)}
                className="absolute right-1 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-red-300"
                title={t("chat.removeAttachment")}
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Input area — uses <Composer> from ai-elements */}
      <div className="px-4 py-3 border-t border-white/5 bg-white/[0.02]">
        <input
          ref={fileInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={handleFileInput}
          accept="image/*,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.md,.csv"
        />
        <Composer
          value={input}
          onChange={setInput}
          onSubmit={handleSend}
          disabled={busy}
          placeholder={t("chat.placeholder")}
          textareaRef={textareaRef}
          className="bg-black/[0.03] dark:bg-white/5 border-black/10 dark:border-white/10"
          leading={
            <Button
              variant="ghost"
              size="icon"
              className="h-9 w-9 shrink-0 text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 ml-1 rounded-full"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading || busy}
              title={t("chat.attachFile")}
            >
              {uploading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Paperclip className="h-4 w-4" />
              )}
            </Button>
          }
          trailing={
            busy ? (
              <button
                type="button"
                onClick={handleStop}
                title={t("chat.stop")}
                className="h-9 w-9 shrink-0 p-0 mr-1 flex items-center justify-center text-red-500 hover:text-red-600 dark:hover:text-red-400 transition-colors"
              >
                <Square className="h-4 w-4 fill-current" />
              </button>
            ) : (
              <button
                type="button"
                onClick={handleSend}
                disabled={busy || (!input.trim() && attachments.length === 0)}
                title={t("chat.send")}
                className="h-9 w-9 shrink-0 p-0 mr-1 flex items-center justify-center text-zinc-400 hover:text-brand-500 dark:hover:text-brand-400 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              >
                <Send className="h-4 w-4" />
              </button>
            )
          }
        />
      </div>

      {/* Drag overlay */}
      {dragOver && (
        <div className="absolute inset-0 z-10 bg-brand-500/10 border-2 border-dashed border-brand-400/60 rounded-xl flex items-center justify-center pointer-events-none">
          <div className="text-sm text-brand-200 flex items-center gap-2">
            <Paperclip className="h-4 w-4" />
            {t("chat.dropToUpload")}
          </div>
        </div>
      )}

      {/* Delete confirmation dialog — prevents accidental loss of
          streamed assistant replies. */}
      <Dialog
        open={!!pendingDelete}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>
              {pendingDelete?.message.role === "assistant" &&
              (pendingDelete.message.previousVersions?.length ?? 0) > 0
                ? t("chat.delete.titleVersion")
                : t("chat.delete.title")}
            </DialogTitle>
            <DialogDescription>
              {pendingDelete?.message.role === "assistant" &&
              (pendingDelete.message.previousVersions?.length ?? 0) > 0
                ? t("chat.delete.confirmVersion")
                : t("chat.delete.confirm")}
            </DialogDescription>
          </DialogHeader>
          {pendingDelete?.message.content && (
            <div className="rounded-md border border-black/10 dark:border-white/10 bg-black/[0.03] dark:bg-white/5 px-3 py-2 text-xs text-zinc-600 dark:text-zinc-400 max-h-32 overflow-y-auto">
              <div className="line-clamp-3 whitespace-pre-wrap break-words">
                {pendingDelete.message.content}
              </div>
            </div>
          )}
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="outline" size="sm">
                {t("chat.delete.cancel")}
              </Button>
            </DialogClose>
            <Button
              variant="destructive"
              size="sm"
              onClick={confirmDelete}
            >
              <Trash2 className="h-3.5 w-3.5 mr-1.5" />
              {t("chat.delete.confirmBtn")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function EmptyState({
  suggestions,
  onPick,
}: {
  suggestions: string[];
  onPick: (s: string) => void;
}) {
  const t = useT();
  return (
    <div className="h-full flex flex-col items-center justify-center text-center py-8 animate-fade-in overflow-y-auto">
      <div className="h-12 w-12 rounded-full bg-gradient-to-br from-brand-400 to-brand-700 flex items-center justify-center shadow-lg shadow-brand-900/40 mb-4">
        <Sparkles className="h-5 w-5 text-white" />
      </div>
      <h2 className="text-base font-semibold text-zinc-200">
        {t("chat.empty.title")}
      </h2>
      <p className="text-xs text-zinc-500 mt-1 max-w-md">
        {t("chat.empty.subtitle")}
      </p>
      {/* Capabilities hint — tells the user what the AI advisor can
          actually do, so they don't have to guess. */}
      <p className="text-[11px] text-zinc-600 dark:text-zinc-400 mt-3 max-w-lg leading-relaxed">
        {t("chat.empty.capabilities")}
      </p>
      <p className="text-[11px] text-zinc-600 dark:text-zinc-400 mt-1.5 max-w-lg leading-relaxed">
        {t("chat.empty.howToUse")}
      </p>
      <div className="mt-5 space-y-2 w-full max-w-md">
        <div className="text-[11px] text-zinc-600 px-1 text-left">
          {t("chat.tryThese")}
        </div>
        <div className="flex flex-col gap-1.5">
          {suggestions.map((s) => (
            <button
              key={s}
              onClick={() => onPick(s)}
              className="text-left text-xs text-zinc-300 bg-white/[0.03] hover:bg-white/[0.06] border border-white/10 hover:border-brand-500/30 rounded-md px-3 py-2 transition-colors"
            >
              {s}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

/**
 * Renders an assistant message body with tool calls interleaved at the
 * exact positions where the model invoked them during streaming.
 *
 * Each `ToolCall.contentOffset` is the character offset into `content`
 * at the moment the tool call started. We sort tool calls by offset,
 * split the content into segments at those offsets, and emit:
 *
 *   text[0..offset₁] → tool₁ → text[offset₁..offset₂] → tool₂ → … → text[tail]
 *
 * Tool calls without an offset (older persisted messages) are appended
 * after the full body so the rendering remains backward-compatible.
 *
 * While streaming, the cursor is shown at the tail of the last text
 * segment — which is wherever the model is currently emitting tokens.
 */
function InterleavedBody({
  content,
  toolCalls,
  streaming,
}: {
  content: string;
  toolCalls?: ToolCall[];
  streaming?: boolean;
}) {
  // Split tool calls into positioned vs. legacy (no offset).
  const positioned = (toolCalls ?? [])
    .filter((tc) => typeof tc.contentOffset === "number")
    .sort((a, b) => (a.contentOffset ?? 0) - (b.contentOffset ?? 0));
  const legacy = (toolCalls ?? []).filter(
    (tc) => typeof tc.contentOffset !== "number"
  );

  // Build the interleaved segment list. We walk through `content`,
  // slicing at each positioned tool call's offset. Offsets that exceed
  // the current content length (can happen briefly during streaming
  // when a tool call arrives before its preceding text) are clamped.
  const segments: React.ReactNode[] = [];
  let cursor = 0;
  for (const tc of positioned) {
    const offset = Math.min(tc.contentOffset ?? 0, content.length);
    if (offset > cursor) {
      segments.push(
        <ResponseMarkdown
          key={`text-${tc.id}`}
          content={content.slice(cursor, offset)}
          streaming={false}
        />
      );
    }
    segments.push(<ToolInvocation key={`tool-${tc.id}`} tool={tc} />);
    cursor = offset;
  }
  // Tail segment — the remaining text after the last positioned tool
  // call. This is where the streaming cursor lives.
  if (cursor < content.length || (streaming && positioned.length === 0)) {
    const tail = content.slice(cursor);
    segments.push(
      <ResponseContainer key="text-tail">
        {tail ? (
          <ResponseMarkdown content={tail} streaming={streaming} />
        ) : streaming ? (
          <ThinkingDots />
        ) : null}
        {streaming && tail ? <StreamingCursor /> : null}
      </ResponseContainer>
    );
  }
  // Legacy tool calls (no offset) — appended after the body.
  for (const tc of legacy) {
    segments.push(<ToolInvocation key={`tool-legacy-${tc.id}`} tool={tc} />);
  }

  // Empty content but streaming — show thinking dots.
  if (!content && streaming && segments.length === 0) {
    return (
      <ResponseContainer>
        <ThinkingDots />
      </ResponseContainer>
    );
  }

  return <ResponseContainer>{segments}</ResponseContainer>;
}

/**
 * Memoized message row. The streaming message re-renders on every token
 * (its `content` changes), but sibling messages — whose props are referentially
 * stable — skip re-rendering entirely. This is critical for streaming perf:
 * without memo, every token would re-render the whole conversation.
 */
const MessageBubble = memo(function MessageBubble({
  message,
  userAvatarUrl,
  userDisplayName,
  aiProtocol,
  aiModelName,
  disabled,
  isEditing,
  onEditStart,
  onEditCancel,
  onEdit,
  onRetry,
  onDelete,
  onCopy,
}: {
  message: ChatMessage;
  userAvatarUrl?: string | null;
  userDisplayName?: string;
  aiProtocol?: string;
  aiModelName?: string;
  disabled?: boolean;
  isEditing?: boolean;
  onEditStart: () => void;
  onEditCancel: () => void;
  onEdit: (message: ChatMessage, newContent: string) => void;
  onRetry: (message: ChatMessage) => void;
  onDelete: (message: ChatMessage, viewingVersion: number) => void;
  onCopy: (content: string) => Promise<boolean>;
}) {
  const t = useT();
  const isUser = message.role === "user";
  const hasTools = (message.toolCalls?.length ?? 0) > 0;
  const isStreaming = !!message.streaming;
  const isEmpty = !message.content && !hasTools;
  const [copied, setCopied] = useState(false);
  const [editDraft, setEditDraft] = useState("");

  // Version navigation state — purely a UI concern. We don't mutate the
  // store; we just pick which historical snapshot to display. Position
  // 0 = current (newest), N = previousVersions[N-1] (oldest). This avoids
  // the costly swap dance on every click and lets the user flip freely.
  // User messages also support versioning (via editUserMessage), so we
  // include them here too.
  const previousVersions = message.previousVersions ?? [];
  const totalVersions = previousVersions.length + 1;
  const [viewingVersion, setViewingVersion] = useState(0);
  const hasMultipleVersions = totalVersions > 1;

  // Reset to newest whenever a new retry arrives (i.e. whenever the
  // previousVersions array grows). This keeps the bubble showing the
  // fresh reply after a retry, not whatever version the user was
  // previously viewing.
  useEffect(() => {
    setViewingVersion(0);
  }, [previousVersions.length]);

  // Pick the displayed snapshot based on viewingVersion.
  const snapshot: Pick<ChatMessage, "content" | "toolCalls"> =
    viewingVersion === 0
      ? {
          content: message.content,
          toolCalls: message.toolCalls,
        }
      : previousVersions[viewingVersion - 1];

  const hasToolsNow = (snapshot.toolCalls?.length ?? 0) > 0;

  // Show action bar when: not streaming, not empty, and has actual content.
  const showActions = !isStreaming && !disabled && (snapshot.content || hasToolsNow);

  async function handleCopyClick() {
    const ok = await onCopy(snapshot.content);
    if (ok) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }
  }

  function handleEditStart() {
    setEditDraft(snapshot.content);
    onEditStart();
  }

  return (
    <Message
      role={message.role}
      avatar={
        isUser ? (
          userAvatarUrl ? (
            <img
              src={userAvatarUrl}
              alt={userDisplayName ?? "user"}
              className="h-full w-full rounded-full object-cover"
            />
          ) : (
            <span className="text-[10px]">
              {(userDisplayName ?? t("chat.me")).slice(0, 1).toUpperCase()}
            </span>
          )
        ) : (
          <AIAvatar
            protocol={aiProtocol}
            name={aiModelName}
            size={14}
            className="h-3.5 w-3.5"
          />
        )
      }
    >
      {/* Attachments */}
      {message.attachments && message.attachments.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {message.attachments.map((a) => (
            <div
              key={a.sourceId}
              className="flex items-center gap-1.5 bg-black/[0.04] dark:bg-white/5 border border-black/10 dark:border-white/10 rounded-md pl-1 pr-2 py-1"
            >
              {a.isImage && a.previewUrl ? (
                <img
                  src={a.previewUrl}
                  alt={a.filename}
                  className="h-6 w-6 rounded object-cover"
                />
              ) : (
                <div className="h-6 w-6 rounded bg-brand-500/15 flex items-center justify-center">
                  {a.isImage ? (
                    <ImageIcon className="h-3 w-3 text-brand-600 dark:text-brand-300" />
                  ) : (
                    <FileText className="h-3 w-3 text-brand-600 dark:text-brand-300" />
                  )}
                </div>
              )}
              <span className="text-[11px] text-zinc-700 dark:text-zinc-300 max-w-[140px] truncate">
                {a.filename}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Text content — user messages keep a tinted bubble; AI messages
          are displayed flat (no bubble wrapper) so markdown content like
          tables, code blocks, and charts can use the full available width
          without being squeezed by bubble padding/border.

          For AI messages, tool calls are interleaved with the text body
          at the exact positions where the model invoked them (tracked via
          `toolCall.contentOffset`). The body is rendered fully without
          an internal scrollbar — long responses simply extend the
          conversation scroll, which is what users expect from a chat.

          When editing a user message, the bubble is replaced with a
          textarea + Save/Cancel controls. The original content is
          preserved as a previousVersion so the user can flip back. */}
      {isEditing && isUser ? (
        <div className="rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed bg-brand-500/15 dark:bg-brand-500/20 text-brand-900 dark:text-brand-50 border border-brand-500/40 dark:border-brand-500/50">
          <textarea
            autoFocus
            value={editDraft}
            onChange={(e) => setEditDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                onEdit(message, editDraft);
              } else if (e.key === "Escape") {
                e.preventDefault();
                onEditCancel();
              }
            }}
            rows={Math.min(8, Math.max(1, editDraft.split("\n").length))}
            className="w-full bg-transparent resize-none outline-none text-sm leading-relaxed text-brand-900 dark:text-brand-50 placeholder:text-brand-700/50 dark:placeholder:text-brand-200/50"
          />
          <div className="flex items-center justify-end gap-1.5 mt-1.5">
            <Button
              variant="ghost"
              size="sm"
              className="h-6 px-2 text-xs"
              onClick={onEditCancel}
            >
              {t("chat.action.cancel")}
            </Button>
            <Button
              variant="default"
              size="sm"
              className="h-6 px-2 text-xs"
              onClick={() => onEdit(message, editDraft)}
              disabled={!editDraft.trim() || editDraft.trim() === message.content}
            >
              {t("chat.action.save")}
            </Button>
          </div>
        </div>
      ) : snapshot.content || isStreaming ? (
        isUser ? (
          <div className="rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed bg-brand-500/15 dark:bg-brand-500/20 text-brand-900 dark:text-brand-50 border border-brand-500/20 dark:border-brand-500/30">
            <div className="whitespace-pre-wrap break-words">
              {snapshot.content}
              {isStreaming && <StreamingCursor />}
            </div>
          </div>
        ) : (
          <div className="text-sm leading-relaxed text-zinc-800 dark:text-zinc-200">
            <InterleavedBody
              content={snapshot.content}
              toolCalls={snapshot.toolCalls}
              streaming={isStreaming}
            />
          </div>
        )
      ) : isEmpty && !hasToolsNow ? null : null}

      {/* Version navigator — `← n / sum →` style. Only shown when the
          assistant message has been retried at least once. Clicking ←
          goes to an older version, → goes to a newer one. Disabled at
          the ends with a tooltip explaining why. */}
      {hasMultipleVersions && !isStreaming && (
        <VersionNavigator
          current={viewingVersion + 1}
          total={totalVersions}
          onNewer={() =>
            setViewingVersion((v) => Math.max(0, v - 1))
          }
          onOlder={() =>
            setViewingVersion((v) => Math.min(totalVersions - 1, v + 1))
          }
        />
      )}

      {/* Action bar — appears under every AI / user message that has content.
          Hidden while streaming and when the global `disabled` flag is set
          (e.g. another reply is in flight). Hover-to-show on touch screens
          would be ideal, but for desktop-first usage always-on is fine. */}
      {showActions && !isEditing && (
        <div
          className={cn(
            "flex items-center gap-0.5 mt-0.5",
            isUser ? "justify-end" : "justify-start"
          )}
        >
          <ActionButton
            icon={
              copied ? (
                <Check className="h-3 w-3 text-emerald-500 dark:text-emerald-400" />
              ) : (
                <Copy className="h-3 w-3" />
              )
            }
            label={copied ? t("chat.action.copied") : t("chat.action.copy")}
            onClick={handleCopyClick}
            disabled={copied}
          />
          {isUser && (
            <ActionButton
              icon={<Pencil className="h-3 w-3" />}
              label={t("chat.action.edit")}
              onClick={handleEditStart}
            />
          )}
          <ActionButton
            icon={<RotateCcw className="h-3 w-3" />}
            label={t("chat.action.retry")}
            onClick={() => onRetry(message)}
          />
          <ActionButton
            icon={<Trash2 className="h-3 w-3" />}
            label={t("chat.action.delete")}
            onClick={() => onDelete(message, viewingVersion)}
            danger
          />
        </div>
      )}
    </Message>
  );
});

/**
 * Inline-editable conversation title. Renders as text by default; clicking
 * switches to an input. Commits on Enter or blur, cancels on Escape.
 * The input is uncontrolled-ish: it keeps a local draft while focused and
 * only calls `onCommit` when the user actually confirms.
 *
 * Exported so the top-level chat page title bar can reuse the same
 * inline-edit UX without duplicating the logic.
 */
export function EditableTitle({
  value,
  placeholder,
  onCommit,
  disabled,
}: {
  value: string;
  placeholder: string;
  onCommit: (title: string) => void;
  disabled?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const inputRef = useRef<HTMLInputElement>(null);

  // Keep draft in sync when the upstream value changes (e.g. auto-title
  // arrives from the model after the first exchange).
  useEffect(() => {
    if (!editing) setDraft(value);
  }, [value, editing]);

  // Focus on enter edit mode.
  useEffect(() => {
    if (editing) inputRef.current?.focus();
  }, [editing]);

  function startEdit() {
    if (disabled) return;
    setDraft(value);
    setEditing(true);
  }

  function commit() {
    const next = draft.trim();
    if (next !== value) onCommit(next);
    setEditing(false);
  }

  function cancel() {
    setDraft(value);
    setEditing(false);
  }

  if (editing) {
    return (
      <input
        ref={inputRef}
        type="text"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commit();
          } else if (e.key === "Escape") {
            e.preventDefault();
            cancel();
          }
        }}
        placeholder={placeholder}
        maxLength={100}
        className="text-xs font-medium bg-transparent border-b border-brand-500/60 focus:outline-none focus:border-brand-500 text-zinc-800 dark:text-zinc-100 placeholder:text-zinc-400 dark:placeholder:text-zinc-500 min-w-0 w-full max-w-[280px] px-0.5"
      />
    );
  }

  return (
    <button
      type="button"
      onClick={startEdit}
      disabled={disabled}
      title={value || placeholder}
      className="text-xs font-medium text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100 truncate max-w-[280px] px-0.5 py-0.5 rounded hover:bg-black/5 dark:hover:bg-white/5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
    >
      {value || placeholder}
    </button>
  );
}

/**
 * Version navigator — `← n / sum →` style. Shows the current version
 * position (1-indexed) over the total number of saved replies for this
 * assistant message. The arrows step through history; disabled at the
 * ends with a tooltip.
 */
function VersionNavigator({
  current,
  total,
  onNewer,
  onOlder,
}: {
  current: number;
  total: number;
  onNewer: () => void;
  onOlder: () => void;
}) {
  const t = useT();
  const atNewest = current <= 1;
  const atOldest = current >= total;

  return (
    <div className="inline-flex items-center gap-0.5 mt-1 px-1 py-0.5 rounded-full border border-black/10 dark:border-white/10 bg-black/[0.03] dark:bg-white/5">
      <button
        type="button"
        onClick={onNewer}
        disabled={atNewest}
        title={atNewest ? t("chat.versions.newest") : undefined}
        className="h-5 w-5 flex items-center justify-center rounded-full text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100 hover:bg-black/10 dark:hover:bg-white/10 disabled:opacity-30 disabled:hover:bg-transparent disabled:cursor-not-allowed transition-colors"
      >
        <ChevronLeft className="h-3 w-3" />
      </button>
      <span
        className="text-[10px] tabular-nums text-zinc-600 dark:text-zinc-400 px-1 select-none"
        title={t("chat.versions.position", { n: current, total })}
      >
        {current} / {total}
      </span>
      <button
        type="button"
        onClick={onOlder}
        disabled={atOldest}
        title={atOldest ? t("chat.versions.oldest") : undefined}
        className="h-5 w-5 flex items-center justify-center rounded-full text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100 hover:bg-black/10 dark:hover:bg-white/10 disabled:opacity-30 disabled:hover:bg-transparent disabled:cursor-not-allowed transition-colors"
      >
        <ChevronRight className="h-3 w-3" />
      </button>
    </div>
  );
}

function ActionButton({
  icon,
  label,
  onClick,
  disabled,
  danger,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={label}
      aria-label={label}
      className={cn(
        "inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] transition-colors",
        "text-zinc-500 hover:text-zinc-200 hover:bg-white/5",
        danger && "hover:text-red-300 hover:bg-red-500/10",
        disabled && "opacity-50 cursor-not-allowed"
      )}
    >
      {icon}
    </button>
  );
}
