import * as React from "react";
import { cn } from "@/lib/utils";

export const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
  <textarea
    ref={ref}
    className={cn(
      "flex min-h-[80px] w-full rounded-md bg-black/[0.03] dark:bg-white/5 border border-black/10 dark:border-white/10 px-3 py-2 text-sm text-zinc-800 dark:text-zinc-200 placeholder:text-zinc-500 focus:outline-none focus:ring-1 focus:ring-brand-500/40 disabled:cursor-not-allowed disabled:opacity-50 resize-y",
      className
    )}
    {...props}
  />
));
Textarea.displayName = "Textarea";
