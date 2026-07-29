"use client";

import { useState, useRef, useEffect, useCallback, useMemo, memo } from "react";
// TooltipProvider wraps PromptInputButton tooltips
import {
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
  ChevronLeft,
  ChevronRight,
  Pencil,
  Globe,
  Wrench,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { api, streamChat } from "@/lib/api";
import { useT } from "@/lib/i18n/provider";
import { useRuntimeCatalog, useUserProfile, useMcpServers, useUserSkills } from "@/lib/hooks";
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
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import { Switch } from "@/components/ui/switch";
import {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
  ConversationScrollButton,
} from "@/components/ai-elements/conversation";
import {
  Message,
  MessageActions,
  MessageContent,
  MessageResponse,
} from "@/components/ai-elements/message";
import {
  Reasoning,
  ReasoningTrigger,
  ReasoningContent,
} from "@/components/ai-elements/reasoning";
import {
  Sources,
  SourcesTrigger,
  SourcesContent,
  Source,
  parseSearchSources,
} from "@/components/ai-elements/sources";
import {
  Tool,
  ToolContent,
  ToolHeader,
  ToolInput,
  ToolOutput,
} from "@/components/ai-elements/tool";
import {
  PromptInput,
  PromptInputBody,
  PromptInputTextarea,
  PromptInputTools,
  PromptInputSubmit,
  PromptInputFooter,
  PromptInputHeader,
  PromptInputButton,
} from "@/components/ai-elements/prompt-input";
import { ChatModelSelector } from "@/components/chat/chat-model-selector";
import { TooltipProvider } from "@/components/ui/tooltip";
import {
  ChatMinimap,
  StreamingCursor,
  ThinkingDots,
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
} from "@/lib/chat-store";
import { AIAvatar } from "@/components/common/ai-avatar";
import { useIsPwa } from "@/lib/use-pwa";

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
  modelId?: string;
  onModelChange?: (modelId: string) => void;
}

function uid() {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export function ChatPanel({ goalId, scenarioId, modelId, onModelChange }: Props) {
  const t = useT();
  const state = useChatStore(); // re-renders on store changes
  const activeConv = getActiveConversation();
  const { data: userProfile } = useUserProfile();
  const { data: settings } = useRuntimeCatalog();
  const userAvatarUrl = (userProfile as { avatar_url?: string | null } | undefined)?.avatar_url ?? null;
  const toast = useToast();

  // Resolve the current chat model + provider so we can show the model's
  // brand icon (e.g. DeepSeek, OpenAI, Anthropic) as the AI avatar instead
  // of a generic sparkles icon.
  const chatModelInfo = useMemo(() => {
    const chatModelId = modelId ?? settings?.role_assignments?.["chat"];
    const chatModel = settings?.models?.find((m) => m.id === chatModelId);
    const chatProvider = chatModel
      ? settings?.providers?.find((p) => p.id === chatModel.provider_id)
      : undefined;
    return {
      protocol: chatProvider?.protocol as string | undefined,
      name: chatModel?.name as string | undefined,
    };
  }, [modelId, settings]);

  const handleModelSelect = useCallback(
    (nextModelId: string) => {
      onModelChange?.(nextModelId);
    },
    [onModelChange]
  );

  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const isPwa = useIsPwa();

  // --- Per-request options for the PromptInput toolbar ---
  // Web search toggle — built-in tool, enabled by default
  const [webSearch, setWebSearch] = useState(true);
  // MCP servers / Skills are loaded from the user's runtime config. When
  // `enabledMcp` / `enabledSkills` is null, ALL enabled servers/skills are
  // active (default). When the user opens the tools panel and toggles any
  // off, we switch to a filtered list.
  const { data: mcpServers } = useMcpServers();
  const { data: userSkills } = useUserSkills();
  const [enabledMcp, setEnabledMcp] = useState<string[] | null>(null);
  const [enabledSkillNames, setEnabledSkillNames] = useState<string[] | null>(
    null
  );

  const suggestions = useMemo(
    () => [t("chat.suggest1"), t("chat.suggest2"), t("chat.suggest3")],
    [t]
  );

  // Ensure there is an active conversation. If none, create one lazily on
  // first user message — but we still need an empty state UI here.
  const messages: ChatMessage[] = activeConv?.messages ?? [];

  // Build user message list for the minimap pill — includes edit versions.
  const userMinimapMessages = useMemo(
    () =>
      messages
        .map((m, i) => ({
          index: i,
          id: m.id,
          content: m.content,
          versions: m.previousVersions?.map((v) => ({
            content: v.content,
            createdAt: v.createdAt,
          })),
        }))
        .filter((m) => messages[m.index]?.role === "user"),
    [messages]
  );

  // Jump to a specific message by index — used by the minimap.
  // Uses document.querySelector since the Vercel Conversation component
  // manages its own scroll container internally.
  const handleJumpTo = useCallback((index: number) => {
    const target = document.querySelector(`[data-message-index="${index}"]`);
    if (target) {
      target.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, []);

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
          model_id: modelId,
          messages: apiMessages,
          web_search: webSearch,
          enabled_mcp_servers: enabledMcp ?? undefined,
          enabled_skills: enabledSkillNames ?? undefined,
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
      let pendingReasoning: string | null = null;
      let reasoningAcc = "";
      let rafId: number | null = null;
      const flushPending = () => {
        rafId = null;
        if (pendingContent !== null || pendingReasoning !== null) {
          patchMessage(convId, assistantId, {
            content: pendingContent ?? acc,
            ...(pendingReasoning !== null ? { reasoning: pendingReasoning } : {}),
            streaming: true,
          });
          pendingContent = null;
          pendingReasoning = null;
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

          // Accumulate reasoning/thinking tokens (CoT) separately from
          // the main content. The backend sends these as `reasoning_delta`.
          if (chunk.reasoning_delta) {
            reasoningAcc += chunk.reasoning_delta;
            pendingReasoning = reasoningAcc;
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
            if (pendingContent !== null || pendingReasoning !== null) {
              patchMessage(convId, assistantId, {
                content: pendingContent ?? acc,
                ...(pendingReasoning !== null ? { reasoning: pendingReasoning } : {}),
                streaming: true,
              });
              pendingContent = null;
              pendingReasoning = null;
            }

            const tc = chunk.tool_call;
            const hasResult = tc.result !== null && tc.result !== undefined;
            if (!hasResult) {
              // Use the tool_call_id from the backend (LangGraph run_id)
              // to correlate start/end events. Fall back to a random uid
              // for backward compat with older backends that don't send id.
              const id = tc.id || uid();
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
              // Match by tool_call_id from the backend. If id is missing
              // (old backend), fall back to name+startedAt matching.
              let matchId: string | undefined;
              if (tc.id && toolCalls[tc.id]) {
                matchId = tc.id;
              } else {
                matchId = Object.entries(toolCalls)
                  .filter(
                    ([, v]) =>
                      v.name === tc.name && v.result === null && !v.error
                  )
                  .sort((a, b) => b[1].startedAt - a[1].startedAt)[0]?.[0];
              }
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
        if (pendingContent !== null || pendingReasoning !== null) {
          patchMessage(convId, assistantId, {
            content: pendingContent ?? acc,
            ...(pendingReasoning !== null ? { reasoning: pendingReasoning } : {}),
            streaming: true,
          });
          pendingContent = null;
          pendingReasoning = null;
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
      className="flex flex-col h-full relative min-w-0 overflow-hidden"
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
    >
      {/* Messages — uses Vercel <Conversation> which handles
          stick-to-bottom scrolling automatically. */}
      <Conversation className="flex-1">
        <ConversationContent className="px-4 sm:px-5 py-4 gap-4">
          {isEmpty ? (
            <EmptyState
              suggestions={suggestions}
              onPick={(s) => {
                setInput(s);
                textareaRef.current?.focus();
              }}
            />
          ) : (
            messages.map((m, i) => (
              <div key={m.id} data-message-index={i}>
                <MessageBubble
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
              </div>
            ))
          )}
        </ConversationContent>
        <ConversationScrollButton />
        {/* Floating minimap pill — hidden in PWA mode (screen too narrow) */}
        {!isEmpty && !isPwa && userMinimapMessages.length > 0 && (
          <ChatMinimap
            userMessages={userMinimapMessages}
            onJumpTo={handleJumpTo}
          />
        )}
      </Conversation>

      {/* PromptInput — floating input box, no wrapper div.
          Structure follows the official Vercel AI Elements docs:
          PromptInputHeader (attachments) > PromptInputBody (textarea) >
          PromptInputFooter (tools + submit). The InputGroup inside
          PromptInput switches to flex-col via the block-end addon. */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        className="hidden"
        onChange={handleFileInput}
        accept="image/*,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.md,.csv"
      />
      <TooltipProvider>
      <PromptInput
        onSubmit={() => {
          handleSend();
        }}
        className="w-auto mx-4 mb-3 bg-black/[0.03] dark:bg-white/5 border-black/10 dark:border-white/10"
      >
        {attachments.length > 0 && (
          <PromptInputHeader>
            <div className="flex flex-wrap gap-1.5">
              {attachments.map((a) => (
                <div
                  key={a.sourceId}
                  className="relative flex items-center gap-1.5 bg-black/[0.04] dark:bg-white/5 border border-black/10 dark:border-white/10 rounded-md pl-1 pr-5 py-1"
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
                  <button
                    type="button"
                    onClick={() => removeAttachment(a.sourceId)}
                    className="absolute right-1 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-red-300"
                    title={t("chat.removeAttachment")}
                  >
                    <X className="h-3 w-3" />
                  </button>
                </div>
              ))}
            </div>
          </PromptInputHeader>
        )}
        <PromptInputBody>
          <PromptInputTextarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={t("chat.placeholder")}
            disabled={busy}
            ref={textareaRef}
          />
        </PromptInputBody>
        <PromptInputFooter className="flex-wrap gap-1">
          <PromptInputTools className="flex-wrap">
            {/* Attachment button — uses our external file input, not
                PromptInput's internal state, so handleFile can upload
                to the backend and track sourceId. */}
            <PromptInputButton
              variant="ghost"
              size="icon-sm"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading || busy}
              tooltip={t("chat.attachFile")}
            >
              {uploading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Paperclip className="h-4 w-4" />
              )}
            </PromptInputButton>

            {/* Web search toggle — built-in tool, always available. */}
            <PromptInputButton
              onClick={() => setWebSearch((v) => !v)}
              variant={webSearch ? "default" : "ghost"}
              size="icon-sm"
              tooltip={t("chat.webSearch")}
            >
              <Globe className="h-4 w-4" />
            </PromptInputButton>

            {/* MCP / Skills selector — uses native button to avoid Radix
                Slot props conflict when nested through PromptInputButton. */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  className="inline-flex items-center justify-center h-8 w-8 rounded-md text-zinc-400 hover:bg-black/[0.04] dark:hover:bg-white/5 transition-colors"
                  title={t("chat.tools")}
                >
                  <Wrench className="h-4 w-4" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent
                align="start"
                className="w-64 max-h-80 overflow-y-auto"
              >
                {(mcpServers ?? []).length > 0 ? (
                  <>
                    <div className="px-2 py-1.5 text-xs font-semibold text-muted-foreground">
                      MCP Servers
                    </div>
                    {(mcpServers ?? []).map((srv) => {
                      const checked = enabledMcp
                        ? enabledMcp.includes(srv.name)
                        : srv.enabled;
                      return (
                        <div
                          key={srv.id}
                          className="flex items-center justify-between px-2 py-1.5"
                        >
                          <span className="text-xs truncate flex-1">
                            {srv.name}
                          </span>
                          <Switch
                            checked={checked}
                            onCheckedChange={(on) =>
                              setEnabledMcp((prev) => {
                                const all = (mcpServers ?? [])
                                  .filter((s) => s.enabled)
                                  .map((s) => s.name);
                                const current = prev ?? all;
                                return on
                                  ? Array.from(new Set([...current, srv.name]))
                                  : current.filter((n) => n !== srv.name);
                              })
                            }
                            className="scale-75"
                          />
                        </div>
                      );
                    })}
                  </>
                ) : (
                  <div className="px-2 py-1.5 text-xs text-muted-foreground">
                    No MCP servers configured
                  </div>
                )}
                <DropdownMenuSeparator />
                {(userSkills ?? []).length > 0 ? (
                  <>
                    <div className="px-2 py-1.5 text-xs font-semibold text-muted-foreground">
                      Skills
                    </div>
                    {(userSkills ?? []).map((skill) => {
                      const checked = enabledSkillNames
                        ? enabledSkillNames.includes(skill.name)
                        : skill.enabled;
                      return (
                        <div
                          key={skill.id}
                          className="flex items-center justify-between px-2 py-1.5"
                        >
                          <span className="text-xs truncate flex-1">
                            {skill.name}
                          </span>
                          <Switch
                            checked={checked}
                            onCheckedChange={(on) =>
                              setEnabledSkillNames((prev) => {
                                const all = (userSkills ?? [])
                                  .filter((s) => s.enabled)
                                  .map((s) => s.name);
                                const current = prev ?? all;
                                return on
                                  ? Array.from(new Set([...current, skill.name]))
                                  : current.filter((n) => n !== skill.name);
                              })
                            }
                            className="scale-75"
                          />
                        </div>
                      );
                    })}
                  </>
                ) : (
                  <div className="px-2 py-1.5 text-xs text-muted-foreground">
                    No skills configured
                  </div>
                )}
              </DropdownMenuContent>
            </DropdownMenu>

            {/* Model selector — reuses the same ChatModelSelector as the
                top bar, with provider-grouped list and model avatars. */}
            <ChatModelSelector
              catalog={settings}
              value={modelId}
              onValueChange={handleModelSelect}
            />
          </PromptInputTools>
          <PromptInputSubmit
            status={busy ? "streaming" : "ready"}
            onStop={handleStop}
            disabled={busy || (!input.trim() && attachments.length === 0)}
          />
        </PromptInputFooter>
      </PromptInput>
      </TooltipProvider>

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
  // Vercel ConversationEmptyState provides the centered full-size layout
  // (flex size-full flex-col items-center justify-center gap-3 p-8
  // text-center). We override gap/padding to preserve the existing
  // margin-based spacing and keep the scrollable rich content.
  return (
    <ConversationEmptyState className="animate-fade-in overflow-y-auto gap-0 px-0 py-8">
      <div className="h-12 w-12 rounded-full bg-gradient-to-br from-brand-400 to-brand-700 flex items-center justify-center shadow-lg shadow-brand-900/40 mb-4">
        <Sparkles className="h-5 w-5 text-white" />
      </div>
      <h2 className="text-base font-semibold text-zinc-200">
        {t("chat.empty.title")}
      </h2>
      <p className="text-xs text-zinc-500 mt-1 max-w-md">
        {t("chat.empty.subtitle")}
      </p>
      {/* Capabilities hint — tells the user what the intelligent assistant can
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
    </ConversationEmptyState>
  );
}

/** Detect failure from result shape: backend tools return {"error": ...}. */
function resultIsError(result: unknown): boolean {
  if (result && typeof result === "object" && "error" in result) {
    const v = (result as Record<string, unknown>).error;
    return typeof v === "string" && v.length > 0;
  }
  return false;
}

/**
 * Renders a single tool call using Vercel AI Elements `Tool` components.
 * The Vercel `Tool` provides the collapsible structure, header (with
 * status badge), and input/output formatting. `mb-0` overrides the
 * default `mb-4` since spacing is handled by the parent flex gap.
 */
function ToolCallView({ tool }: { tool: ToolCall }) {
  const resultHasError = resultIsError(tool.result);
  const failed = !!tool.error || resultHasError;
  const running = tool.result === null && !tool.error;
  const state: "input-available" | "output-available" | "output-error" = failed
    ? "output-error"
    : running
    ? "input-available"
    : "output-available";
  const errorMessage = tool.error
    ? tool.error
    : resultHasError
    ? String((tool.result as Record<string, unknown>).error)
    : undefined;

  return (
    <Tool className="mb-0">
      <ToolHeader
        type="dynamic-tool"
        state={state}
        toolName={tool.name}
        title={tool.name}
      />
      <ToolContent>
        {Object.keys(tool.args).length > 0 && (
          <ToolInput input={tool.args} />
        )}
        <ToolOutput
          output={failed ? null : tool.result}
          errorText={errorMessage}
        />
      </ToolContent>
    </Tool>
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
        <MessageResponse
          key={`text-${tc.id}`}
          parseIncompleteMarkdown={streaming}
        >
          {content.slice(cursor, offset)}
        </MessageResponse>
      );
    }
    segments.push(<ToolCallView key={`tool-${tc.id}`} tool={tc} />);
    cursor = offset;
  }
  // Tail segment — the remaining text after the last positioned tool
  // call. This is where the streaming cursor lives.
  if (cursor < content.length || (streaming && positioned.length === 0)) {
    const tail = content.slice(cursor);
    segments.push(
      <div key="text-tail" className="flex flex-col gap-1.5 animate-fade-in">
        {tail ? (
          <MessageResponse parseIncompleteMarkdown={streaming}>
            {tail}
          </MessageResponse>
        ) : streaming ? (
          <ThinkingDots />
        ) : null}
        {streaming && tail ? <StreamingCursor /> : null}
      </div>
    );
  }
  // Legacy tool calls (no offset) — appended after the body.
  for (const tc of legacy) {
    segments.push(<ToolCallView key={`tool-legacy-${tc.id}`} tool={tc} />);
  }

  // Empty content but streaming — show thinking dots.
  if (!content && streaming && segments.length === 0) {
    return (
      <div className="flex flex-col gap-1.5 animate-fade-in">
        <ThinkingDots />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1.5 animate-fade-in">{segments}</div>
  );
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
  const isStreaming = !!message.streaming;
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
  const snapshot: Pick<ChatMessage, "content" | "toolCalls" | "reasoning"> =
    viewingVersion === 0
      ? {
          content: message.content,
          toolCalls: message.toolCalls,
          reasoning: message.reasoning,
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
    <div
      className={cn(
        "flex gap-3 animate-fade-in",
        isUser ? "flex-row-reverse" : "flex-row"
      )}
    >
      <div
        className={cn(
          "h-7 w-7 rounded-full shrink-0 flex items-center justify-center text-[10px] font-medium",
          isUser
            ? "bg-brand-500/20 text-brand-200 border border-brand-500/30"
            : "bg-white dark:bg-zinc-800 border border-black/10 dark:border-white/10 shadow-sm"
        )}
      >
        {isUser ? (
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
        )}
      </div>
      <Message
        from={message.role}
        className={cn(
          "flex-1 max-w-[80%] sm:max-w-[75%] gap-1.5",
          isUser ? "items-end ml-0 justify-start" : "items-start"
        )}
      >
      {/* Attachments — wrapped in Vercel MessageContent so user
          attachments inherit the user-bubble styling. */}
      {message.attachments && message.attachments.length > 0 && (
        <MessageContent>
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
        </MessageContent>
      )}

      {/* Content — Vercel MessageContent is the structural wrapper.
          For user messages it auto-applies the bubble (bg-secondary,
          rounded, padding); AI messages render flat so markdown tables,
          code blocks, and charts use the full available width.

          AI reasoning (CoT) uses the Vercel Reasoning component as a
          sibling of MessageContent. Tool calls are interleaved with the
          text body at the exact positions where the model invoked them
          (tracked via `toolCall.contentOffset`).

          When editing a user message, MessageContent wraps the textarea
          + Save/Cancel controls. The original content is preserved as a
          previousVersion so the user can flip back. */}
      {isEditing && isUser ? (
        <MessageContent>
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
            className="w-full bg-transparent resize-none outline-none text-sm leading-relaxed text-foreground placeholder:text-muted-foreground"
          />
          <div className="flex items-center justify-end gap-1.5">
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
        </MessageContent>
      ) : isUser ? (
        (snapshot.content || isStreaming) && (
          <MessageContent>
            {snapshot.content ? (
              <MessageResponse
                parseIncompleteMarkdown={isStreaming}
              >
                {snapshot.content}
              </MessageResponse>
            ) : isStreaming ? (
              <StreamingCursor />
            ) : null}
          </MessageContent>
        )
      ) : (snapshot.content || isStreaming) ? (
        <>
          {snapshot.reasoning && (
            <Reasoning
              isStreaming={isStreaming && !snapshot.content}
              className="mb-2"
            >
              <ReasoningTrigger />
              <ReasoningContent>{snapshot.reasoning}</ReasoningContent>
            </Reasoning>
          )}
          <MessageContent>
            <InterleavedBody
              content={snapshot.content}
              toolCalls={snapshot.toolCalls}
              streaming={isStreaming}
            />
          </MessageContent>
          {/* Sources — when the assistant used web_search or web_fetch,
              parse the tool output for URLs and display them as
              collapsible source citations below the message. */}
          {!isStreaming && (() => {
            const searchTools = (snapshot.toolCalls ?? []).filter(
              (tc) => tc.name === "web_search" || tc.name === "web_fetch"
            );
            const allUrls: { title: string; url: string }[] = [];
            for (const tc of searchTools) {
              const output = typeof tc.result === "string" ? tc.result : "";
              if (output) allUrls.push(...parseSearchSources(output));
            }
            if (allUrls.length === 0) return null;
            return (
              <Sources className="mt-1">
                <SourcesTrigger count={allUrls.length} />
                <SourcesContent>
                  {allUrls.map((s, i) => (
                    <Source
                      key={`${s.url}-${i}`}
                      href={s.url}
                      title={s.title}
                    >
                      {s.title}
                    </Source>
                  ))}
                </SourcesContent>
              </Sources>
            );
          })()}
        </>
      ) : null}

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

      {/* Action bar — Vercel MessageActions is the structural container.
          Hidden while streaming and when the global `disabled` flag is set
          (e.g. another reply is in flight). */}
      {showActions && !isEditing && (
        <MessageActions
          className={cn(
            "mt-0.5 gap-0.5",
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
        </MessageActions>
      )}
      </Message>
    </div>
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
