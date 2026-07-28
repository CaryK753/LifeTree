"use client";

/**
 * ScenarioEvolution — timeline visualization of LLM-projected future events.
 *
 * Renders a scenario's self-evolution projection as a horizontal timeline:
 *   - X axis = months from now (0 → horizon)
 *   - Each projected event is a node positioned at its month
 *   - Nodes are color-coded by type (milestone/risk/opportunity/decision)
 *   - A probability trajectory line shows how P(success) evolves over time
 *   - Click an event to see its description, probability, and impact
 *
 * This is the "自演化" (self-evolution) view — the LLM projects future
 * events based on the user's long-term accumulated data (profile, memories,
 * requirements, risk factors), and the frontend renders them as actionable
 * nodes the user can explore.
 */

import { useState, useMemo, useEffect, type FC } from "react";
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  Handle,
  Position,
  type Node,
  type Edge,
  type NodeProps,
  type NodeTypes,
  MarkerType,
  useNodesState,
  useEdgesState,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  CheckCircle2,
  AlertTriangle,
  Lightbulb,
  GitFork,
  Loader2,
  Sparkles,
  RefreshCw,
  TrendingUp,
  TrendingDown,
  Clock,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";
import { api, type EvolutionProjection, type ProjectedEvent } from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";

// ---------- Constants ----------

const NODE_WIDTH = 200;
const NODE_HEIGHT = 100;
const MONTH_PX = 140; // horizontal pixels per month
const TOP_PADDING = 80;
const LEFT_PADDING = 60;

// ---------- Event type metadata ----------

interface EventTypeMeta {
  icon: FC<{ className?: string }>;
  color: string;
  bg: string;
  border: string;
  row: number; // Y-axis row to avoid overlapping events in the same month
}

const TYPE_META: Record<ProjectedEvent["type"], EventTypeMeta> = {
  milestone: {
    icon: CheckCircle2,
    color: "text-emerald-600 dark:text-emerald-400",
    bg: "bg-emerald-500/10",
    border: "border-emerald-500/30",
    row: 0,
  },
  opportunity: {
    icon: Lightbulb,
    color: "text-sky-600 dark:text-sky-400",
    bg: "bg-sky-500/10",
    border: "border-sky-500/30",
    row: 1,
  },
  decision: {
    icon: GitFork,
    color: "text-amber-600 dark:text-amber-400",
    bg: "bg-amber-500/10",
    border: "border-amber-500/30",
    row: 2,
  },
  risk: {
    icon: AlertTriangle,
    color: "text-red-600 dark:text-red-400",
    bg: "bg-red-500/10",
    border: "border-red-500/30",
    row: 3,
  },
};

// ---------- Projected event node ----------

// React Flow requires Node.data to satisfy Record<string, unknown>, so we
// widen the typed payload to a record via an index signature. Casting is
// contained to the node components below.
type EventFlowData = ProjectedEvent & { selected?: boolean } & Record<string, unknown>;
type AxisFlowData = { month: number; p?: number } & Record<string, unknown>;
type EventFlowNode = Node<EventFlowData, "event">;
type AxisFlowNode = Node<AxisFlowData, "axis">;

function EventNode({ data }: NodeProps<EventFlowNode>) {
  const d = data as unknown as ProjectedEvent & { selected?: boolean };
  const meta = TYPE_META[d.type];
  const Icon = meta.icon;
  const isPositiveImpact = d.impact >= 0;

  return (
    <div
      className={cn(
        "group relative rounded-lg border bg-surface shadow-md transition-all cursor-pointer",
        "w-[200px] pointer-events-auto",
        d.selected
          ? "ring-2 ring-brand-400/40 shadow-lg"
          : "hover:shadow-lg hover:border-black/20 dark:hover:border-white/20"
      )}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!w-1.5 !h-1.5 !bg-zinc-400"
      />
      <div className={cn("p-2.5 space-y-1.5", meta.bg, meta.border, "rounded-t-lg border-b")}>
        <div className="flex items-center gap-1.5">
          <Icon className={cn("h-3.5 w-3.5 shrink-0", meta.color)} />
          <span className="text-[10px] uppercase tracking-wider font-medium text-zinc-600 dark:text-zinc-400">
            M{d.month}
          </span>
          <span className={cn("ml-auto text-[9px] font-mono px-1 py-0.5 rounded", meta.bg, meta.color)}>
            {Math.round(d.probability * 100)}%
          </span>
        </div>
        <div className="text-xs font-medium text-zinc-900 dark:text-zinc-100 leading-snug line-clamp-2">
          {d.title}
        </div>
      </div>
      <div className="px-2.5 py-1.5 flex items-center justify-between">
        <span className="text-[9px] text-zinc-500 dark:text-zinc-400">
          {d.dependencies.length > 0
            ? `dep: ${d.dependencies.length}`
            : "—"}
        </span>
        <span
          className={cn(
            "inline-flex items-center gap-0.5 text-[9px] font-medium",
            isPositiveImpact ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"
          )}
        >
          {isPositiveImpact ? (
            <TrendingUp className="h-2.5 w-2.5" />
          ) : (
            <TrendingDown className="h-2.5 w-2.5" />
          )}
          {d.impact > 0 ? "+" : ""}
          {Math.round(d.impact * 100)}%
        </span>
      </div>
      <Handle
        type="source"
        position={Position.Right}
        className="!w-1.5 !h-1.5 !bg-zinc-400"
      />
    </div>
  );
}

// ---------- Timeline axis node (decorative) ----------

function MonthAxisNode({ data }: NodeProps<AxisFlowNode>) {
  const d = data as unknown as { month: number; p?: number };
  return (
    <div className="flex flex-col items-center pointer-events-none">
      <div className="text-[10px] text-zinc-400 dark:text-zinc-500 font-mono">
        {d.month === 0 ? "Now" : `M${d.month}`}
      </div>
      {d.p != null && (
        <div className="text-[9px] text-brand-600 dark:text-brand-400 font-semibold tabular-nums">
          {Math.round(d.p * 100)}%
        </div>
      )}
    </div>
  );
}

const nodeTypes: NodeTypes = {
  event: EventNode as unknown as NodeTypes["event"],
  axis: MonthAxisNode as unknown as NodeTypes["event"],
};

// ---------- Layout ----------

function buildTimeline(
  projection: EvolutionProjection
): { nodes: Node[]; edges: Edge[] } {
  const events = [...projection.projected_events].sort((a, b) => a.month - b.month);

  // Group events by month to stack them vertically when multiple events
  // share the same month.
  const byMonth = new Map<number, ProjectedEvent[]>();
  for (const ev of events) {
    const arr = byMonth.get(ev.month) ?? [];
    arr.push(ev);
    byMonth.set(ev.month, arr);
  }

  const nodes: Node[] = [];
  const edges: Edge[] = [];

  // Month axis nodes along the bottom — shows the probability trajectory
  // as a sequence of P(success) values at each month.
  for (let m = 0; m <= projection.horizon_months; m += 3) {
    const trajPoint = projection.trajectory.find((t) => t.month === m);
    nodes.push({
      id: `axis-${m}`,
      type: "axis",
      position: {
        x: LEFT_PADDING + m * MONTH_PX,
        y: TOP_PADDING + 4 * (NODE_HEIGHT + 40) + 20,
      },
      data: { month: m, p: trajPoint?.p },
      draggable: false,
      selectable: false,
    });
  }

  // Event nodes
  const titleToId = new Map<string, string>();
  events.forEach((ev, i) => {
    const id = `ev-${i}`;
    titleToId.set(ev.title, id);

    const sameMonthCount = byMonth.get(ev.month)?.indexOf(ev) ?? 0;
    const row = TYPE_META[ev.type].row + sameMonthCount;

    nodes.push({
      id,
      type: "event",
      position: {
        x: LEFT_PADDING + ev.month * MONTH_PX,
        y: TOP_PADDING + row * (NODE_HEIGHT + 20),
      },
      data: { ...ev },
      draggable: false,
    });
  });

  // Dependency edges
  events.forEach((ev, i) => {
    for (const dep of ev.dependencies) {
      const depId = titleToId.get(dep);
      if (depId) {
        edges.push({
          id: `edge-${depId}-to-ev-${i}`,
          source: depId,
          target: `ev-${i}`,
          type: "smoothstep",
          animated: true,
          style: { stroke: "#71717a", strokeWidth: 1.5, strokeDasharray: "4 3" },
          markerEnd: { type: MarkerType.ArrowClosed, color: "#71717a" },
        });
      }
    }
  });

  return { nodes, edges };
}

// ---------- Main component ----------

interface ScenarioEvolutionProps {
  scenarioId: string;
  scenarioName: string;
  initialProjection?: EvolutionProjection | null;
}

function EvolutionFlow({
  scenarioId,
  scenarioName,
  initialProjection,
}: ScenarioEvolutionProps) {
  const t = useT();
  const toast = useToast();
  const [projection, setProjection] = useState<EvolutionProjection | null>(
    initialProjection ?? null
  );
  const [loading, setLoading] = useState(false);
  const [selectedTitle, setSelectedTitle] = useState<string | null>(null);

  const { nodes, edges } = useMemo(() => {
    if (!projection) return { nodes: [], edges: [] };
    const built = buildTimeline(projection);
    // Mark selected node
    return {
      nodes: built.nodes.map((n) =>
        n.type === "event" && (n.data as unknown as ProjectedEvent).title === selectedTitle
          ? { ...n, data: { ...n.data, selected: true } }
          : n
      ),
      edges: built.edges,
    };
  }, [projection, selectedTitle]);

  const [nodesState, setNodes, onNodesChange] = useNodesState(nodes);
  const [edgesState, setEdges, onEdgesChange] = useEdgesState(edges);

  // Re-sync when projection or selection changes. useEffect (not useMemo)
  // because we're mutating state — useMemo-for-side-effects is an anti-
  // pattern that can cause stale renders under React 18 StrictMode.
  useEffect(() => {
    setNodes(nodes);
  }, [nodes, setNodes]);
  useEffect(() => {
    setEdges(edges);
  }, [edges, setEdges]);

  async function handleEvolve() {
    setLoading(true);
    try {
      const result = await api.evolveScenario(scenarioId);
      setProjection(result);
      toast({
        title: t("scenarioEvolution.evolved"),
        variant: "success",
      });
    } catch (e: any) {
      toast({
        title: t("scenarioEvolution.failed"),
        description: e?.message,
        variant: "error",
      });
    } finally {
      setLoading(false);
    }
  }

  const selectedEvent = projection?.projected_events.find(
    (e) => e.title === selectedTitle
  );

  if (!projection) {
    return (
      <div className="flex flex-col items-center justify-center h-full min-h-[400px] gap-4 p-8 text-center">
        <div className="h-14 w-14 rounded-full bg-brand-500/10 flex items-center justify-center">
          <Sparkles className="h-7 w-7 text-brand-600 dark:text-brand-400" />
        </div>
        <div className="space-y-1.5 max-w-md">
          <h3 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">
            {t("scenarioEvolution.emptyTitle")}
          </h3>
          <p className="text-sm text-zinc-500 dark:text-zinc-400 leading-relaxed">
            {t("scenarioEvolution.emptyDesc", { name: scenarioName })}
          </p>
        </div>
        <Button onClick={handleEvolve} disabled={loading}>
          {loading ? (
            <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
          ) : (
            <Sparkles className="h-4 w-4 mr-1.5" />
          )}
          {loading ? t("scenarioEvolution.evolving") : t("scenarioEvolution.evolveBtn")}
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="shrink-0 px-4 py-3 border-b border-black/5 dark:border-white/5 space-y-2">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-brand-600 dark:text-brand-400 shrink-0" />
              <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100 truncate">
                {scenarioName}
              </h3>
              {projection.cached && (
                <span className="text-[9px] px-1.5 py-0.5 rounded-full border border-zinc-500/30 text-zinc-500 dark:text-zinc-400 shrink-0">
                  {t("scenarioEvolution.cached")}
                </span>
              )}
            </div>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1 line-clamp-2">
              {projection.summary}
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={handleEvolve}
            disabled={loading}
            className="shrink-0"
          >
            {loading ? (
              <Loader2 className="h-3 w-3 mr-1 animate-spin" />
            ) : (
              <RefreshCw className="h-3 w-3 mr-1" />
            )}
            {t("scenarioEvolution.reEvolve")}
          </Button>
        </div>

        {/* Quick stats */}
        <div className="flex items-center gap-3 flex-wrap text-[11px]">
          <span className="inline-flex items-center gap-1 text-zinc-500 dark:text-zinc-400">
            <Clock className="h-3 w-3" />
            {t("scenarioEvolution.horizon", { months: projection.horizon_months })}
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="text-zinc-500 dark:text-zinc-400">
              {t("scenarioEvolution.finalProb")}
            </span>
            <span className="font-semibold text-brand-600 dark:text-brand-400 tabular-nums">
              {Math.round(projection.final_probability * 100)}%
            </span>
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="text-zinc-500 dark:text-zinc-400">
              {t("scenarioEvolution.confidence")}
            </span>
            <span className="font-semibold text-zinc-700 dark:text-zinc-300 tabular-nums">
              {Math.round(projection.confidence * 100)}%
            </span>
          </span>
          <span className="inline-flex items-center gap-1 text-zinc-500 dark:text-zinc-400">
            {t("scenarioEvolution.eventsCount", { count: projection.projected_events.length })}
          </span>
        </div>
      </div>

      {/* Canvas + detail panel */}
      <div className="flex-1 min-h-0 flex">
        <div className="flex-1 min-h-0 relative">
          <ReactFlow
            nodes={nodesState}
            edges={edgesState}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={(_, node) => {
              if (node.type === "event") {
                setSelectedTitle((node.data as unknown as ProjectedEvent).title);
              }
            }}
            nodeTypes={nodeTypes}
            fitView
            fitViewOptions={{ padding: 0.15, maxZoom: 1.2 }}
            minZoom={0.3}
            maxZoom={2}
            panOnScroll
            zoomOnScroll={false}
            proOptions={{ hideAttribution: true }}
          >
            <Background variant={BackgroundVariant.Dots} gap={20} size={1} className="opacity-40" />
            <Controls className="!bg-surface !border-black/10 dark:!border-white/10" />
            <MiniMap
              className="!bg-surface !border-black/10 dark:!border-white/10"
              nodeColor={(node) => {
                if (node.type !== "event") return "#a1a1aa";
                const ev = node.data as unknown as ProjectedEvent;
                return ev.type === "milestone"
                  ? "#10b981"
                  : ev.type === "risk"
                  ? "#ef4444"
                  : ev.type === "opportunity"
                  ? "#0ea5e9"
                  : "#f59e0b";
              }}
              pannable
              zoomable
            />
          </ReactFlow>
        </div>

        {/* Event detail sidebar */}
        {selectedEvent && (
          <aside className="w-72 shrink-0 border-l border-black/5 dark:border-white/5 p-4 overflow-y-auto bg-surface">
            <div className="flex items-start justify-between gap-2 mb-3">
              <div className="min-w-0">
                <div className="flex items-center gap-1.5 mb-1">
                  {(() => {
                    const meta = TYPE_META[selectedEvent.type];
                    const Icon = meta.icon;
                    return <Icon className={cn("h-3.5 w-3.5", meta.color)} />;
                  })()}
                  <span className="text-[10px] uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
                    {t(`scenarioEvolution.type_${selectedEvent.type}`)}
                  </span>
                </div>
                <h4 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                  {selectedEvent.title}
                </h4>
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6 shrink-0"
                onClick={() => setSelectedTitle(null)}
              >
                <X className="h-3 w-3" />
              </Button>
            </div>

            <div className="space-y-3">
              <div>
                <div className="text-[10px] uppercase tracking-wider text-zinc-500 dark:text-zinc-400 mb-1">
                  {t("scenarioEvolution.month")}
                </div>
                <div className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
                  {t("scenarioEvolution.monthValue", { month: selectedEvent.month })}
                </div>
              </div>

              <div>
                <div className="text-[10px] uppercase tracking-wider text-zinc-500 dark:text-zinc-400 mb-1">
                  {t("scenarioEvolution.description")}
                </div>
                <p className="text-xs text-zinc-700 dark:text-zinc-300 leading-relaxed">
                  {selectedEvent.description}
                </p>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-zinc-500 dark:text-zinc-400 mb-1">
                    {t("scenarioEvolution.probability")}
                  </div>
                  <div className="text-sm font-semibold text-zinc-900 dark:text-zinc-100 tabular-nums">
                    {Math.round(selectedEvent.probability * 100)}%
                  </div>
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-zinc-500 dark:text-zinc-400 mb-1">
                    {t("scenarioEvolution.impact")}
                  </div>
                  <div
                    className={cn(
                      "text-sm font-semibold tabular-nums",
                      selectedEvent.impact >= 0
                        ? "text-emerald-600 dark:text-emerald-400"
                        : "text-red-600 dark:text-red-400"
                    )}
                  >
                    {selectedEvent.impact > 0 ? "+" : ""}
                    {Math.round(selectedEvent.impact * 100)}%
                  </div>
                </div>
              </div>

              {selectedEvent.dependencies.length > 0 && (
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-zinc-500 dark:text-zinc-400 mb-1">
                    {t("scenarioEvolution.dependencies")}
                  </div>
                  <ul className="space-y-1">
                    {selectedEvent.dependencies.map((dep, i) => (
                      <li
                        key={i}
                        className="text-xs text-zinc-600 dark:text-zinc-400 flex items-center gap-1.5"
                      >
                        <span className="h-1 w-1 rounded-full bg-zinc-400" />
                        {dep}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}

// ---------- Exported wrapper with provider ----------

export function ScenarioEvolution(props: ScenarioEvolutionProps) {
  return (
    <ReactFlowProvider>
      <EvolutionFlow {...props} />
    </ReactFlowProvider>
  );
}
