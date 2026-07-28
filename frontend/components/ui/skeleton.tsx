/**
 * Skeleton — a shimmering placeholder block used while data loads.
 *
 * Why: list pages previously showed a bare "Loading…" text string, which
 * makes the layout jump when data arrives and gives no sense of what's
 * coming. A skeleton matches the final content shape so the transition
 * to real data is smooth and the user can anticipate the structure.
 *
 * The shimmer uses a left-to-right gradient sweep that loops. It
 * respects `prefers-reduced-motion` (the sweep is replaced by a static
 * faint pulse so motion-sensitive users aren't distracted).
 */
import { cn } from "@/lib/utils";

export function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-md bg-black/[0.06] dark:bg-white/[0.08]",
        "animate-shimmer",
        className
      )}
      {...props}
    />
  );
}
