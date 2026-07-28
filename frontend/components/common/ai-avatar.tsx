"use client";

/**
 * AIAvatar — renders a brand icon for an AI provider/model.
 *
 * Wraps `@lobehub/icons` so the rest of the app doesn't need to know
 * which specific icon component to import for each protocol/provider.
 * Falls back to a Sparkles icon when the provider is unknown or when
 * `@lobehub/icons` doesn't ship a matching icon.
 *
 * Used in:
 *   - chat-panel.tsx — the assistant's avatar on each message
 *   - platform-config.tsx — provider cards & model rows
 *
 * The mapping table below links our internal `protocol` values to the
 * PascalCase icon ids exported by `@lobehub/icons`. See
 * https://lobehub.com/icons for the full catalogue.
 */

import { memo } from "react";
import {
  OpenAI,
  Anthropic,
  AlibabaCloud,
  Google,
  DeepSeek,
  Zhipu,
  ByteDance,
  Microsoft,
  Aws,
  Bedrock,
  Mistral,
  Cohere,
  Meta,
  Gemini,
  Perplexity,
  Github,
  LobeHub,
  Ollama,
  Qwen,
} from "@lobehub/icons";
import { Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Map our internal `protocol` value (stored on Provider rows) to a
 * `@lobehub/icons` component. The mapping is intentionally generous —
 * if two protocols share the same vendor (e.g. `bailian` and
 * `bailian_rerank`), they both resolve to the AlibabaCloud icon.
 */
const PROTOCOL_ICON: Record<string, React.ComponentType<{ size?: number; className?: string }>> = {
  openai_compatible: OpenAI,
  openai: OpenAI,
  anthropic: Anthropic,
  claude: Anthropic,
  bailian: AlibabaCloud,
  bailian_rerank: AlibabaCloud,
  alibaba: AlibabaCloud,
  alibaba_cloud: AlibabaCloud,
  google: Google,
  gemini: Gemini,
  deepseek: DeepSeek,
  zhipu: Zhipu,
  byte_dance: ByteDance,
  bytedance: ByteDance,
  microsoft: Microsoft,
  azure: Microsoft,
  aws: Aws,
  bedrock: Bedrock,
  mistral: Mistral,
  cohere: Cohere,
  meta: Meta,
  llama: Meta,
  perplexity: Perplexity,
  github: Github,
  lobehub: LobeHub,
  ollama: Ollama,
  qwen: Qwen,
};

/**
 * Map a provider/model name string (case-insensitive) to an icon.
 * Useful when we don't have a `protocol` field — e.g. matching by the
 * model name on a chat message ("gpt-4o" → OpenAI, "claude-3-opus" → Anthropic).
 */
const NAME_KEYWORDS: Array<{ keywords: string[]; Icon: React.ComponentType<{ size?: number; className?: string }> }> = [
  { keywords: ["openai", "gpt", "chatgpt", "o1", "o3", "o4"], Icon: OpenAI },
  { keywords: ["anthropic", "claude"], Icon: Anthropic },
  { keywords: ["qwen", "tongyi"], Icon: Qwen },
  { keywords: ["alibaba", "bailian", "dashscope"], Icon: AlibabaCloud },
  { keywords: ["ollama"], Icon: Ollama },
  { keywords: ["google", "gemini", "bard", "palm"], Icon: Gemini },
  { keywords: ["deepseek"], Icon: DeepSeek },
  { keywords: ["zhipu", "glm", "chatglm"], Icon: Zhipu },
  { keywords: ["bytedance", "doubao", "wenkong"], Icon: ByteDance },
  { keywords: ["microsoft", "azure", "copilot"], Icon: Microsoft },
  { keywords: ["aws", "bedrock"], Icon: Aws },
  { keywords: ["mistral", "mixtral"], Icon: Mistral },
  { keywords: ["cohere", "command-r"], Icon: Cohere },
  { keywords: ["meta", "llama"], Icon: Meta },
  { keywords: ["perplexity"], Icon: Perplexity },
];

export interface AIAvatarProps {
  /** Provider protocol (preferred — most stable identifier). */
  protocol?: string;
  /** Provider or model name — used as fallback when protocol is unknown. */
  name?: string;
  /** Pixel size of the rendered icon. Default: 24. */
  size?: number;
  className?: string;
}

/**
 * Resolve which icon component to render. Returns `null` if no match —
 * the caller can fall back to a generic Sparkles icon.
 */
function resolveIcon(
  protocol?: string,
  name?: string
): React.ComponentType<{ size?: number; className?: string }> | null {
  if (protocol) {
    const p = protocol.toLowerCase();
    if (PROTOCOL_ICON[p]) return PROTOCOL_ICON[p];
  }
  if (name) {
    const n = name.toLowerCase();
    for (const { keywords, Icon } of NAME_KEYWORDS) {
      if (keywords.some((k) => n.includes(k))) return Icon;
    }
  }
  return null;
}

export const AIAvatar = memo(function AIAvatar({
  protocol,
  name,
  size = 24,
  className,
}: AIAvatarProps) {
  const Icon = resolveIcon(protocol, name);
  if (!Icon) {
    return (
      <Sparkles
        size={size}
        className={cn("text-brand-500", className)}
        aria-label="AI"
      />
    );
  }
  return <Icon size={size} className={className} />;
});

export default AIAvatar;
