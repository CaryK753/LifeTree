"use client";

import { Badge } from "@/components/ui/badge";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { ChevronDownIcon, FileTextIcon, LinkIcon } from "lucide-react";
import type { ComponentProps, HTMLAttributes } from "react";
import { useState } from "react";

export type SourcesProps = HTMLAttributes<HTMLDivElement> & {
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
};

export const Sources = ({
  className,
  open,
  defaultOpen = false,
  onOpenChange,
  ...props
}: SourcesProps) => (
  <Collapsible
    open={open}
    defaultOpen={defaultOpen}
    onOpenChange={onOpenChange}
    className={cn(
      "flex w-full flex-col items-start gap-2 rounded-lg border bg-muted/30 text-sm",
      className
    )}
    {...props}
  />
);

export type SourcesTriggerProps = ComponentProps<typeof CollapsibleTrigger> & {
  count?: number;
  label?: string;
};

export const SourcesTrigger = ({
  count,
  label,
  className,
  children,
  ...props
}: SourcesTriggerProps) => (
  <CollapsibleTrigger
    className={cn(
      "flex w-full items-center gap-2 rounded-lg p-2 text-xs font-medium text-muted-foreground hover:bg-muted/50 [&[data-state=open]>svg.chevron]:rotate-180",
      className
    )}
    {...props}
  >
    {children ?? (
      <>
        <LinkIcon className="size-3.5" />
        <span>
          {label ?? (count !== undefined ? `Used ${count} ${count === 1 ? "source" : "sources"}` : "Sources")}
        </span>
        <ChevronDownIcon className="chevron ml-auto size-3.5 transition-transform" />
      </>
    )}
  </CollapsibleTrigger>
);

export type SourcesContentProps = HTMLAttributes<HTMLDivElement>;

export const SourcesContent = ({
  className,
  ...props
}: SourcesContentProps) => (
  <CollapsibleContent
    className={cn("flex w-full flex-col gap-1.5 px-2 pb-2", className)}
    {...(props as ComponentProps<typeof CollapsibleContent>)}
  />
);

export type SourceProps = ComponentProps<"a"> & {
  title?: string;
};

export const Source = ({ className, title, children, ...props }: SourceProps) => (
  <a
    target="_blank"
    rel="noopener noreferrer"
    className={cn(
      "flex items-center gap-2 rounded-md border bg-background px-2.5 py-1.5 text-xs transition-colors hover:bg-muted/50",
      className
    )}
    {...props}
  >
    <FileTextIcon className="size-3 shrink-0 text-muted-foreground" />
    <span className="min-w-0 flex-1 truncate">
      {children ?? title ?? props.href}
    </span>
  </a>
);

/**
 * Hook to manage Sources open state.
 */
export const useSources = (defaultOpen = false) => {
  const [open, setOpen] = useState(defaultOpen);
  return { open, setOpen };
};

/**
 * Parse a web_search tool output string (markdown with [title](url) links)
 * into a list of source objects for the Sources component.
 *
 * The backend _web_search function returns:
 *   "1. [Title](https://example.com)\n   Content snippet..."
 *
 * This extracts the title and URL pairs.
 */
export interface ParsedSource {
  title: string;
  url: string;
}

export function parseSearchSources(toolOutput: string): ParsedSource[] {
  const sources: ParsedSource[] = [];
  // Match markdown links: [title](url)
  const linkRegex = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g;
  let match: RegExpExecArray | null;
  while ((match = linkRegex.exec(toolOutput)) !== null) {
    sources.push({ title: match[1], url: match[2] });
  }
  // Deduplicate by URL
  const seen = new Set<string>();
  return sources.filter((s) => {
    if (seen.has(s.url)) return false;
    seen.add(s.url);
    return true;
  });
}
