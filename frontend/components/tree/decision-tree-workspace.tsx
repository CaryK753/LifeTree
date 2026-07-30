"use client";

/**
 * DecisionTreeWorkspace — reusable decision-tree visualization.
 *
 * Extracted from the standalone /tree/[goalId] page so the same
 * React Flow canvas + side panel + context menu can be embedded
 * inside a goal workspace tab (GoalTreeTab) or any other surface.
 *
 * The tree auto-grows: AI-predicted branches (虚线) appear after
 * running "探索新分支", and the user confirms / selects / abandons
 * them via the side panel or right-click context menu. Layout is
 * computed by dagre (left-to-right by default, top-to-bottom when
 * toggled).
 *
 * The workspace does NOT render a page header — that's the consumer's
 * responsibility (back button, goal title, sidebar toggle, etc.).
 * It renders: a compact toolbar (explore-all + layout toggle), the
 * legend strip, the canvas area (skeleton/error/empty states +
 * TreeCanvas + SidePanel + exploringAll overlay), the context menu
 * portal, and the add-child dialog.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  Handle,
  Position,
  MarkerType,
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
  useReactFlow,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type NodeProps,
  type NodeTypes,
  type EdgeTypes,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import dagre from "dagre";
import useSWR from "swr";
import {
  ArrowLeft,
  Sparkles,
  CheckCircle2,
  Play,
  Ban,
  GitBranch,
  HelpCircle,
  Flag,
  Loader2,
  Plus,
  X,
  AlertTriangle,
  ShieldAlert,
  CircleDot,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from "@/components/ui/dialog";
import {
  abandonBranch,
  canonicalizeStatus,
  collectLeaves,
  confirmBranch,
  evolveBranch,
  flattenTree,
  getDecisionTree,
  growBranch,
  selectBranch,
  type CanonicalStatus,
  type DecisionTreeNode,
} from "@/lib/api-decision-tree";

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

// ---------- Status styling ----------
//
// Each canonical status maps to:
//   - border + ring classes for the node card
//   - badge text/ classes for the inline status pill
//   - the icon shown on the badge
//   - the React Flow edge stroke style (solid / dashed / faded)

interface StatusStyle {
  badgeClass: string;
  borderClass: string;
  ringClass: string;
  edgeStrokeDash: string | undefined;
  edgeOpacity: number;
}

const STATUS_STYLES: Record<CanonicalStatus, StatusStyle> = {
  predicted: {
    badgeClass:
      "bg-amber-500/15 text-amber-700 dark:text-amber-300 border-amber-500/30",
    borderClass: "border-dashed border-amber-500/50",
    ringClass: "",
    edgeStrokeDash: "6 4",
    edgeOpacity: 0.7,
  },
  confirmed: {
    badgeClass:
      "bg-sky-500/15 text-sky-700 dark:text-sky-300 border-sky-500/30",
    borderClass: "border-sky-500/40",
    ringClass: "",
    edgeStrokeDash: undefined,
    edgeOpacity: 0.9,
  },
  in_progress: {
    badgeClass:
      "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/40",
    borderClass: "border-emerald-500/60",
    ringClass: "ring-2 ring-emerald-500/40 shadow-emerald-500/10",
    edgeStrokeDash: undefined,
    edgeOpacity: 1,
  },
  abandoned: {
    badgeClass:
      "bg-zinc-500/10 text-zinc-500 dark:text-zinc-500 border-zinc-500/20",
    borderClass: "border-zinc-500/30",
    ringClass: "",
    edgeStrokeDash: "2 4",
    edgeOpacity: 0.35,
  },
};

function probColor(p50?: number): string {
  if (p50 == null) return "#6b7280";
  if (p50 >= 0.7) return "#22c55e";
  if (p50 >= 0.45) return "#f59e0b";
  return "#ef4444";
}

function probLabel(p50?: number): string {
  if (p50 == null) return "—";
  return `${Math.round(p50 * 100)}%`;
}

/** Marker color for an edge based on its canonical status. */
function statusMarkerColor(status: CanonicalStatus): string | undefined {
  switch (status) {
    case "in_progress":
      return "#10b981";
    case "predicted":
      return "#f59e0b";
    case "abandoned":
      return undefined;
    default:
      return "#3b8d61";
  }
}

/** Build a React Flow markerEnd object for a given status. */
function statusMarkerEnd(status: CanonicalStatus) {
  const color = statusMarkerColor(status);
  if (!color) return undefined;
  return {
    type: MarkerType.ArrowClosed,
    color,
    markerUnits: "userSpaceOnUse" as const,
    width: 12,
    height: 12,
  };
}

// ---------- Custom node data shape ----------

interface NodeData {
  node: DecisionTreeNode;
  status: CanonicalStatus;
  selected?: boolean;
  evolving?: boolean;
  onSelect?: (id: string) => void;
  onContextMenu?: (id: string, x: number, y: number) => void;
  t: (k: string, v?: Record<string, string | number>) => string;
  [key: string]: unknown;
}

type FlowNode = Node<NodeData>;

// ---------- Status badge ----------

function StatusBadge({
  status,
  t,
}: {
  status: CanonicalStatus;
  t: (k: string) => string;
}) {
  const style = STATUS_STYLES[status];
  const labelKey =
    status === "predicted"
      ? "tree.predicted"
      : status === "confirmed"
      ? "tree.confirmed"
      : status === "in_progress"
      ? "tree.inProgress"
      : "tree.abandoned";
  const Icon =
    status === "predicted"
      ? Sparkles
      : status === "confirmed"
      ? CheckCircle2
      : status === "in_progress"
      ? Play
      : Ban;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] border",
        style.badgeClass
      )}
    >
      <Icon className="h-2.5 w-2.5" />
      {t(labelKey)}
    </span>
  );
}

// ---------- Root node ----------

function RootNode({ data }: NodeProps<FlowNode>) {
  const d = data as NodeData;
  const style = STATUS_STYLES[d.status];
  const p50 = d.node.probability?.p50;
  const color = probColor(p50);

  return (
    <div
      className={cn(
        "group relative rounded-xl border bg-surface shadow-lg transition-all w-[260px] cursor-pointer",
        "border-brand-500/50 ring-1 ring-brand-500/20",
        d.selected && "ring-2 ring-brand-400/60"
      )}
      onClick={(e) => {
        e.stopPropagation();
        d.onSelect?.(d.node.id);
      }}
      onContextMenu={(e) => {
        e.preventDefault();
        e.stopPropagation();
        d.onContextMenu?.(d.node.id, e.clientX, e.clientY);
      }}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!h-2 !w-2 !border-brand-300 !bg-brand-500"
      />
      <Handle
        type="source"
        position={Position.Right}
        className="!w-2 !h-2 !bg-brand-500 !border-brand-300"
      />
      <div className="p-3 space-y-2">
        <div className="flex items-start gap-2">
          <span className="shrink-0 inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] border bg-brand-500/15 text-brand-700 dark:text-brand-300 border-brand-500/30">
            <Flag className="h-2.5 w-2.5" />
            {d.t("tree.root")}
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold text-zinc-900 dark:text-zinc-100 truncate">
              {d.node.name}
            </div>
            {d.node.description && (
              <div className="text-[10px] text-zinc-500 dark:text-zinc-400 truncate mt-0.5">
                {d.node.description}
              </div>
            )}
          </div>
        </div>
        <div className="flex items-center justify-between gap-2 pt-1 border-t border-black/5 dark:border-white/5">
          <div className="flex items-center gap-1.5">
            <div
              className="relative h-7 w-7 rounded-full flex items-center justify-center shrink-0"
              style={{
                background: `conic-gradient(${color} ${Math.round(
                  (p50 ?? 0) * 360
                )}deg, rgba(127,127,127,0.12) 0deg)`,
              }}
            >
              <div className="absolute inset-1 rounded-full bg-surface flex items-center justify-center">
                <span className="text-[9px] font-semibold" style={{ color }}>
                  {probLabel(p50)}
                </span>
              </div>
            </div>
            <span className="text-[10px] text-zinc-500 dark:text-zinc-400">
              {d.t("tree.probability")}
            </span>
          </div>
          <NodeCounters node={d.node} t={d.t} />
        </div>
      </div>
    </div>
  );
}

// ---------- Decision node (diamond-like) ----------

function DecisionNode({ data }: NodeProps<FlowNode>) {
  const d = data as NodeData;
  const style = STATUS_STYLES[d.status];

  return (
    <div
      className={cn(
        "group relative bg-surface shadow-lg transition-all w-[220px] cursor-pointer",
        "rotate-0 border-2 border-amber-500/60 rounded-2xl",
        style.borderClass,
        d.selected && "ring-2 ring-amber-400/60",
        d.status === "predicted" && "animate-pulse-soft"
      )}
      onClick={(e) => {
        e.stopPropagation();
        d.onSelect?.(d.node.id);
      }}
      onContextMenu={(e) => {
        e.preventDefault();
        e.stopPropagation();
        d.onContextMenu?.(d.node.id, e.clientX, e.clientY);
      }}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!w-2 !h-2 !bg-amber-500 !border-amber-300"
      />
      <Handle
        type="source"
        position={Position.Right}
        className="!w-2 !h-2 !bg-amber-500 !border-amber-300"
      />
      <div className="p-3 space-y-1.5">
        <div className="flex items-start gap-1.5">
          <HelpCircle className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />
          <div className="min-w-0 flex-1">
            <div className="text-[10px] uppercase tracking-wider text-amber-700 dark:text-amber-300 font-semibold">
              {d.t("tree.decision")}
            </div>
            <div className="text-xs text-zinc-800 dark:text-zinc-200 line-clamp-3 mt-0.5">
              {d.node.decision_question ?? d.node.name}
            </div>
          </div>
        </div>
        <div className="flex items-center justify-between pt-1 border-t border-black/5 dark:border-white/5">
          <StatusBadge status={d.status} t={d.t} />
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              d.onSelect?.(d.node.id);
            }}
            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] text-amber-700 dark:text-amber-300 hover:bg-amber-500/10"
            title={d.t("tree.evolve")}
          >
            <Sparkles className="h-2.5 w-2.5" />
            {d.t("tree.evolve")}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------- Branch node ----------

function BranchNode({ data }: NodeProps<FlowNode>) {
  const d = data as NodeData;
  const style = STATUS_STYLES[d.status];
  const p50 = d.node.probability?.p50;
  const color = probColor(p50);
  const isAbandoned = d.status === "abandoned";

  return (
    <div
      className={cn(
        "group relative rounded-xl border bg-surface shadow-lg transition-all w-[240px] cursor-pointer",
        style.borderClass,
        style.ringClass,
        d.selected && "ring-2 ring-brand-400/60",
        d.status === "predicted" && "animate-pulse-soft",
        isAbandoned && "opacity-30 grayscale"
      )}
      onClick={(e) => {
        e.stopPropagation();
        d.onSelect?.(d.node.id);
      }}
      onContextMenu={(e) => {
        e.preventDefault();
        e.stopPropagation();
        d.onContextMenu?.(d.node.id, e.clientX, e.clientY);
      }}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!w-2 !h-2 !bg-white/40 !border-white/20"
      />
      <Handle
        type="source"
        position={Position.Right}
        className="!w-2 !h-2 !bg-white/40 !border-white/20"
      />
      {d.evolving && (
        <div className="absolute -top-2 -right-2 z-10 h-6 w-6 rounded-full bg-brand-500 text-white flex items-center justify-center shadow-lg">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        </div>
      )}
      <div className="p-3 space-y-2">
        <div className="flex items-start gap-2">
          <StatusBadge status={d.status} t={d.t} />
          {d.node.region && (
            <span className="shrink-0 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] border bg-violet-500/10 text-violet-700 dark:text-violet-300 border-violet-500/20">
              {d.node.region}
            </span>
          )}
        </div>
        <div className="min-w-0">
          <div
            className={cn(
              "text-sm font-medium text-zinc-900 dark:text-zinc-100 truncate",
              isAbandoned && "line-through"
            )}
          >
            {d.node.name}
          </div>
          {d.node.description && (
            <div
              className={cn(
                "text-[10px] text-zinc-500 dark:text-zinc-400 truncate mt-0.5",
                isAbandoned && "line-through"
              )}
            >
              {d.node.description}
            </div>
          )}
        </div>
        <div className="flex items-center justify-between gap-2 pt-1 border-t border-black/5 dark:border-white/5">
          <div className="flex items-center gap-1.5">
            <div
              className="relative h-7 w-7 rounded-full flex items-center justify-center shrink-0"
              style={{
                background: `conic-gradient(${color} ${Math.round(
                  (p50 ?? 0) * 360
                )}deg, rgba(127,127,127,0.12) 0deg)`,
              }}
            >
              <div className="absolute inset-1 rounded-full bg-surface flex items-center justify-center">
                <span className="text-[9px] font-semibold" style={{ color }}>
                  {probLabel(p50)}
                </span>
              </div>
            </div>
            {d.status === "predicted" && d.node.evolution_hint && (
              <span
                className="text-[10px] text-amber-600 dark:text-amber-400 italic line-clamp-1 max-w-[120px]"
                title={d.node.evolution_hint}
              >
                {d.node.evolution_hint}
              </span>
            )}
          </div>
          <NodeCounters node={d.node} t={d.t} />
        </div>
      </div>
    </div>
  );
}

// ---------- Milestone node ----------

function MilestoneNode({ data }: NodeProps<FlowNode>) {
  const d = data as NodeData;

  return (
    <div
      className={cn(
        "group relative rounded-full border bg-surface shadow-md transition-all w-[160px] cursor-pointer",
        "border-emerald-500/40",
        d.selected && "ring-2 ring-emerald-400/60"
      )}
      onClick={(e) => {
        e.stopPropagation();
        d.onSelect?.(d.node.id);
      }}
      onContextMenu={(e) => {
        e.preventDefault();
        e.stopPropagation();
        d.onContextMenu?.(d.node.id, e.clientX, e.clientY);
      }}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!w-2 !h-2 !bg-emerald-500 !border-emerald-300"
      />
      <Handle
        type="source"
        position={Position.Right}
        className="!w-2 !h-2 !bg-emerald-500 !border-emerald-300"
      />
      <div className="px-3 py-2 flex items-center gap-2">
        <Flag className="h-3.5 w-3.5 text-emerald-500 shrink-0" />
        <div className="min-w-0">
          <div className="text-[10px] uppercase tracking-wider text-emerald-700 dark:text-emerald-300 font-semibold">
            {d.t("tree.milestone")}
          </div>
          <div className="text-xs text-zinc-900 dark:text-zinc-100 truncate">
            {d.node.name}
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------- Inline counters (requirements + risks) ----------

function NodeCounters({
  node,
  t,
}: {
  node: DecisionTreeNode;
  t: (k: string) => string;
}) {
  const reqCount = node.requirements?.length ?? 0;
  const riskCount = node.risk_factors?.length ?? 0;
  return (
    <div className="flex items-center gap-1 shrink-0">
      {reqCount > 0 && (
        <span
          className="inline-flex items-center gap-0.5 px-1 py-0.5 rounded text-[10px] bg-sky-500/10 text-sky-700 dark:text-sky-300 border border-sky-500/20"
          title={t("tree.requirements")}
        >
          <CircleDot className="h-2.5 w-2.5" />
          {reqCount}
        </span>
      )}
      {riskCount > 0 && (
        <span
          className="inline-flex items-center gap-0.5 px-1 py-0.5 rounded text-[10px] bg-amber-500/10 text-amber-700 dark:text-amber-300 border border-amber-500/20"
          title={t("tree.riskFactors")}
        >
          <AlertTriangle className="h-2.5 w-2.5" />
          {riskCount}
        </span>
      )}
    </div>
  );
}

// ---------- Custom edge (status-aware stroke) ----------

function StatusEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  data,
}: {
  id: string;
  sourceX: number;
  sourceY: number;
  targetX: number;
  targetY: number;
  data?: { status?: CanonicalStatus; label?: string };
}) {
  const status = data?.status ?? "confirmed";
  const style = STATUS_STYLES[status];
  const stroke =
    status === "in_progress"
      ? "#10b981"
      : status === "predicted"
      ? "#f59e0b"
      : status === "abandoned"
      ? "#71717a"
      : "#3b8d61";

  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
  });

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        style={{
          stroke,
          strokeWidth: status === "in_progress" ? 2.2 : 1.5,
          strokeOpacity: style.edgeOpacity,
          strokeDasharray: style.edgeStrokeDash,
        }}
      />
      {data?.label && (
        <EdgeLabelRenderer>
          <div
            style={{
              position: "absolute",
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
              fontSize: 9,
              fontStyle: "italic",
              pointerEvents: "none",
            }}
            className="fill-zinc-500 dark:fill-zinc-400 text-zinc-500 dark:text-zinc-400"
          >
            {data.label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

// ---------- Node type registry ----------

const nodeTypes: NodeTypes = {
  root: RootNode,
  decision: DecisionNode,
  branch: BranchNode,
  milestone: MilestoneNode,
};

const edgeTypes: EdgeTypes = { status: StatusEdge };

// ---------- Shared requirement-edge builder ----------

function buildRequirementEdges(
  flat: { id: string; node: DecisionTreeNode }[]
): Edge[] {
  const edges: Edge[] = [];
  const seenReq = new Set<string>();
  // Group node ids by requirement id.
  const reqToNodes = new Map<string, string[]>();
  for (const { id, node } of flat) {
    for (const r of node.requirements ?? []) {
      const list = reqToNodes.get(r.id) ?? [];
      list.push(id);
      reqToNodes.set(r.id, list);
    }
  }
  for (const [reqId, nodeIds] of reqToNodes.entries()) {
    if (nodeIds.length < 2 || seenReq.has(reqId)) continue;
    seenReq.add(reqId);
    // Only draw the first pair to keep the canvas clean.
    const [a, b] = nodeIds;
    const reqName =
      flat.find((f) => f.node.requirements?.some((r) => r.id === reqId))?.node.requirements?.find(
        (r) => r.id === reqId
      )?.name ?? "";
    edges.push({
      id: `req-${reqId}-${a}-${b}`,
      source: a,
      target: b,
      type: "status",
      data: { status: "confirmed", label: reqName },
      markerEnd: statusMarkerEnd("confirmed"),
      style: { strokeDasharray: "1 4", stroke: "#94a3b8", opacity: 0.4 },
    });
  }
  return edges;
}

// ---------- Inner tree (the React Flow canvas) ----------

interface TreeCanvasProps {
  root: DecisionTreeNode;
  selectedId: string | null;
  evolvingIds: Set<string>;
  direction: "LR" | "TB";
  onSelect: (id: string) => void;
  onContextMenu: (id: string, x: number, y: number) => void;
}

function TreeCanvas({
  root,
  selectedId,
  evolvingIds,
  direction,
  onSelect,
  onContextMenu,
}: TreeCanvasProps) {
  const t = useT();
  const { fitView, setCenter } = useReactFlow();

  // Build the node/edge definitions (without dagre positions) from the
  // tree data. Recomputed when selection / evolving / tree changes so
  // the per-node `data` reflects the latest state.
  const { initialNodes, initialEdges } = useMemo(() => {
    const flat = flattenTree(root);
    const nodes: Node[] = flat.map(({ id, parentId, node }) => {
      const status = canonicalizeStatus(node.status);
      const typeKey =
        node.node_type === "root"
          ? "root"
          : node.node_type === "decision"
          ? "decision"
          : node.node_type === "milestone"
          ? "milestone"
          : "branch";
      return {
        id,
        type: typeKey,
        position: { x: 0, y: 0 },
        data: {
          node,
          status,
          selected: selectedId === id,
          evolving: evolvingIds.has(id),
          onSelect,
          onContextMenu,
          t,
        } as NodeData,
      } satisfies Node;
    });

    const edges: Edge[] = flat
      .filter((f) => f.parentId)
      .map((f) => {
        const childStatus = canonicalizeStatus(f.node.status);
        return {
          id: `e-${f.parentId}-${f.id}`,
          source: f.parentId!,
          target: f.id,
          type: "status",
          data: { status: childStatus },
          markerEnd: statusMarkerEnd(childStatus),
        } satisfies Edge;
      });

    // Add dotted requirement-sharing edges (visual clarity only — kept
    // to one pair per requirement).
    edges.push(...buildRequirementEdges(flat));

    return { initialNodes: nodes, initialEdges: edges };
  }, [root, selectedId, evolvingIds, onSelect, onContextMenu, t]);

  // Compute dagre-laid-out positions whenever the structure (node/edge
  // set) or direction changes. We only use the positions from this —
  // the `data` always comes from `initialNodes` so selection/evolving
  // updates flow through without resetting user-dragged positions.
  const layoutPositions = useMemo(() => {
    const { nodes: laidOut } = layoutTree(initialNodes, initialEdges, direction);
    const m = new Map<string, { x: number; y: number }>();
    for (const n of laidOut) m.set(n.id, n.position);
    return m;
    // Intentionally exclude selectedId / evolvingIds so dragging a node
    // or toggling selection doesn't snap nodes back to dagre positions.
    // We only re-layout when the node set or direction changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [root, direction]);

  // Track the previous set of node ids so we can detect structural
  // changes (add/remove) vs. mere data updates. Initialized empty so
  // the first render is treated as a structural change and dagre
  // positions are applied.
  const prevNodeIdsRef = useRef<Set<string>>(new Set());
  const prevDirectionRef = useRef<string>(direction);

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const edgesState = useEdgesState(initialEdges);
  const edges = edgesState[0];
  const setEdges = edgesState[1];
  const onEdgesChange = edgesState[2];

  // Apply dagre positions + latest data whenever initialNodes/Edges or
  // layout direction change. This preserves user-dragged positions for
  // nodes that still exist (we only re-position on structural change or
  // direction toggle), while keeping `data` (selection, evolving, t)
  // in sync on every render.
  useEffect(() => {
    const currentNodeIds = new Set(initialNodes.map((n) => n.id));
    // Detect structural change: node set differs from previous, OR the
    // layout direction just toggled (which requires re-running dagre).
    let structuralChange = false;
    if (
      currentNodeIds.size !== prevNodeIdsRef.current.size ||
      prevDirectionRef.current !== direction
    ) {
      structuralChange = true;
    } else {
      for (const id of currentNodeIds) {
        if (!prevNodeIdsRef.current.has(id)) {
          structuralChange = true;
          break;
        }
      }
    }
    // Update current nodes: keep existing positions (user drags) unless
    // the structure changed, in which case re-apply dagre positions.
    setNodes((prev) => {
      const prevById = new Map(prev.map((n) => [n.id, n]));
      return initialNodes.map((n) => {
        const pos =
          structuralChange || !prevById.has(n.id)
            ? (layoutPositions.get(n.id) ?? n.position)
            : (prevById.get(n.id)!.position);
        return { ...n, position: pos };
      });
    });
    setEdges(initialEdges);
    prevNodeIdsRef.current = currentNodeIds;
    prevDirectionRef.current = direction;
  }, [initialNodes, initialEdges, layoutPositions, direction, setNodes, setEdges]);

  // Fit view only after a structural change or direction toggle, not on
  // every selection/evolving update (which would fight user panning).
  useEffect(() => {
    const id = requestAnimationFrame(() => {
      fitView({ padding: 0.2, duration: 400 });
    });
    return () => cancelAnimationFrame(id);
  }, [direction, root, fitView]);

  // Track live node positions in a ref so the centering effect can read
  // the current (post-drag) position without re-firing on every `nodes`
  // state update (which would cause unwanted re-centering).
  const nodePositionsRef = useRef<Map<string, { x: number; y: number }>>(
    new Map()
  );
  useEffect(() => {
    const m = new Map<string, { x: number; y: number }>();
    for (const n of nodes) m.set(n.id, n.position);
    nodePositionsRef.current = m;
  }, [nodes]);

  // When a node is selected, zoom in and pan so the node sits at the
  // center of the left area (leaving room for the ~384px right detail
  // panel). Reads from the ref so it only fires when selection changes.
  useEffect(() => {
    if (!selectedId) return;
    const pos = nodePositionsRef.current.get(selectedId);
    if (!pos) return;
    // Node center in flow coordinates (positions are top-left).
    const cx = pos.x + NODE_WIDTH / 2;
    const cy = pos.y + NODE_HEIGHT / 2;
    // Target zoom — 1.1 shows the node slightly enlarged so it's easy
    // to read while keeping neighbors visible for context.
    const targetZoom = 1.1;
    // The SidePanel is ~384px wide on xl screens. Shift the centering
    // point right by half the panel width (in flow units) so the node
    // lands in the middle of the visible (non-panel) area.
    const panelWidth = 384;
    const offsetX = panelWidth / 2 / targetZoom;
    setCenter(cx + offsetX, cy, { zoom: targetZoom, duration: 450 });
  }, [selectedId, setCenter]);

  return (
    <>
      <style>{`
        @keyframes flow-dash {
          to { stroke-dashoffset: -12; }
        }
        .react-flow__edge-path { pointer-events: all; }
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
          background: rgba(59, 141, 97, 0.15) !important;
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
        .react-flow__node { cursor: grab; }
        .react-flow__node:active { cursor: grabbing; }
        .react-flow__node.dragging { cursor: grabbing; }
      `}</style>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodesDraggable
        nodesConnectable={false}
        elementsSelectable
        fitView
        fitViewOptions={{ padding: 0.12 }}
        minZoom={0.2}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
        onNodeClick={(_, node) => onSelect(node.id)}
        defaultEdgeOptions={{
          type: "status",
          markerEnd: { type: MarkerType.ArrowClosed, color: "#3b8d61" },
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
          color="rgba(59, 141, 97, 0.06)"
        />
        <Controls showInteractive={false} className="!shadow-lg" />
        <MiniMap
          nodeColor={(n) => {
            const status = (n.data as NodeData)?.status;
            if (status === "in_progress") return "#10b981";
            if (status === "predicted") return "#f59e0b";
            if (status === "abandoned") return "#71717a";
            if ((n.data as NodeData)?.node?.node_type === "root")
              return "#3b8d61";
            return "#8fcaa6";
          }}
          nodeStrokeWidth={3}
          nodeStrokeColor="rgba(0,0,0,0.3)"
          pannable
          zoomable
          className="!shadow-lg !w-48 !h-32"
          maskColor="rgba(0,0,0,0.06)"
        />
      </ReactFlow>
    </>
  );
}

// ---------- Context menu ----------

interface ContextMenuState {
  nodeId: string;
  x: number;
  y: number;
}

function ContextMenu({
  state,
  node,
  onClose,
  onAction,
  t,
}: {
  state: ContextMenuState;
  node: DecisionTreeNode | null;
  onClose: () => void;
  onAction: (action: TreeAction) => void;
  t: (k: string) => string;
}) {
  useEffect(() => {
    function onDown(e: MouseEvent) {
      const target = e.target as Element;
      if (target.closest("[data-context-menu='true']")) return;
      onClose();
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  if (!node) return null;
  const status = canonicalizeStatus(node.status);

  // Build the action list — order matches the spec:
  // 确认 / 选择此路径 / 放弃 / 添加子分支 / 探索新分支
  const items: {
    action: TreeAction;
    label: string;
    icon: typeof CheckCircle2;
    disabled?: boolean;
    danger?: boolean;
  }[] = [
    {
      action: "confirm",
      label: t("tree.confirm"),
      icon: CheckCircle2,
      disabled: status !== "predicted",
    },
    {
      action: "select",
      label: t("tree.select"),
      icon: Play,
      disabled: status === "abandoned" || status === "predicted",
    },
    {
      action: "abandon",
      label: t("tree.abandon"),
      icon: Ban,
      disabled: status === "abandoned",
      danger: true,
    },
    { action: "addChild", label: t("tree.addChild"), icon: Plus },
    { action: "evolve", label: t("tree.evolve"), icon: Sparkles },
  ];

  if (typeof document === "undefined") return null;
  return createPortal(
    <div
      data-context-menu="true"
      role="menu"
      style={{
        position: "fixed",
        left: state.x,
        top: state.y,
        zIndex: 200,
        width: 200,
      }}
      className="rounded-lg border border-black/10 dark:border-white/10 bg-white dark:bg-zinc-950 shadow-xl py-1"
    >
      {items.map((item) => {
        const Icon = item.icon;
        return (
          <button
            key={item.action}
            type="button"
            role="menuitem"
            disabled={item.disabled}
            onClick={() => {
              onAction(item.action);
              onClose();
            }}
            className={cn(
              "flex items-center gap-2.5 w-full px-3 py-1.5 text-xs transition-colors text-left",
              item.disabled
                ? "text-zinc-400 dark:text-zinc-600 cursor-not-allowed"
                : item.danger
                ? "text-red-600 dark:text-red-400 hover:bg-red-500/10"
                : "text-zinc-700 dark:text-zinc-300 hover:bg-black/5 dark:hover:bg-white/5"
            )}
          >
            <Icon className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">{item.label}</span>
          </button>
        );
      })}
    </div>,
    document.body
  );
}

// ---------- Side panel (drawer) ----------

function SidePanel({
  node,
  onClose,
  onAction,
  busy,
  t,
}: {
  node: DecisionTreeNode;
  onClose: () => void;
  onAction: (action: TreeAction) => void;
  busy: boolean;
  t: (k: string, v?: Record<string, string | number>) => string;
}) {
  const status = canonicalizeStatus(node.status);
  const p50 = node.probability?.p50;
  const p10 = node.probability?.p10;
  const p90 = node.probability?.p90;
  const style = STATUS_STYLES[status];

  return (
    <aside className="absolute right-3 top-3 bottom-3 w-80 xl:w-96 z-20 flex flex-col rounded-xl border border-black/10 dark:border-white/10 bg-surface/95 backdrop-blur-md shadow-xl overflow-hidden">
      <div className="flex items-start justify-between gap-2 p-3 border-b border-black/5 dark:border-white/5 shrink-0">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 mb-1">
            <StatusBadge status={status} t={t} />
            {node.region && (
              <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] border bg-violet-500/10 text-violet-700 dark:text-violet-300 border-violet-500/20">
                {node.region}
              </span>
            )}
          </div>
          <h2
            className={cn(
              "text-sm font-semibold text-zinc-900 dark:text-zinc-100",
              status === "abandoned" && "line-through opacity-60"
            )}
          >
            {node.name}
          </h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="shrink-0 rounded-md p-1 text-zinc-500 hover:bg-black/5 dark:hover:bg-white/5"
          aria-label="Close"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-4 text-xs">
        {node.description && (
          <Section label={t("tree.description")}>
            <p className="text-zinc-700 dark:text-zinc-300 leading-relaxed">
              {node.description}
            </p>
          </Section>
        )}

        {node.node_type === "decision" && node.decision_question && (
          <Section label={t("tree.decisionQuestion")}>
            <p className="text-amber-700 dark:text-amber-300 italic leading-relaxed">
              {node.decision_question}
            </p>
          </Section>
        )}

        {status === "predicted" && node.evolution_hint && (
          <Section label={t("tree.evolutionHint")}>
            <p className="text-amber-700 dark:text-amber-300 leading-relaxed bg-amber-500/5 border border-amber-500/20 rounded p-2">
              {node.evolution_hint}
            </p>
          </Section>
        )}

        {node.probability && (
          <Section label={t("tree.probability")}>
            <div className="space-y-2">
              <ProbBar label="P50" value={p50} color="#3b8d61" />
              <ProbBar label="P10" value={p10} color="#ef4444" />
              <ProbBar label="P90" value={p90} color="#22c55e" />
            </div>
          </Section>
        )}

        {node.requirements && node.requirements.length > 0 && (
          <Section label={t("tree.requirements")}>
            <ul className="space-y-1.5">
              {node.requirements.map((r) => {
                const gap = r.gap_status;
                const gapClass =
                  gap === "met"
                    ? "text-emerald-600 dark:text-emerald-400 bg-emerald-500/10 border-emerald-500/20"
                    : gap === "partial"
                    ? "text-amber-600 dark:text-amber-400 bg-amber-500/10 border-amber-500/20"
                    : gap === "missing"
                    ? "text-red-600 dark:text-red-400 bg-red-500/10 border-red-500/20"
                    : "text-zinc-500 dark:text-zinc-400 bg-zinc-500/10 border-zinc-500/20";
                return (
                  <li
                    key={r.id}
                    className="flex items-center justify-between gap-2"
                  >
                    <div className="min-w-0">
                      <div className="text-zinc-800 dark:text-zinc-200 truncate">
                        {r.name}
                      </div>
                      <div className="text-[10px] text-zinc-500">
                        {r.type}
                      </div>
                    </div>
                    <span
                      className={cn(
                        "shrink-0 px-1.5 py-0.5 rounded text-[10px] border",
                        gapClass
                      )}
                    >
                      {t(`tree.gap.${gap}`)}
                    </span>
                  </li>
                );
              })}
            </ul>
          </Section>
        )}

        {node.risk_factors && node.risk_factors.length > 0 && (
          <Section label={t("tree.riskFactors")}>
            <ul className="space-y-1.5">
              {node.risk_factors.map((r) => {
                const lvl = r.level;
                const lvlClass =
                  lvl === "low"
                    ? "text-emerald-600 dark:text-emerald-400 bg-emerald-500/10 border-emerald-500/20"
                    : lvl === "medium"
                    ? "text-amber-600 dark:text-amber-400 bg-amber-500/10 border-amber-500/20"
                    : lvl === "high"
                    ? "text-red-600 dark:text-red-400 bg-red-500/10 border-red-500/20"
                    : "text-zinc-500 dark:text-zinc-400 bg-zinc-500/10 border-zinc-500/20";
                return (
                  <li
                    key={r.id}
                    className="flex items-center justify-between gap-2"
                  >
                    <div className="min-w-0">
                      <div className="text-zinc-800 dark:text-zinc-200 truncate">
                        {r.name}
                      </div>
                      <div className="text-[10px] text-zinc-500">
                        {r.type}
                      </div>
                    </div>
                    <span
                      className={cn(
                        "shrink-0 px-1.5 py-0.5 rounded text-[10px] border",
                        lvlClass
                      )}
                    >
                      {t(`tree.riskLevel.${lvl}`)}
                    </span>
                  </li>
                );
              })}
            </ul>
          </Section>
        )}
      </div>

      <div className="p-3 border-t border-black/5 dark:border-white/5 grid grid-cols-2 gap-1.5 shrink-0">
        <SidePanelButton
          icon={CheckCircle2}
          label={t("tree.confirm")}
          disabled={busy || status !== "predicted"}
          onClick={() => onAction("confirm")}
        />
        <SidePanelButton
          icon={Play}
          label={t("tree.select")}
          disabled={
            busy || status === "abandoned" || status === "predicted"
          }
          onClick={() => onAction("select")}
        />
        <SidePanelButton
          icon={Ban}
          label={t("tree.abandon")}
          disabled={busy || status === "abandoned"}
          danger
          onClick={() => onAction("abandon")}
        />
        <SidePanelButton
          icon={Plus}
          label={t("tree.addChild")}
          disabled={busy}
          onClick={() => onAction("addChild")}
        />
        <SidePanelButton
          icon={Sparkles}
          label={t("tree.evolve")}
          disabled={busy}
          onClick={() => onAction("evolve")}
          full
        />
      </div>
    </aside>
  );
}

function Section({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-zinc-500 dark:text-zinc-400 font-semibold mb-1">
        {label}
      </div>
      {children}
    </div>
  );
}

function ProbBar({
  label,
  value,
  color,
}: {
  label: string;
  value?: number;
  color: string;
}) {
  const pct = value != null ? Math.round(value * 100) : null;
  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] text-zinc-500 w-8">{label}</span>
      <div className="flex-1 h-2 rounded-full bg-black/5 dark:bg-white/5 overflow-hidden">
        <div
          className="h-full transition-all"
          style={{
            width: `${pct ?? 0}%`,
            backgroundColor: color,
          }}
        />
      </div>
      <span className="text-[10px] tabular-nums text-zinc-700 dark:text-zinc-300 w-10 text-right">
        {pct != null ? `${pct}%` : "—"}
      </span>
    </div>
  );
}

function SidePanelButton({
  icon: Icon,
  label,
  onClick,
  disabled,
  danger,
  full,
}: {
  icon: typeof CheckCircle2;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  danger?: boolean;
  full?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "inline-flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-md text-[11px] font-medium transition-colors border",
        full && "col-span-2",
        disabled
          ? "opacity-50 cursor-not-allowed border-black/5 dark:border-white/5 text-zinc-400 dark:text-zinc-600"
          : danger
          ? "border-red-500/30 text-red-600 dark:text-red-400 hover:bg-red-500/10"
          : "border-black/10 dark:border-white/10 text-zinc-700 dark:text-zinc-300 hover:bg-black/5 dark:hover:bg-white/5"
      )}
    >
      <Icon className="h-3 w-3" />
      {label}
    </button>
  );
}

// ---------- Legend ----------

function Legend({
  t,
}: {
  t: (k: string) => string;
}) {
  const items: { color: string; labelKey: string }[] = [
    { color: "#f59e0b", labelKey: "tree.predicted" },
    { color: "#0ea5e9", labelKey: "tree.confirmed" },
    { color: "#10b981", labelKey: "tree.inProgress" },
    { color: "#71717a", labelKey: "tree.abandoned" },
  ];
  return (
    <div className="flex flex-wrap items-center gap-3">
      <span className="text-[10px] uppercase tracking-wider text-zinc-500 dark:text-zinc-400 font-semibold">
        {t("tree.legend")}
      </span>
      {items.map((i) => (
        <div
          key={i.labelKey}
          className="flex items-center gap-1.5 text-[11px] text-zinc-600 dark:text-zinc-400"
        >
          <span
            className="h-2.5 w-2.5 rounded-sm"
            style={{ backgroundColor: i.color }}
          />
          {t(i.labelKey)}
        </div>
      ))}
    </div>
  );
}

// ---------- "Add child" dialog ----------

function AddChildDialog({
  open,
  onOpenChange,
  onSubmit,
  t,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onSubmit: (data: {
    name: string;
    description?: string;
    region?: string;
  }) => Promise<void>;
  t: (k: string) => string;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [region, setRegion] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) {
      setName("");
      setDescription("");
      setRegion("");
    }
  }, [open]);

  async function handleSubmit() {
    if (!name.trim()) return;
    setBusy(true);
    try {
      await onSubmit({
        name: name.trim(),
        description: description.trim() || undefined,
        region: region.trim() || undefined,
      });
      onOpenChange(false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t("tree.addChildTitle")}</DialogTitle>
          <DialogDescription>{t("tree.addChildDesc")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label className="text-xs">{t("tree.addChildName")}</Label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("tree.addChildNamePlaceholder")}
              className="h-9 text-sm"
              autoFocus
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs">{t("tree.addChildDescLabel")}</Label>
            <Textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t("tree.addChildDescPlaceholder")}
              rows={2}
              className="text-xs"
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs">{t("tree.addChildRegion")}</Label>
            <Input
              value={region}
              onChange={(e) => setRegion(e.target.value)}
              placeholder={t("tree.addChildRegionPlaceholder")}
              className="h-9 text-sm"
            />
          </div>
        </div>
        <DialogFooter>
          <DialogClose asChild>
            <Button size="sm" variant="ghost">
              {t("common.cancel")}
            </Button>
          </DialogClose>
          <Button size="sm" onClick={handleSubmit} disabled={!name.trim() || busy}>
            {busy ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />
            ) : (
              <Plus className="h-3.5 w-3.5 mr-1" />
            )}
            {t("tree.addChildSubmit")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------- Action types ----------

type TreeAction = "confirm" | "select" | "abandon" | "addChild" | "evolve";

// ---------- Main workspace component ----------

export interface DecisionTreeWorkspaceProps {
  /** Goal ID whose decision tree should be fetched & rendered. */
  goalId: string;
  /**
   * Optional className applied to the workspace root. Use this to
   * override the default tab-friendly height (e.g. `h-full flex-1
   * min-h-0` for fullscreen embedding, or `h-full` to fill a parent
   * container). Conflicting Tailwind classes are merged via twMerge.
   */
  className?: string;
}

export function DecisionTreeWorkspace({
  goalId,
  className,
}: DecisionTreeWorkspaceProps) {
  const t = useT();
  const toast = useToast();

  const swrKey = ["decision-tree", goalId] as const;
  const { data, error, isLoading, mutate } = useSWR(
    swrKey,
    () => getDecisionTree(goalId),
    {
      revalidateOnFocus: false,
      shouldRetryOnError: false,
      dedupingInterval: 5000,
    }
  );

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const [direction, setDirection] = useState<"LR" | "TB">("LR");
  const [evolvingIds, setEvolvingIds] = useState<Set<string>>(new Set());
  const [busyId, setBusyId] = useState<string | null>(null);
  const [exploringAll, setExploringAll] = useState(false);
  const [addChildTarget, setAddChildTarget] = useState<string | null>(null);

  // Find the currently selected node from the tree (re-derived on every
  // mutate so the panel always reflects the freshest server state).
  const selectedNode = useMemo(() => {
    if (!data || !selectedId) return null;
    const flat = flattenTree(data);
    return flat.find((f) => f.id === selectedId)?.node ?? null;
  }, [data, selectedId]);

  const contextNode = useMemo(() => {
    if (!data || !contextMenu) return null;
    const flat = flattenTree(data);
    return flat.find((f) => f.id === contextMenu.nodeId)?.node ?? null;
  }, [data, contextMenu]);

  // ---------- Actions ----------

  const refresh = useCallback(() => {
    void mutate();
  }, [mutate]);

  const handleSelect = useCallback((id: string) => {
    setSelectedId(id);
  }, []);

  const handleContextMenu = useCallback(
    (id: string, x: number, y: number) => {
      setContextMenu({ nodeId: id, x, y });
    },
    []
  );

  // Central action handler — used by both the side panel and the context
  // menu so behaviour stays identical.
  const runAction = useCallback(
    async (
      action: TreeAction,
      targetId: string,
      payload?: { name: string; description?: string; region?: string }
    ) => {
      const target =
        data && flattenTree(data).find((f) => f.id === targetId)?.node;
      const targetName = target?.name ?? targetId;
      setBusyId(targetId);
      try {
        if (action === "confirm") {
          await confirmBranch(targetId);
          toast({
            title: t("tree.toast.confirmed"),
            description: targetName,
            variant: "success",
          });
        } else if (action === "select") {
          await selectBranch(targetId, true);
          toast({
            title: t("tree.toast.selected"),
            description: targetName,
            variant: "success",
          });
        } else if (action === "abandon") {
          await abandonBranch(targetId);
          toast({
            title: t("tree.toast.abandoned"),
            description: targetName,
            variant: "default",
          });
        } else if (action === "addChild") {
          if (!payload) {
            setAddChildTarget(targetId);
          } else {
            await growBranch(targetId, payload);
            toast({
              title: t("tree.toast.grown"),
              description: payload.name,
              variant: "success",
            });
          }
        } else if (action === "evolve") {
          setEvolvingIds((prev) => new Set(prev).add(targetId));
          try {
            const predicted = await evolveBranch(targetId);
            toast({
              title: t("tree.toast.evolved", { n: predicted.length }),
              variant: "success",
            });
          } finally {
            setEvolvingIds((prev) => {
              const next = new Set(prev);
              next.delete(targetId);
              return next;
            });
          }
        }
        // Refresh the tree to pick up backend changes. For "addChild"
        // without payload we just open the dialog (no refresh yet).
        if (!(action === "addChild" && !payload)) {
          refresh();
        }
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        toast({
          title: t("tree.toast.failed"),
          description: msg,
          variant: "error",
        });
      } finally {
        setBusyId(null);
      }
    },
    [data, toast, t, refresh]
  );

  // "探索全部" — evolve every leaf node sequentially (sequential so we
  // don't hammer the LLM backend with N concurrent requests).
  const handleExploreAll = useCallback(async () => {
    if (!data || exploringAll) return;
    const leaves = collectLeaves(data);
    if (leaves.length === 0) {
      toast({ title: t("tree.toast.noLeaves"), variant: "default" });
      return;
    }
    setExploringAll(true);
    try {
      let totalNew = 0;
      const failedLeaves: string[] = [];
      for (const leaf of leaves) {
        setEvolvingIds((prev) => new Set(prev).add(leaf.id));
        try {
          const predicted = await evolveBranch(leaf.id);
          totalNew += predicted.length;
        } catch (e: unknown) {
          const msg = e instanceof Error ? e.message : String(e);
          failedLeaves.push(`${leaf.name}: ${msg}`);
        } finally {
          setEvolvingIds((prev) => {
            const next = new Set(prev);
            next.delete(leaf.id);
            return next;
          });
        }
      }
      if (failedLeaves.length > 0) {
        toast({
          title: t("tree.toast.exploreAllPartial", {
            n: totalNew,
            failed: failedLeaves.length,
          }),
          description: failedLeaves.slice(0, 3).join("\n"),
          variant: totalNew > 0 ? "warning" : "error",
        });
      } else {
        toast({
          title: t("tree.toast.exploreAllDone", { n: totalNew }),
          variant: "success",
        });
      }
      refresh();
    } finally {
      setExploringAll(false);
    }
  }, [data, exploringAll, toast, t, refresh]);

  // ---------- Render ----------

  const showSkeleton = isLoading && !data;
  const showError = !!error && !data;
  const showEmpty = !isLoading && !data && !error;

  return (
    <div
      className={cn(
        "flex flex-col h-[60vh] min-h-[400px] max-h-full min-w-0 overflow-hidden rounded-lg border border-black/5 dark:border-white/5 bg-surface",
        className
      )}
    >
      {/* Compact toolbar — legend (left) + explore all / layout toggle (right) */}
      <div className="flex items-center justify-between gap-2 flex-wrap px-3 py-2 border-b border-black/5 dark:border-white/5 shrink-0">
        <Legend t={t} />
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="default"
            onClick={handleExploreAll}
            disabled={exploringAll || !data}
            title={t("tree.exploreAllHint")}
          >
            {exploringAll ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />
            ) : (
              <Sparkles className="h-3.5 w-3.5 mr-1" />
            )}
            {exploringAll ? t("tree.evolving") : t("tree.exploreAll")}
          </Button>
          {/* Layout toggle */}
          <div className="inline-flex items-center rounded-md border border-black/10 dark:border-white/10 bg-black/5 dark:bg-white/5 p-0.5">
            <button
              type="button"
              onClick={() => setDirection("LR")}
              className={cn(
                "inline-flex items-center px-2 py-1 rounded text-[11px] transition-colors",
                direction === "LR"
                  ? "bg-brand-500/20 text-brand-700 dark:text-brand-300"
                  : "text-zinc-500 dark:text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-100"
              )}
              title={t("tree.layoutHorizontal")}
            >
              {t("tree.layoutHorizontal")}
            </button>
            <button
              type="button"
              onClick={() => setDirection("TB")}
              className={cn(
                "inline-flex items-center px-2 py-1 rounded text-[11px] transition-colors",
                direction === "TB"
                  ? "bg-brand-500/20 text-brand-700 dark:text-brand-300"
                  : "text-zinc-500 dark:text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-100"
              )}
              title={t("tree.layoutVertical")}
            >
              {t("tree.layoutVertical")}
            </button>
          </div>
        </div>
      </div>

      {/* Canvas area */}
      <div className="flex-1 min-h-0 relative bg-background/30">
        {showSkeleton && (
          <div className="absolute inset-0 p-6 flex flex-col gap-4">
            <div className="flex items-center justify-center h-48">
              <Skeleton className="h-32 w-32 rounded-full" />
            </div>
            <div className="flex justify-center gap-3 flex-wrap">
              {[0, 1, 2, 3, 4].map((i) => (
                <Skeleton key={i} className="h-20 w-40 rounded-xl" />
              ))}
            </div>
            <div className="text-center text-xs text-zinc-500 dark:text-zinc-400">
              <Loader2 className="h-3.5 w-3.5 animate-spin inline mr-1.5" />
              {t("tree.loading")}
            </div>
          </div>
        )}

        {showError && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-8 text-center">
            <ShieldAlert className="h-10 w-10 text-red-500 opacity-60" />
            <p className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
              {t("tree.errorTitle")}
            </p>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 max-w-md">
              {error instanceof Error ? error.message : String(error)}
            </p>
            <Button size="sm" variant="outline" onClick={refresh}>
              {t("tree.retry")}
            </Button>
          </div>
        )}

        {showEmpty && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-8 text-center">
            <GitBranch className="h-10 w-10 text-brand-600 dark:text-brand-400 opacity-60" />
            <p className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
              {t("tree.noTree")}
            </p>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 max-w-md">
              {t("tree.noTreeHint")}
            </p>
            <Button asChild size="sm" variant="outline">
              <Link href={`/goals/${goalId}`}>
                <ArrowLeft className="h-3.5 w-3.5 mr-1" />
                {t("tree.back")}
              </Link>
            </Button>
          </div>
        )}

        {data && (
          <ReactFlowProvider>
            <TreeCanvas
              root={data}
              selectedId={selectedId}
              evolvingIds={evolvingIds}
              direction={direction}
              onSelect={handleSelect}
              onContextMenu={handleContextMenu}
            />
          </ReactFlowProvider>
        )}

        {/* Side panel — only when a node is selected */}
        {data && selectedNode && (
          <SidePanel
            node={selectedNode}
            onClose={() => setSelectedId(null)}
            onAction={(action) =>
              runAction(action, selectedNode.id)
            }
            busy={busyId === selectedNode.id}
            t={t}
          />
        )}

        {/* "AI正在分析..." overlay on evolving nodes — handled inline by
            the BranchNode via the evolving prop, no extra overlay needed. */}
        {exploringAll && (
          <div className="absolute top-3 left-1/2 -translate-x-1/2 z-30 inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-brand-500/15 border border-brand-500/30 text-brand-700 dark:text-brand-300 text-xs shadow-lg">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            {t("tree.evolving")}
          </div>
        )}
      </div>

      {/* Context menu */}
      {contextMenu && (
        <ContextMenu
          state={contextMenu}
          node={contextNode}
          onClose={() => setContextMenu(null)}
          onAction={(action) => {
            if (contextMenu) {
              runAction(action, contextMenu.nodeId);
            }
          }}
          t={t}
        />
      )}

      {/* Add-child dialog */}
      <AddChildDialog
        open={addChildTarget !== null}
        onOpenChange={(v) => {
          if (!v) setAddChildTarget(null);
        }}
        t={t}
        onSubmit={async (data) => {
          if (addChildTarget) {
            await runAction("addChild", addChildTarget, data);
            setAddChildTarget(null);
          }
        }}
      />
    </div>
  );
}
