"use client";

import { Badge } from "@/components/ui/badge";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import type { LucideIcon } from "lucide-react";
import {
  BrainIcon,
  CheckIcon,
  ChevronRightIcon,
  LoaderIcon,
  SearchIcon,
  SparklesIcon,
} from "lucide-react";
import type { ComponentProps, HTMLAttributes, ReactNode } from "react";
import {
  createContext,
  useContext,
  useState,
} from "react";

// ============================================================================
// Context
// ============================================================================

interface ChainOfThoughtContextType {
  isOpen: boolean;
  setIsOpen: (open: boolean) => void;
}

const ChainOfThoughtContext = createContext<ChainOfThoughtContextType | null>(
  null
);

const useChainOfThought = () => {
  const ctx = useContext(ChainOfThoughtContext);
  if (!ctx) {
    throw new Error(
      "ChainOfThought components must be used within <ChainOfThought>"
    );
  }
  return ctx;
};

// ============================================================================
// Main components
// ============================================================================

export type ChainOfThoughtProps = HTMLAttributes<HTMLDivElement> & {
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
};

export const ChainOfThought = ({
  className,
  open,
  defaultOpen = true,
  onOpenChange,
  ...props
}: ChainOfThoughtProps) => {
  const [internalOpen, setInternalOpen] = useState(defaultOpen);
  const isOpen = open ?? internalOpen;
  const setIsOpen = (v: boolean) => {
    setInternalOpen(v);
    onOpenChange?.(v);
  };

  return (
    <ChainOfThoughtContext.Provider value={{ isOpen, setIsOpen }}>
      <Collapsible
        open={isOpen}
        onOpenChange={setIsOpen}
        className={cn(
          "flex w-full flex-col gap-1 rounded-lg border bg-muted/20 text-sm",
          className
        )}
        {...props}
      />
    </ChainOfThoughtContext.Provider>
  );
};

export type ChainOfThoughtHeaderProps = ComponentProps<
  typeof CollapsibleTrigger
> & {
  children?: ReactNode;
};

export const ChainOfThoughtHeader = ({
  className,
  children,
  ...props
}: ChainOfThoughtHeaderProps) => (
  <CollapsibleTrigger
    className={cn(
      "flex w-full items-center gap-2 rounded-lg p-2 text-xs font-medium text-muted-foreground hover:bg-muted/50 [&[data-state=open]>svg.chevron]:rotate-90",
      className
    )}
    {...props}
  >
    {children ?? (
      <>
        <BrainIcon className="size-3.5" />
        <span>Chain of Thought</span>
        <ChevronRightIcon className="chevron ml-auto size-3.5 transition-transform" />
      </>
    )}
  </CollapsibleTrigger>
);

export type ChainOfThoughtStepProps = HTMLAttributes<HTMLDivElement> & {
  icon?: LucideIcon;
  label?: string;
  description?: string;
  status?: "complete" | "active" | "pending";
};

const stepIcons = {
  search: SearchIcon,
  sparkles: SparklesIcon,
};

export const ChainOfThoughtStep = ({
  className,
  icon: Icon,
  label,
  description,
  status = "complete",
  children,
  ...props
}: ChainOfThoughtStepProps) => {
  const StepIcon = Icon ?? SparklesIcon;
  return (
    <div
      className={cn(
        "flex items-start gap-2 px-2 py-1.5 transition-opacity",
        status === "pending" && "opacity-40",
        className
      )}
      {...props}
    >
      <div className="mt-0.5 shrink-0">
        {status === "active" ? (
          <LoaderIcon className="size-3.5 animate-spin text-muted-foreground" />
        ) : status === "complete" ? (
          <StepIcon className="size-3.5 text-emerald-500 dark:text-emerald-400" />
        ) : (
          <StepIcon className="size-3.5 text-muted-foreground" />
        )}
      </div>
      <div className="flex-1 min-w-0">
        {label && (
          <div className="text-xs font-medium text-foreground">{label}</div>
        )}
        {description && (
          <div className="text-xs text-muted-foreground">{description}</div>
        )}
        {children && (
          <div className="mt-1 text-xs text-muted-foreground">{children}</div>
        )}
      </div>
    </div>
  );
};

export type ChainOfThoughtSearchResultsProps = HTMLAttributes<HTMLDivElement>;

export const ChainOfThoughtSearchResults = ({
  className,
  ...props
}: ChainOfThoughtSearchResultsProps) => (
  <div
    className={cn("flex flex-wrap gap-1 px-2 pb-1", className)}
    {...props}
  />
);

export type ChainOfThoughtSearchResultProps = ComponentProps<typeof Badge>;

export const ChainOfThoughtSearchResult = ({
  className,
  children,
  ...props
}: ChainOfThoughtSearchResultProps) => (
  <Badge
    variant="default"
    className={cn("gap-1 text-[10px]", className)}
    {...props}
  >
    <SearchIcon className="size-2.5" />
    {children}
  </Badge>
);

export type ChainOfThoughtContentProps = ComponentProps<
  typeof CollapsibleContent
>;

export const ChainOfThoughtContent = ({
  className,
  ...props
}: ChainOfThoughtContentProps) => (
  <CollapsibleContent
    className={cn("flex flex-col gap-0.5 pb-1", className)}
    {...props}
  />
);

export type ChainOfThoughtImageProps = HTMLAttributes<HTMLDivElement> & {
  caption?: string;
};

export const ChainOfThoughtImage = ({
  className,
  caption,
  children,
  ...props
}: ChainOfThoughtImageProps) => (
  <div
    className={cn("flex flex-col gap-1 px-2 py-1", className)}
    {...props}
  >
    {children}
    {caption && (
      <span className="text-[10px] text-muted-foreground">{caption}</span>
    )}
  </div>
);
