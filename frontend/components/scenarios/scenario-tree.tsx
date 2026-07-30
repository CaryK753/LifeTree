"use client";

/**
 * ScenarioTree — React Flow + Canvas visualization of scenario branching.
 *
 * Each node represents a scenario; edges represent parent → child branches.
 * The tree is auto-laid-out with dagre (left → right, conveying time/evolution).
 * Nodes are color-coded by success probability and show status badges.
 * Edges are animated to convey the "flow" of a choice propagating into the future.
 */

import { useCallback, useEffect, useMemo, useState, type FC } from "react";
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
  type EdgeTypes,
  MarkerType,
  useNodesState,
  useEdgesState,
  useReactFlow,
} from "@xyflow/react";
import dagre from "dagre";
import "@xyflow/react/dist/style.css";
import {
  GitBranch,
  Play,
  Loader2,
  CircleDot,
  AlertTriangle,
  CheckCircle2,
  Pause,
  XCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";
import { api } from "@/lib/api";
import { useToast } from "@/components/ui/toast";

// ---------- Types ----------

export interface ScenarioNodeData {
  id: string;
  name: string;
  description?: string;
  status: string;
  parent_scenario_id?: string | null;
  success_probability?: {
    p10?: number;
    p50?: number;
    p90?: number;
    bayesian_point?: number;
  };
  risk_score?: number | null;
  key_risk_factors?: Array<{ name: string; level: string; contribution: number }>;
  assumptions?: Record<string, unknown>;
  computed_at?: string | null;
  // §5 透明化 — populated from latest ScenarioRun.result by the API layer.
  survival_curve?: Array<{ month?: number; t?: number; p?: number; [k: string]: unknown }>;
  key_risk_times?: Array<{ month?: number; risk?: number; label?: string; [k: string]: unknown }>;
  median_time_months?: number | null;
  isRoot?: boolean;
  [key: string]: unknown;
}

interface ScenarioTreeProps {
  scenarios: ScenarioNodeData[];
  onSelect?: (scenario: ScenarioNodeData | null) => void;
  onRerun?: () => void;
  selectedId?: string | null;
  /** When true, the parent renders a right-side detail panel ~384px wide;
   *  clicked nodes are centered in the remaining left area. */
  panelOpen?: boolean;
}

// ---------- Layout (dagre) ----------

const NODE_WIDTH = 240;
const NODE_HEIGHT = 132;

function layoutTree(
  nodes: Node[],
  edges: Edge[],
  direction: "LR" | "TB" = "LR"
): { nodes: Node[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph();
  g.setGraph({
    rankdir: direction,
    nodesep: 56,
    ranksep: 120,
    marginx: 40,
    marginy: 40,
  });
  g.setDefaultEdgeLabel(() => ({}));

  for (const n of nodes) {
    g.setNode(n.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }
  for (const e of edges) {
    g.setEdge(e.source, e.target);
  }

  dagre.layout(g);

  const laidOut = nodes.map((n) => {
    const pos = g.node(n.id);
    // Round to integers to avoid subpixel rendering — dagre outputs
    // floats and browsers blend non-integer pixel positions, making
    // text and borders look blurry.
    return {
      ...n,
      position: {
        x: Math.round(pos.x - NODE_WIDTH / 2),
        y: Math.round(pos.y - NODE_HEIGHT / 2),
      },
    };
  });

  return { nodes: laidOut, edges };
}

// ---------- Helpers ----------

function probColor(p50?: number): string {
  if (p50 == null) return "#6b7280"; // gray-500 — not computed
  if (p50 >= 0.7) return "#22c55e"; // green
  if (p50 >= 0.45) return "#f59e0b"; // amber
  return "#ef4444"; // red
}

function probLabel(p50?: number): string {
  if (p50 == null) return "—";
  return `${Math.round(p50 * 100)}%`;
}

const STATUS_META: Record<
  string,
  { icon: FC<{ className?: string }>; color: string; bg: string }
> = {
  active: { icon: CheckCircle2, color: "text-emerald-400", bg: "bg-emerald-500/10 border-emerald-500/20" },
  draft: { icon: CircleDot, color: "text-sky-400", bg: "bg-sky-500/10 border-sky-500/20" },
  dormant: { icon: Pause, color: "text-amber-400", bg: "bg-amber-500/10 border-amber-500/20" },
  merged: { icon: GitBranch, color: "text-violet-400", bg: "bg-violet-500/10 border-violet-500/20" },
  closed: { icon: XCircle, color: "text-zinc-500", bg: "bg-zinc-500/10 border-zinc-500/20" },
};

// ---------- Custom Node ----------

type ScenarioFlowNode = Node<ScenarioNodeData & { isRunning?: boolean; onRun?: (id: string) => void; onSelect?: (id: string) => void; selected?: boolean; t?: (k: string, v?: any) => string }>;

function ScenarioNode({ data }: NodeProps<ScenarioFlowNode>) {
  const d = data as ScenarioNodeData & {
    isRunning?: boolean;
    onRun?: (id: string) => void;
    onSelect?: (id: string) => void;
    selected?: boolean;
    t?: (k: string, v?: any) => string;
  };
  const p50 = d.success_probability?.p50;
  const color = probColor(p50);
  const statusMeta = STATUS_META[d.status] ?? STATUS_META.draft;
  const StatusIcon = statusMeta.icon;
  const hasRisk = (d.risk_score ?? 0) >= 0.6 || (d.key_risk_factors?.length ?? 0) > 0;

  return (
    <div
      className={cn(
        // Opaque background (not /95 + backdrop-blur) — the blur was
        // causing a fuzzy "frosted glass" effect that made nodes look
        // soft, especially the text inside them.
        "group relative rounded-xl border bg-surface shadow-lg transition-all",
        "w-[240px] cursor-pointer pointer-events-auto",
        d.selected
          ? "border-brand-400/60 ring-2 ring-brand-400/30 shadow-brand-500/10"
          : "border-black/10 dark:border-white/10 hover:border-black/20 dark:hover:border-white/20 hover:shadow-xl"
      )}
    >
      {/* Handles */}
      {!d.isRoot && (
        <Handle
          type="target"
          position={Position.Left}
          className="!w-2 !h-2 !bg-white/40 !border-white/20"
        />
      )}
      <Handle
        type="source"
        position={Position.Right}
        className="!w-2 !h-2 !bg-white/40 !border-white/20"
      />

      <div className="p-3 space-y-2">
        {/* Header: status + name */}
        <div className="flex items-start gap-2">
          <span
            className={cn(
              "shrink-0 inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] border",
              statusMeta.bg,
              statusMeta.color
            )}
          >
            <StatusIcon className="h-2.5 w-2.5" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium text-zinc-100 truncate">
              {d.name}
            </div>
            {d.description && (
              <div className="text-[10px] text-zinc-500 truncate mt-0.5">
                {d.description}
              </div>
            )}
          </div>
        </div>

        {/* Probability ring + risk indicator */}
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <div
              className="relative h-9 w-9 rounded-full flex items-center justify-center shrink-0"
              style={{
                background: `conic-gradient(${color} ${Math.round(
                  (p50 ?? 0) * 360
                )}deg, rgba(255,255,255,0.06) 0deg)`,
              }}
            >
              <div className="absolute inset-1 rounded-full bg-surface flex items-center justify-center">
                <span
                  className="text-[10px] font-semibold"
                  style={{ color }}
                >
                  {probLabel(p50)}
                </span>
              </div>
            </div>
            <div className="text-[10px] text-zinc-500 leading-tight">
              <div>{d.t?.("scenarioTree.success")}</div>
              {d.success_probability?.p10 != null && (
                <div className="text-zinc-600">
                  {d.t?.("scenarioTree.range", {
                    p10: Math.round((d.success_probability.p10 ?? 0) * 100),
                    p90: Math.round((d.success_probability.p90 ?? 0) * 100),
                  })}
                </div>
              )}
            </div>
          </div>

          {hasRisk && (
            <span
              className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] bg-amber-500/10 text-amber-400 border border-amber-500/20"
              title={d.t?.("scenarioTree.highRisk")}
            >
              <AlertTriangle className="h-2.5 w-2.5" />
            </span>
          )}
        </div>

        {/* Footer: run button */}
        <div className="flex items-center justify-between pt-1 border-t border-white/5">
          <span className="text-[9px] text-zinc-600">
            {d.computed_at
              ? d.t?.("scenarioTree.computed")
              : d.t?.("scenarioTree.notComputed")}
          </span>
          <button
            type="button"
            disabled={d.isRunning}
            onClick={(e) => {
              e.stopPropagation();
              d.onRun?.(d.id);
            }}
            className={cn(
              "inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] transition-colors",
              "text-zinc-400 hover:text-brand-300 hover:bg-brand-500/10",
              d.isRunning && "opacity-60 cursor-wait"
            )}
          >
            {d.isRunning ? (
              <Loader2 className="h-2.5 w-2.5 animate-spin" />
            ) : (
              <Play className="h-2.5 w-2.5" />
            )}
            {d.isRunning
              ? d.t?.("scenarioTree.running")
              : d.t?.("scenarioTree.run")}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------- Custom Animated Edge ----------

function BranchEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  source,
  target,
  data,
}: any) {
  // Bezier path from source to target.
  const dx = targetX - sourceX;
  const midX = sourceX + dx * 0.5;
  const path = `M ${sourceX},${sourceY} C ${midX},${sourceY} ${midX},${targetY} ${targetX},${targetY}`;

  const isHighlight = data?.highlight;

  return (
    <>
      <defs>
        <linearGradient id={`grad-${id}`} x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stopColor={isHighlight ? "#5eab7f" : "#3b8d61"} stopOpacity="0.7" />
          <stop offset="100%" stopColor={isHighlight ? "#8fcaa6" : "#5eab7f"} stopOpacity="0.9" />
        </linearGradient>
      </defs>
      {/* Base path */}
      <path
        id={id}
        d={path}
        fill="none"
        stroke={`url(#grad-${id})`}
        strokeWidth={isHighlight ? 2.5 : 1.5}
        strokeOpacity={isHighlight ? 1 : 0.6}
        markerEnd="url(#branch-arrow)"
      />
      {/* Animated dashed overlay — conveys "flow" of choices propagating */}
      <path
        d={path}
        fill="none"
        stroke={isHighlight ? "#bbf7d0" : "#5eab7f"}
        strokeWidth={1.5}
        strokeDasharray="4 8"
        strokeOpacity={0.7}
        className="react-flow__edge-path-animate"
        style={{
          animation: "flow-dash 1.6s linear infinite",
        }}
      />
    </>
  );
}

// ---------- Main Component ----------

const nodeTypes: NodeTypes = { scenario: ScenarioNode };
const edgeTypes: EdgeTypes = { branch: BranchEdge };

function ScenarioTreeInner({
  scenarios,
  onSelect,
  onRerun,
  selectedId,
  panelOpen,
}: ScenarioTreeProps) {
  const t = useT();
  const toast = useToast();
  const { fitView, setCenter } = useReactFlow();
  const [running, setRunning] = useState<string | null>(null);

  const handleSelect = useCallback(
    (id: string) => {
      const s = scenarios.find((x) => x.id === id) ?? null;
      onSelect?.(s);
    },
    [scenarios, onSelect]
  );

  const handleRun = useCallback(
    async (id: string) => {
      setRunning(id);
      try {
        await api.runScenario(id);
        toast({ title: t("scenarioTree.runComplete"), variant: "success" });
        onRerun?.();
      } catch (e: any) {
        toast({
          title: t("scenarioTree.runFailed"),
          description: e?.message,
          variant: "error",
        });
      } finally {
        setRunning(null);
      }
    },
    [toast, t, onRerun]
  );

  // Build nodes & edges from scenarios.
  const { initialNodes, initialEdges } = useMemo(() => {
    const nodes: Node[] = scenarios.map((s) => ({
      id: s.id,
      type: "scenario",
      position: { x: 0, y: 0 },
      data: {
        ...s,
        isRoot: !s.parent_scenario_id,
        t,
        isRunning: running === s.id,
        selected: selectedId === s.id,
        onRun: handleRun,
        onSelect: handleSelect,
      },
    }));
    const edges: Edge[] = scenarios
      .filter((s) => s.parent_scenario_id)
      .map((s) => ({
        id: `e-${s.parent_scenario_id}-${s.id}`,
        source: s.parent_scenario_id!,
        target: s.id,
        type: "branch",
        markerEnd: { type: MarkerType.ArrowClosed, color: "#5eab7f" },
        data: {
          highlight: selectedId === s.id || selectedId === s.parent_scenario_id,
        },
      }));
    return { initialNodes: nodes, initialEdges: edges };
  }, [scenarios, selectedId, running, t, handleRun, handleSelect]);

  // Apply dagre layout directly — no separate node state needed for a
  // read-only auto-laid-out tree. React Flow handles pan/zoom internally.
  const { nodes: laidOutNodes, edges: laidOutEdges } = useMemo(
    () => layoutTree(initialNodes, initialEdges),
    [initialNodes, initialEdges]
  );

  // IMPORTANT: useNodesState / useEdgesState + onNodesChange / onEdgesChange
  // are required for the MiniMap to render node thumbnails. Without
  // onNodesChange, React Flow cannot write back the `measured` dimensions
  // (DOM-measured width/height) onto the node state, so the MiniMap has no
  // size data to draw thumbnails from. Decision-tree Canvas already does
  // this; the scenario-tree Canvas was previously passing the memoized
  // array directly, which is why its MiniMap appeared empty.
  const [nodes, setNodes, onNodesChange] = useNodesState(laidOutNodes);
  const edgesState = useEdgesState(laidOutEdges);
  const edges = edgesState[0];
  const setEdges = edgesState[1];
  const onEdgesChange = edgesState[2];

  // Sync the laid-out nodes/edges into state whenever the layout changes.
  // Using useEffect (not useMemo) because we're mutating state.
  useEffect(() => {
    setNodes(laidOutNodes);
  }, [laidOutNodes, setNodes]);
  useEffect(() => {
    setEdges(laidOutEdges);
  }, [laidOutEdges, setEdges]);

  // Build a quick id → node-position lookup so we can center the clicked
  // node without scanning the array on every click.
  const nodePosById = useMemo(() => {
    const m = new Map<string, { x: number; y: number }>();
    for (const n of nodes) m.set(n.id, n.position);
    return m;
  }, [nodes]);

  // Fit view when the set of scenarios changes (NOT on every selection —
  // selection is handled by the centering effect below). We intentionally
  // exclude selectedId / running from the deps so re-fitting doesn't
  // fight the centering logic.
  const scenarioKey = scenarios.map((s) => s.id).join("|");
  useEffect(() => {
    const id = requestAnimationFrame(() => {
      fitView({ padding: 0.2, duration: 400 });
    });
    return () => cancelAnimationFrame(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenarioKey, fitView]);

  // When the selected node changes, zoom in and pan so the node sits at
  // the center of the left area (i.e. shifted left to leave room for the
  // ~384px right detail panel when it's open).
  useEffect(() => {
    if (!selectedId) return;
    const pos = nodePosById.get(selectedId);
    if (!pos) return;
    // Node center in flow coordinates (positions are top-left of the node).
    const cx = pos.x + NODE_WIDTH / 2;
    const cy = pos.y + NODE_HEIGHT / 2;
    // Target zoom — 1.0 shows the node at its natural size which is big
    // enough to read clearly without being so large the surrounding
    // context disappears.
    const targetZoom = 1.0;
    // When the right panel is open, shift the center left so the node
    // sits in the middle of the visible (non-panel) area. React Flow's
    // setCenter takes the point in flow coords that should map to the
    // viewport center, so we offset cx to the right by half the panel
    // width in flow units (panelWidth / 2 / zoom).
    const panelWidth = panelOpen ? 384 : 0;
    const offsetX = panelWidth / 2 / targetZoom;
    setCenter(cx + offsetX, cy, { zoom: targetZoom, duration: 450 });
  }, [selectedId, nodePosById, panelOpen, setCenter]);

  if (scenarios.length === 0) {
    return null;
  }

  return (
    <div className="w-full h-full min-h-[600px] relative">
      <style>{`
        @keyframes flow-dash {
          to { stroke-dashoffset: -12; }
        }
        .react-flow__edge-path-animate {
          pointer-events: none;
        }
        .react-flow__attribution {
          background: transparent !important;
          color: rgba(0,0,0,0.2) !important;
        }
        .dark .react-flow__attribution {
          color: rgba(255,255,255,0.2) !important;
        }
        .react-flow__controls {
          background: rgba(255, 255, 255, 0.9) !important;
          border: 1px solid rgba(0,0,0,0.1) !important;
          border-radius: 8px !important;
          overflow: hidden;
        }
        .dark .react-flow__controls {
          background: rgba(23, 29, 24, 0.9) !important;
          border: 1px solid rgba(255,255,255,0.08) !important;
        }
        .react-flow__controls-button {
          background: transparent !important;
          border-bottom: 1px solid rgba(0,0,0,0.05) !important;
          color: #3f3f46 !important;
        }
        .dark .react-flow__controls-button {
          border-bottom: 1px solid rgba(255,255,255,0.05) !important;
          color: #d4d4d8 !important;
        }
        .react-flow__controls-button:hover {
          background: rgba(94, 171, 127, 0.15) !important;
        }
        .react-flow__minimap {
          background: rgba(255, 255, 255, 0.9) !important;
          border: 1px solid rgba(0,0,0,0.1) !important;
          border-radius: 8px !important;
        }
        .dark .react-flow__minimap {
          background: rgba(23, 29, 24, 0.9) !important;
          border: 1px solid rgba(255,255,255,0.08) !important;
        }
        .react-flow__node {
          cursor: pointer;
        }
      `}</style>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={(_, node) => handleSelect(node.id)}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable
        fitView
        fitViewOptions={{ padding: 0.12 }}
        minZoom={0.2}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
        defaultEdgeOptions={{
          type: "branch",
          markerEnd: { type: MarkerType.ArrowClosed, color: "#5eab7f" },
        }}
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={20}
          size={1.5}
          color="rgba(0,0,0,0.08)"
        />
        <Background
          variant={BackgroundVariant.Lines}
          gap={64}
          color="rgba(94, 171, 127, 0.06)"
        />
        <Controls
          showInteractive={false}
          className="!shadow-lg"
        />
        <MiniMap
          nodeColor={(n) => {
            const p50 = (n.data as ScenarioNodeData)?.success_probability?.p50;
            return probColor(p50);
          }}
          nodeStrokeWidth={3}
          nodeStrokeColor="rgba(0,0,0,0.3)"
          pannable
          zoomable
          className="!shadow-lg !w-64 !h-40"
          maskColor="rgba(0,0,0,0.06)"
        />
      </ReactFlow>
    </div>
  );
}

export function ScenarioTree(props: ScenarioTreeProps) {
  return (
    <ReactFlowProvider>
      <ScenarioTreeInner {...props} />
    </ReactFlowProvider>
  );
}
