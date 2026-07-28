"use client";

import type { ComponentProps, ReactNode } from "react";
import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
  CommandShortcut,
} from "@/components/ui/command";
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { AIAvatar } from "@/components/common/ai-avatar";
import { cn } from "@/lib/utils";

export const ModelSelector = (props: ComponentProps<typeof Dialog>) => <Dialog {...props} />;
export const ModelSelectorTrigger = (props: ComponentProps<typeof DialogTrigger>) => <DialogTrigger {...props} />;

export function ModelSelectorContent({
  className, children, title = "Model Selector", ...props
}: ComponentProps<typeof DialogContent> & { title?: ReactNode }) {
  return (
    <DialogContent aria-describedby={undefined} className={cn("border-none p-0", className)} {...props}>
      <DialogTitle className="sr-only">{title}</DialogTitle>
      <Command>{children}</Command>
    </DialogContent>
  );
}

export const ModelSelectorDialog = (props: ComponentProps<typeof CommandDialog>) => <CommandDialog {...props} />;
export const ModelSelectorInput = (props: ComponentProps<typeof CommandInput>) => <CommandInput {...props} />;
export const ModelSelectorList = (props: ComponentProps<typeof CommandList>) => <CommandList {...props} />;
export const ModelSelectorEmpty = (props: ComponentProps<typeof CommandEmpty>) => <CommandEmpty {...props} />;
export const ModelSelectorGroup = (props: ComponentProps<typeof CommandGroup>) => <CommandGroup {...props} />;
export const ModelSelectorItem = (props: ComponentProps<typeof CommandItem>) => <CommandItem {...props} />;
export const ModelSelectorShortcut = (props: ComponentProps<typeof CommandShortcut>) => <CommandShortcut {...props} />;
export const ModelSelectorSeparator = (props: ComponentProps<typeof CommandSeparator>) => <CommandSeparator {...props} />;

export function ModelSelectorLogo({ provider, className }: { provider: string; className?: string }) {
  return <AIAvatar name={provider} protocol={provider} size={16} className={className} />;
}

export const ModelSelectorLogoGroup = ({ className, ...props }: ComponentProps<"div">) => (
  <div className={cn("flex shrink-0 items-center -space-x-1", className)} {...props} />
);
export const ModelSelectorName = ({ className, ...props }: ComponentProps<"span">) => (
  <span className={cn("min-w-0 flex-1 truncate text-left", className)} {...props} />
);
