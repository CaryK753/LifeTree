"use client";

import { memo, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import type { Components } from "react-markdown";
import { ChevronDown, ChevronRight, Copy, Check } from "lucide-react";
import { EChart, AnimatedTable, TrendBadge } from "@/components/charts/echart";

/**
 * Markdown renderer tuned for chat bubbles.
 *
 * Supports:
 *   - GitHub-flavored markdown (tables, task lists, strikethrough, autolinks)
 *   - Syntax-highlighted code blocks via highlight.js
 *   - ```echarts / ```chart code blocks → rendered as animated ECharts
 *   - ```table-csv code blocks → rendered as AnimatedTable (CSV payload)
 *   - ```table-json code blocks → rendered as AnimatedTable (JSON payload)
 *   - ```trend:value inline gauge (rare; mostly for numeric callouts)
 *
 * Streaming performance: when `streaming` is true, the expensive
 * `rehypeHighlight` pass is skipped — syntax highlighting is only applied
 * once the stream completes. This keeps token-by-token rendering smooth
 * even for long messages with code blocks.
 *
 * The component is memoized so streaming token-by-token updates don't
 * re-render the entire markdown tree on every chunk — only when the content
 * string actually changes.
 */

const components: Components = {
  // Paragraphs: tighten spacing inside chat bubbles.
  p: ({ children }) => <p className="leading-relaxed first:mt-0 last:mb-0 my-2">{children}</p>,

  h1: ({ children }) => <h1 className="text-base font-semibold mt-3 mb-2 first:mt-0">{children}</h1>,
  h2: ({ children }) => <h2 className="text-sm font-semibold mt-3 mb-2 first:mt-0">{children}</h2>,
  h3: ({ children }) => <h3 className="text-sm font-semibold mt-2 mb-1 first:mt-0">{children}</h3>,
  h4: ({ children }) => <h4 className="text-xs font-semibold mt-2 mb-1 first:mt-0 uppercase tracking-wide text-zinc-400">{children}</h4>,
  h5: ({ children }) => <h5 className="text-xs font-semibold mt-2 mb-1 first:mt-0">{children}</h5>,
  h6: ({ children }) => <h6 className="text-xs font-medium mt-2 mb-1 first:mt-0 text-zinc-500">{children}</h6>,

  // Lists.
  ul: ({ children }) => <ul className="list-disc pl-5 my-2 space-y-1">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal pl-5 my-2 space-y-1">{children}</ol>,
  li: ({ children }) => <li className="leading-relaxed">{children}</li>,

  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-brand-300 hover:text-brand-200 underline underline-offset-2 break-words"
    >
      {children}
    </a>
  ),

  // Inline code.
  code: ({ inline, className, children, ...props }: any) => {
    if (inline) {
      return (
        <code
          className="px-1 py-0.5 rounded bg-white/10 text-[0.85em] font-mono text-amber-200 break-words"
          {...props}
        >
          {children}
        </code>
      );
    }
    // Block code is handled by `pre` below — we just style the <code> element.
    return (
      <code className={className} {...props}>
        {children}
      </code>
    );
  },

  // Code block container. Detects special language tags and renders the
  // appropriate visualization component instead of plain text.
  pre: ({ children }) => {
    // The child should be a <code> element with a className like
    // "language-echarts" or "language-table-csv".
    const child: any = Array.isArray(children) ? children[0] : children;
    const className: string = child?.props?.className ?? "";
    const langMatch = className.match(/language-([\w-]+)/);
    const lang = langMatch?.[1]?.toLowerCase();
    const raw: string = String(child?.props?.children ?? "");

    if (lang === "echarts" || lang === "chart") {
      return <ChartBlock raw={raw} />;
    }
    if (lang === "table-csv") {
      return <CsvTableBlock raw={raw} />;
    }
    if (lang === "table-json") {
      return <JsonTableBlock raw={raw} />;
    }
    if (lang === "trend") {
      return <TrendBlock raw={raw} />;
    }

    return <CodeBlock raw={raw} className={className}>{children}</CodeBlock>;
  },

  // Blockquotes.
  blockquote: ({ children }) => (
    <blockquote className="my-2 pl-3 border-l-2 border-brand-500/40 text-zinc-400 italic">
      {children}
    </blockquote>
  ),

  // Tables — horizontal scroll on small screens.
  table: ({ children }) => (
    <div className="my-2 overflow-x-auto">
      <table className="min-w-full text-xs border-collapse">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-white/5">{children}</thead>,
  th: ({ children }) => (
    <th className="border border-white/10 px-2 py-1 text-left font-semibold text-zinc-200">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="border border-white/10 px-2 py-1 text-zinc-300">{children}</td>
  ),

  hr: () => <hr className="my-3 border-white/10" />,

  strong: ({ children }) => <strong className="font-semibold text-zinc-100">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,

  del: ({ children }) => <del className="line-through text-zinc-500">{children}</del>,
};

function MarkdownImpl({
  content,
  streaming = false,
}: {
  content: string;
  streaming?: boolean;
}) {
  // Progressive markdown rendering during streaming.
  //
  // We still render ReactMarkdown while streaming so headings, lists,
  // bold, tables, links, etc. all appear as they arrive — but we skip
  // the expensive `rehypeHighlight` syntax-highlighting pass (which
  // re-tokenizes every code block on every token) until streaming ends.
  // remark-gfm stays on so GFM tables/task-lists/strikethrough work.
  //
  // Performance: ReactMarkdown's parser is fast enough for typical chat
  // message sizes (a few KB). The previous "render plain text while
  // streaming" approach made code blocks and tables appear as raw
  // markdown source until the stream finished, which felt broken.
  //
  // Memoization: the parent already memoizes on `content`, so each new
  // token produces exactly one re-parse — same cost as before.
  const element = useMemo(
    () => (
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={
          streaming
            ? undefined
            : [[rehypeHighlight, { detect: true, ignoreMissing: true }]]
        }
        components={components}
      >
        {content}
      </ReactMarkdown>
    ),
    [content, streaming]
  );
  return <div className="markdown-body text-sm">{element}</div>;
}

export const Markdown = memo(MarkdownImpl);

// ---------- Chart code block ----------

function ChartBlock({ raw }: { raw: string }) {
  const [err, setErr] = useState<string | null>(null);
  const option = useMemo(() => {
    try {
      // Strip trailing commas that LLMs sometimes emit.
      const cleaned = raw
        .replace(/,(\s*[}\]])/g, "$1")
        .trim();
      return JSON.parse(cleaned);
    } catch (e: any) {
      setErr(e?.message ?? "parse error");
      return null;
    }
  }, [raw]);

  if (err || !option) {
    return (
      <div className="my-2 p-3 rounded-md bg-amber-500/10 border border-amber-500/30 text-[11px] text-amber-200 font-mono">
        ⚠ Invalid ECharts JSON: {err}
        <pre className="mt-1 text-amber-100/70 whitespace-pre-wrap">{raw}</pre>
      </div>
    );
  }

  return (
    <div className="my-3 animate-fade-in">
      <EChart option={option} height={300} />
    </div>
  );
}

// ---------- CSV table block ----------

function CsvTableBlock({ raw }: { raw: string }) {
  const { columns, rows, err } = useMemo(() => parseCsvTable(raw), [raw]);
  if (err) {
    return (
      <div className="my-2 p-2 rounded-md bg-red-500/10 border border-red-500/30 text-[11px] text-red-200 font-mono">
        ⚠ {err}
      </div>
    );
  }
  if (rows.length === 0) return null;
  return (
    <div className="my-3">
      <AnimatedTable columns={columns} rows={rows} />
    </div>
  );
}

// ---------- JSON table block ----------

function JsonTableBlock({ raw }: { raw: string }) {
  const { columns, rows, err } = useMemo(() => parseJsonTable(raw), [raw]);
  if (err) {
    return (
      <div className="my-2 p-2 rounded-md bg-red-500/10 border border-red-500/30 text-[11px] text-red-200 font-mono">
        ⚠ {err}
      </div>
    );
  }
  if (rows.length === 0) return null;
  return (
    <div className="my-3">
      <AnimatedTable columns={columns} rows={rows} />
    </div>
  );
}

// ---------- Trend badge block ----------

function TrendBlock({ raw }: { raw: string }) {
  const v = parseFloat(raw.trim());
  if (Number.isNaN(v)) return null;
  return (
    <div className="my-1">
      <TrendBadge value={v} />
    </div>
  );
}

// ---------- Default code block with copy button ----------

function CodeBlock({
  raw,
  className,
  children,
}: {
  raw: string;
  className: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(true);
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(raw);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // ignore
    }
  };

  const langMatch = className.match(/language-([\w-]+)/);
  const lang = langMatch?.[1] ?? "text";
  const isLong = raw.split("\n").length > 12;

  return (
    <div className="my-2 rounded-md bg-[#0b0d12] border border-white/5 overflow-hidden text-xs">
      <div className="flex items-center justify-between px-2.5 py-1 border-b border-white/5 bg-white/[0.02]">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-1 text-[10px] uppercase tracking-wider text-zinc-500 hover:text-zinc-300"
        >
          {open ? (
            <ChevronDown className="h-3 w-3" />
          ) : (
            <ChevronRight className="h-3 w-3" />
          )}
          {lang}
        </button>
        <button
          type="button"
          onClick={copy}
          className="text-zinc-500 hover:text-zinc-200 transition-colors"
          title="Copy"
        >
          {copied ? (
            <Check className="h-3 w-3 text-emerald-400" />
          ) : (
            <Copy className="h-3 w-3" />
          )}
        </button>
      </div>
      {(!isLong || open) && (
        <pre className="p-3 overflow-x-auto text-xs leading-relaxed">
          {children}
        </pre>
      )}
    </div>
  );
}

// ---------- Parsers ----------

function parseCsvTable(
  raw: string
): { columns: { key: string; label: string; align?: "left" | "right" | "center" }[]; rows: Record<string, unknown>[]; err?: string } {
  const lines = raw.split(/\r?\n/).filter((l) => l.trim().length > 0);
  if (lines.length === 0) return { columns: [], rows: [] };
  // Split on | or , — preferring | when present in the header.
  const delim = lines[0].includes("|") ? "|" : ",";
  const split = (l: string) =>
    l.split(delim).map((c) => c.trim().replace(/^"|"$/g, ""));

  type Col = { key: string; label: string; align?: "left" | "right" | "center" };
  const header = split(lines[0]);
  const columns: Col[] = header.map((h) => ({ key: h, label: h }));
  const rows: Record<string, unknown>[] = [];
  for (let i = 1; i < lines.length; i++) {
    const cells = split(lines[i]);
    const row: Record<string, unknown> = {};
    header.forEach((h, idx) => {
      const v = cells[idx] ?? "";
      // Try to coerce numeric values.
      const num = Number(v);
      row[h] = v !== "" && !Number.isNaN(num) && /^-?\d+(\.\d+)?$/.test(v) ? num : v;
    });
    rows.push(row);
  }
  // Right-align columns whose name suggests numeric data.
  for (const c of columns) {
    if (/count|p\b|p50|p10|p90|prob|score|value|n\b|pct|percent|risk/i.test(c.key)) {
      c.align = "right";
    }
  }
  return { columns, rows };
}

function parseJsonTable(
  raw: string
): { columns: { key: string; label: string; align?: "left" | "right" | "center" }[]; rows: Record<string, unknown>[]; err?: string } {
  try {
    const cleaned = raw.replace(/,(\s*[}\]])/g, "$1").trim();
    const parsed = JSON.parse(cleaned);
    if (!Array.isArray(parsed) || parsed.length === 0) {
      return { columns: [], rows: [], err: "Expected non-empty array of objects" };
    }
    // Derive columns from the union of keys (preserving first-seen order).
    const keys: string[] = [];
    for (const row of parsed) {
      if (row && typeof row === "object") {
        for (const k of Object.keys(row)) {
          if (!keys.includes(k)) keys.push(k);
        }
      }
    }
    const columns = keys.map((k) => ({
      key: k,
      label: k,
      align: (/count|p\b|p50|p10|p90|prob|score|value|n\b|pct|percent|risk/i.test(k)
        ? "right"
        : "left") as "right" | "left",
    }));
    const rows = parsed.map((r) => (r && typeof r === "object" ? r : { value: r }));
    return { columns, rows };
  } catch (e: any) {
    return { columns: [], rows: [], err: e?.message ?? "Invalid JSON" };
  }
}
