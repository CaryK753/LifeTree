"use client";

import { useEffect, useRef, useState } from "react";
import { useTheme } from "next-themes";
import cytoscape, { type Core, type ElementDefinition } from "cytoscape";
// fcose is a force-directed layout that produces much better results for
// labeled graphs than the built-in cose. Must be registered before use.
import fcose from "cytoscape-fcose";
import { X, ExternalLink, ArrowRight } from "lucide-react";
import { useT } from "@/lib/i18n/provider";

cytoscape.use(fcose as unknown as Parameters<typeof cytoscape.use>[0]);

interface GraphNode {
  id: string;
  type: string;
  label: string;
  properties?: Record<string, unknown>;
}
interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  weight?: number;
}

interface Props {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

const TYPE_COLORS: Record<string, string> = {
  Goal: "#3b8d61",
  Pathway: "#5eab7f",
  Requirement: "#8fcaa6",
  RiskFactor: "#ef4444",
  Event: "#f59e0b",
  InformationSource: "#94a3b8",
  Scenario: "#a78bfa",
};

// Theme-aware palette. Cytoscape styles don't react to CSS variables, so we
// read `resolvedTheme` from next-themes and pick a palette. The graph is
// re-init'd whenever the theme changes (effect dep).
const DARK_PALETTE = {
  nodeText: "#e4e7e3",
  nodeBorder: "rgba(255,255,255,0.15)",
  goalBorder: "#bbe1c9",
  edgeLine: "rgba(255,255,255,0.15)",
  edgeArrow: "rgba(255,255,255,0.35)",
  edgeLabel: "rgba(255,255,255,0.55)",
  edgeLabelBg: "#0f1410",
};
const LIGHT_PALETTE = {
  nodeText: "#18181b",        // zinc-900
  nodeBorder: "rgba(0,0,0,0.18)",
  goalBorder: "#3b8d61",
  edgeLine: "rgba(0,0,0,0.2)",
  edgeArrow: "rgba(0,0,0,0.4)",
  edgeLabel: "rgba(0,0,0,0.65)",
  edgeLabelBg: "#fffefb",
};

// Friendly labels for node properties. Keys not listed here are shown as-is.
const PROP_LABELS: Record<string, string> = {
  type: "Type",
  subject: "Subject",
  action: "Action",
  object: "Object",
  occurred_at: "Occurred At",
  effective_at: "Effective At",
  old_value: "Old Value",
  new_value: "New Value",
  summary: "Summary",
  risk_flag_level: "Risk Level",
  risk_flag_type: "Risk Type",
  risk_flag_urgency: "Urgency",
  extraction_confidence: "Extraction Confidence",
  status: "Status",
  description: "Description",
  target_date: "Target Date",
  scenario: "Scenario",
  url: "URL",
  publisher: "Publisher",
  published_at: "Published At",
  credibility: "Credibility",
  level: "Level",
  probability: "Probability",
  impact: "Impact",
  half_life_days: "Half-life (days)",
  region: "Region",
  value: "Value",
  unit: "Unit",
  name: "Name",
  display_name: "Display Name",
  category: "Category",
  parent_pathway_id: "Parent Pathway",
  gap_status: "Gap Status",
  created_at: "Created At",
  updated_at: "Updated At",
  source_id: "Source",
};

function formatPropValue(key: string, value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number") return String(value);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  // ISO timestamp shortcut: show date portion only for readability
  if (key.endsWith("_at") && typeof value === "string" && value.length >= 10) {
    return value.slice(0, 10);
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

export function KnowledgeGraph({ nodes, edges }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const { resolvedTheme } = useTheme();
  const t = useT();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  // Default to dark on the server; flip to light only once we know.
  const palette = mounted && resolvedTheme === "light" ? LIGHT_PALETTE : DARK_PALETTE;

  // Selected node state for the detail panel.
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  // Track connected edges / neighbors for the panel.
  const [neighbors, setNeighbors] = useState<{ edgeType: string; direction: "out" | "in"; node: GraphNode }[]>([]);

  // Index for O(1) lookups when building the neighbor list.
  const nodesById = useRef<Map<string, GraphNode>>(new Map());

  useEffect(() => {
    nodesById.current = new Map(nodes.map((n) => [n.id, n]));
  }, [nodes]);

  useEffect(() => {
    if (!ref.current) return;

    // Filter out edges whose endpoints aren't in the node set; Cytoscape
    // throws "nonexistent target" if an edge references a missing node.
    const nodeIds = new Set(nodes.map((n) => n.id));
    const safeEdges = edges.filter(
      (e) => nodeIds.has(e.source) && nodeIds.has(e.target)
    );

    const elements: ElementDefinition[] = [
      ...nodes.map((n) => ({
        data: {
          id: n.id,
          label: n.label,
          type: n.type,
          color: TYPE_COLORS[n.type] ?? "#94a3b8",
        },
      })),
      ...safeEdges.map((e) => ({
        data: {
          id: e.id,
          source: e.source,
          target: e.target,
          label: e.type,
          weight: e.weight ?? 0,
        },
      })),
    ];

    if (elements.length === 0) {
      if (cyRef.current) {
        cyRef.current.destroy();
        cyRef.current = null;
      }
      return;
    }

    cyRef.current = cytoscape({
      container: ref.current,
      elements,
      // `wheelSensitivity` lower = smoother zoom; helps avoid accidental huge zoom.
      wheelSensitivity: 0.2,
      style: [
        {
          selector: "node",
          style: {
            "background-color": "data(color)",
            "label": "data(label)",
            "color": palette.nodeText,
            "font-size": "11px",
            "font-weight": 500,
            "text-wrap": "wrap",
            "text-max-width": "120px",
            "text-justification": "center",
            "text-valign": "bottom",
            "text-halign": "center",
            "text-margin-y": 10,
            "width": 30,
            "height": 30,
            "border-width": 2,
            "border-color": palette.nodeBorder,
            "transition-property": "border-color, border-width, opacity",
            "transition-duration": 180,
          },
        },
        {
          selector: "node[type = 'Goal']",
          style: { "width": 50, "height": 50, "border-color": palette.goalBorder, "font-size": "13px", "font-weight": 700 },
        },
        {
          selector: "node[type = 'Pathway']",
          style: { "width": 36, "height": 36, "font-size": "10px" },
        },
        {
          selector: "node[type = 'Requirement']",
          style: { "width": 24, "height": 24, "font-size": "9px" },
        },
        {
          selector: "node[type = 'RiskFactor']",
          style: { "shape": "diamond", "width": 32, "height": 32 },
        },
        {
          selector: "edge",
          style: {
            "width": 1.5,
            "line-color": palette.edgeLine,
            "target-arrow-color": palette.edgeArrow,
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
            "label": "data(label)",
            "font-size": "9px",
            "color": palette.edgeLabel,
            "text-background-color": palette.edgeLabelBg,
            "text-background-padding": "3px",
            "text-background-opacity": 0.9,
            "text-rotation": "autorotate",
            "transition-property": "line-color, target-arrow-color, opacity",
            "transition-duration": 180,
          },
        },
        // Highlight states — applied when a node is selected.
        {
          selector: "node.selected",
          style: {
            "border-color": "#3b8d61",
            "border-width": 4,
            "z-index": 99,
          },
        },
        {
          selector: "node.dimmed",
          style: { "opacity": 0.25 },
        },
        {
          selector: "edge.highlighted",
          style: {
            "line-color": "#5eab7f",
            "target-arrow-color": "#5eab7f",
            "width": 2.5,
            "z-index": 99,
          },
        },
        {
          selector: "edge.dimmed",
          style: { "opacity": 0.12 },
        },
      ],
      layout: {
        // fcose: force-directed layout that respects label dimensions and
        // produces non-overlapping node placements for labeled graphs.
        name: "fcose",
        animate: true,
        animationDuration: 800,
        padding: 80,
        // Node repulsion (higher = more spread out).
        nodeRepulsion: 8000,
        // Ideal edge length (in layout pixels).
        idealEdgeLength: 200,
        edgeElasticity: 0.45,
        gravity: 0.2,
        gravityRangeCompound: 1.5,
        numIter: 3500,
        // Tile disconnected components in a grid so they don't all pile on
        // top of each other in the center.
        tile: true,
        tilingPaddingVertical: 50,
        tilingPaddingHorizontal: 50,
        // Pack components into a compact area.
        packComponents: true,
        // Critical: include label dimensions so nodes don't get placed as if
        // their label text doesn't exist.
        nodeDimensionsIncludeLabels: true,
        fit: true,
        randomize: true,
      } as unknown as cytoscape.LayoutOptions,
      minZoom: 0.2,
      maxZoom: 2.5,
    });

    // §5 透明化 — tap on a node opens the detail panel with its properties
    // and a list of connected entities. Clicking a neighbor navigates to it.
    // Clicking empty canvas closes the panel and clears the highlight.
    const selectNode = (nodeId: string) => {
      const cy = cyRef.current;
      if (!cy) return;
      const node = nodesById.current.get(nodeId);
      if (!node) return;

      // Collect neighbors via incident edges.
      const cyNode = cy.getElementById(nodeId);
      const connectedEdges = cyNode.connectedEdges();
      const neighborList: { edgeType: string; direction: "out" | "in"; node: GraphNode }[] = [];
      connectedEdges.forEach((edge) => {
        const isOutgoing = edge.source().id() === nodeId;
        const otherId = isOutgoing ? edge.target().id() : edge.source().id();
        const otherNode = nodesById.current.get(otherId);
        if (otherNode) {
          neighborList.push({
            edgeType: edge.data("label") ?? "",
            direction: isOutgoing ? "out" : "in",
            node: otherNode,
          });
        }
      });

      // Apply visual highlight: dim everything, then highlight the selected
      // node + its neighbors + the edges connecting them.
      cy.elements().removeClass("selected dimmed highlighted");
      cy.elements().addClass("dimmed");
      cyNode.removeClass("dimmed").addClass("selected");
      connectedEdges.removeClass("dimmed").addClass("highlighted");
      connectedEdges.connectedNodes().removeClass("dimmed");

      setSelectedNode(node);
      setNeighbors(neighborList);
    };

    const clearSelection = () => {
      const cy = cyRef.current;
      if (!cy) return;
      cy.elements().removeClass("selected dimmed highlighted");
      setSelectedNode(null);
      setNeighbors([]);
    };

    cyRef.current.on("tap", "node", (evt) => {
      const id = evt.target.id();
      selectNode(id);
    });
    cyRef.current.on("tap", (evt) => {
      // Tap on empty canvas (no target) clears the selection.
      if (evt.target === cyRef.current) {
        clearSelection();
      }
    });

    // After initial layout, fit with extra padding so border labels aren't clipped.
    setTimeout(() => {
      cyRef.current?.fit(undefined, 100);
    }, 100);

    return () => {
      cyRef.current?.destroy();
      cyRef.current = null;
    };
  }, [nodes, edges, palette]);

  // When the detail panel is closed via the X button, clear highlight too.
  const handleClosePanel = () => {
    const cy = cyRef.current;
    if (cy) cy.elements().removeClass("selected dimmed highlighted");
    setSelectedNode(null);
    setNeighbors([]);
  };

  // Click a neighbor chip in the panel — select that node in the graph.
  const handleNeighborClick = (nodeId: string) => {
    const cy = cyRef.current;
    if (!cy) return;
    // Re-run the same highlight logic as tap, then re-center on the node.
    const node = cy.getElementById(nodeId);
    if (node.empty()) return;
    cy.animate({ center: { eles: node }, zoom: cy.zoom() }, { duration: 250 });
    // Emit tap so the registered handler re-runs the highlight + state update.
    node.emit("tap");
  };

  return (
    <div className="relative h-full w-full">
      <div ref={ref} className="cytoscape-container" />

      {/* Detail panel — floats above the graph canvas on the right.
          §5 透明化: 点击节点查看详情、下钻到原始事件。*/}
      {selectedNode && (
        <aside
          className="absolute right-3 top-3 bottom-3 w-72 xl:w-80 z-10 rounded-lg border border-black/10 dark:border-white/10 bg-surface/95 backdrop-blur-md shadow-2xl shadow-black/30 flex flex-col overflow-hidden"
          role="dialog"
          aria-label={t("graph.nodeDetails")}
        >
          {/* Header — color stripe by node type + close button */}
          <div className="shrink-0 p-3 border-b border-black/5 dark:border-white/5">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span
                    className="h-2.5 w-2.5 rounded-sm shrink-0"
                    style={{ backgroundColor: TYPE_COLORS[selectedNode.type] ?? "#94a3b8" }}
                    aria-hidden
                  />
                  <span className="text-[10px] uppercase tracking-wide font-medium text-zinc-500 dark:text-zinc-400">
                    {selectedNode.type}
                  </span>
                </div>
                <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100 mt-1 break-words">
                  {selectedNode.label}
                </h3>
              </div>
              <button
                type="button"
                onClick={handleClosePanel}
                className="shrink-0 h-7 w-7 inline-flex items-center justify-center rounded-md text-zinc-500 hover:bg-black/5 dark:hover:bg-white/5 hover:text-zinc-700 dark:hover:text-zinc-300"
                aria-label={t("common.close")}
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>

          {/* Body — properties + neighbors */}
          <div className="flex-1 overflow-y-auto p-3 space-y-4">
            {/* Properties */}
            {selectedNode.properties &&
            Object.keys(selectedNode.properties).length > 0 ? (
              <div>
                <div className="text-[10px] uppercase tracking-wide font-medium text-zinc-500 dark:text-zinc-400 mb-1.5">
                  {t("graph.properties")}
                </div>
                <dl className="space-y-1">
                  {Object.entries(selectedNode.properties).map(([key, value]) => (
                    <div
                      key={key}
                      className="flex justify-between gap-2 text-xs leading-relaxed"
                    >
                      <dt className="text-zinc-500 dark:text-zinc-400 shrink-0">
                        {PROP_LABELS[key] ?? key}
                      </dt>
                      <dd className="text-zinc-800 dark:text-zinc-200 text-right break-all">
                        {formatPropValue(key, value)}
                      </dd>
                    </div>
                  ))}
                </dl>
              </div>
            ) : (
              <div className="text-xs text-zinc-500 dark:text-zinc-400 italic">
                {t("graph.noProperties")}
              </div>
            )}

            {neighbors.length > 0 && (
              <div>
                <div className="text-[10px] uppercase tracking-wide font-medium text-zinc-500 dark:text-zinc-400 mb-1.5">
                  {t("graph.connected", { n: neighbors.length })}
                </div>
                <ul className="space-y-1">
                  {neighbors.map((nb, i) => (
                    <li key={`${nb.node.id}-${i}`}>
                      <button
                        type="button"
                        onClick={() => handleNeighborClick(nb.node.id)}
                        className="w-full text-left p-1.5 rounded-md hover:bg-black/5 dark:hover:bg-white/5 transition-colors group"
                      >
                        <div className="flex items-center gap-1.5 text-[10px] text-zinc-500 dark:text-zinc-400">
                          <ArrowRight
                            className={`h-2.5 w-2.5 shrink-0 ${
                              nb.direction === "in" ? "rotate-180" : ""
                            }`}
                          />
                          <span className="truncate">{nb.edgeType || t("graph.relatedTo")}</span>
                        </div>
                        <div className="flex items-center gap-1.5 mt-0.5 pl-4">
                          <span
                            className="h-2 w-2 rounded-sm shrink-0"
                            style={{ backgroundColor: TYPE_COLORS[nb.node.type] ?? "#94a3b8" }}
                            aria-hidden
                          />
                          <span className="text-xs text-zinc-800 dark:text-zinc-200 truncate group-hover:text-brand-700 dark:group-hover:text-brand-300">
                            {nb.node.label}
                          </span>
                          <span className="text-[9px] uppercase tracking-wide text-zinc-400 ml-auto shrink-0">
                            {nb.node.type}
                          </span>
                        </div>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Drill-down to source — for Event nodes, link to /sources page */}
            {selectedNode.type === "Event" &&
              Boolean(selectedNode.properties?.source_id) && (
              <a
                href={`/sources`}
                className="inline-flex items-center gap-1 text-xs text-brand-700 dark:text-brand-300 hover:underline"
              >
                <ExternalLink className="h-3 w-3" />
                {t("graph.viewSource")}
              </a>
            )}
          </div>
        </aside>
      )}
    </div>
  );
}
