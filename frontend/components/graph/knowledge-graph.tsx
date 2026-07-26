"use client";

import { useEffect, useRef, useState } from "react";
import { useTheme } from "next-themes";
import cytoscape, { type Core, type ElementDefinition } from "cytoscape";
// fcose is a force-directed layout that produces much better results for
// labeled graphs than the built-in cose. Must be registered before use.
import fcose from "cytoscape-fcose";

cytoscape.use(fcose);

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

export function KnowledgeGraph({ nodes, edges }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const { resolvedTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  // Default to dark on the server; flip to light only once we know.
  const palette = mounted && resolvedTheme === "light" ? LIGHT_PALETTE : DARK_PALETTE;

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
            "text-background-padding": 3,
            "text-background-opacity": 0.9,
            "text-rotation": "autorotate",
          },
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
      },
      minZoom: 0.2,
      maxZoom: 2.5,
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

  return <div ref={ref} className="cytoscape-container" />;
}
