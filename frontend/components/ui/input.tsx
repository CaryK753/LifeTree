import * as React from "react";
import { cn } from "@/lib/utils";

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, type, ...props }, ref) => (
    <input
      type={type}
      ref={ref}
      className={cn(
        "flex h-9 w-full rounded-md bg-black/[0.03] dark:bg-white/5 border border-black/10 dark:border-white/10 px-3 py-1 text-sm text-zinc-800 dark:text-zinc-200 placeholder:text-zinc-500 focus:outline-none focus:ring-1 focus:ring-brand-500/40 disabled:cursor-not-allowed disabled:opacity-50",
        className
      )}
      {...props}
    />
  )
);
Input.displayName = "Input";
