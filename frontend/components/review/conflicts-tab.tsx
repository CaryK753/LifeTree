"use client";

/**
 * ConflictsTab — extracted from IntelligenceReviewSections. Lists only
 * the source-conclusion conflicts so they can be reviewed in isolation
 * from the rest of the unified review inbox.
 */

import { useState } from "react";
import { Check, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { useUnifiedReview } from "@/lib/hooks";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { useT } from "@/lib/i18n/provider";

export function ConflictsTab() {
  const t = useT();
  const toast = useToast();
  const { data, mutate, isLoading } = useUnifiedReview();
  const [working, setWorking] = useState<string | null>(null);

  async function run(id: string, operation: () => Promise<unknown>) {
    setWorking(id);
    try {
      await operation();
      await mutate();
      toast({ title: t("review.intelligence.saved"), variant: "success" });
    } catch (error: any) {
      toast({
        title: t("review.intelligence.failed"),
        description: error?.message,
        variant: "error",
      });
    } finally {
      setWorking(null);
    }
  }

  if (isLoading) {
    return <Skeleton className="h-28 w-full" />;
  }

  const conflicts = data?.conflicts ?? [];

  if (conflicts.length === 0) {
    return (
      <Card>
        <CardContent className="py-12 text-center space-y-3">
          <div className="mx-auto h-12 w-12 rounded-full bg-emerald-500/10 flex items-center justify-center">
            <Check className="h-6 w-6 text-emerald-500" />
          </div>
          <div className="text-sm text-foreground">{t("review.conflicts.empty")}</div>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-2">
      {conflicts.map((conflict) => {
        const id = `${conflict.subject_id}:${conflict.predicate}`;
        return (
          <Card key={id}>
            <CardContent className="p-4">
              <div className="text-sm font-medium text-foreground">
                {t("review.conflicts.title")} · {conflict.predicate}
              </div>
              <div className="mt-2 flex flex-wrap gap-2">
                {conflict.conflicting_values
                  .filter((value) => value.source_id)
                  .map((value) => (
                    <Button
                      key={`${value.object_id}:${value.source_id}`}
                      size="sm"
                      variant="outline"
                      disabled={working === id}
                      onClick={() =>
                        run(id, () =>
                          api.resolveSourceConflict(conflict, value.source_id!)
                        )
                      }
                    >
                      {working === id ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Check className="h-3.5 w-3.5" />
                      )}
                      <span className="ml-1.5 max-w-40 truncate">
                        {value.source_title || value.source_id}
                      </span>
                    </Button>
                  ))}
              </div>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
