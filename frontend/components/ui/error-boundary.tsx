"use client";

/**
 * ErrorBoundary — catches render-time errors in its children and shows a
 * friendly, retryable error card instead of a blank page.
 *
 * Why a class component: React's error-boundary API (`getDerivedStateFromError`
 * + `componentDidCatch`) is only available on class components. Hooks can't
 * catch render errors yet.
 *
 * The "重试" (Retry) button increments an internal `retryKey` state, which
 * is used as the `key` of the wrapped subtree. Changing that key forces
 * React to unmount + remount the children, giving them a clean slate —
 * this is the simplest way to recover from a render error without
 * carrying over corrupted component state.
 */

import * as React from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";
import { Button } from "./button";
import { cn } from "@/lib/utils";

interface ErrorBoundaryProps {
  /** Optional custom title for the error card. */
  title?: string;
  /** Optional className applied to the outer card wrapper. */
  className?: string;
  /** Optional fallback renderer; receives the caught error + a retry callback. */
  fallback?: (error: Error, retry: () => void) => React.ReactNode;
  children: React.ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
  /** Bumped on each retry to force a remount of the children subtree. */
  retryKey: number;
}

export class ErrorBoundary extends React.Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { error: null, retryKey: 0 };
  }

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // Log to the browser console so devs can inspect the component stack
    // without needing the React devtools. We deliberately don't forward
    // to a remote telemetry endpoint — LifeTree has no such pipeline.
    // eslint-disable-next-line no-console
    console.error("[ErrorBoundary] render error:", error, info.componentStack);
  }

  private handleRetry = () => {
    this.setState((prev) => ({
      error: null,
      retryKey: prev.retryKey + 1,
    }));
  };

  render() {
    const { error, retryKey } = this.state;
    const { children, title, className, fallback } = this.props;

    if (error) {
      if (fallback) {
        return <>{fallback(error, this.handleRetry)}</>;
      }
      return (
        <DefaultErrorCard
          error={error}
          title={title}
          onRetry={this.handleRetry}
          className={className}
        />
      );
    }

    // key={retryKey} forces remount on retry → children re-run their
    // render from scratch with fresh state.
    return <div key={retryKey}>{children}</div>;
  }
}

function DefaultErrorCard({
  error,
  title,
  onRetry,
  className,
}: {
  error: Error;
  title?: string;
  onRetry: () => void;
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={cn(
        "surface min-w-0 p-5 space-y-3 border border-red-500/30 bg-red-500/[0.04]",
        className
      )}
    >
      <div className="flex items-start gap-3">
        <AlertTriangle className="h-5 w-5 text-red-400 shrink-0 mt-0.5" />
        <div className="min-w-0 flex-1 space-y-1">
          <h3 className="text-sm font-semibold text-zinc-100 break-words">
            {title ?? "渲染出错"}
          </h3>
          <p className="text-xs text-zinc-400 break-words font-mono leading-relaxed">
            {error.message || String(error)}
          </p>
        </div>
      </div>
      <div className="flex justify-end">
        <Button size="sm" variant="outline" onClick={onRetry}>
          <RotateCcw className="h-3.5 w-3.5 mr-1.5" />
          重试
        </Button>
      </div>
    </div>
  );
}
