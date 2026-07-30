/**
 * Decision Tree API client.
 *
 * Pathways form a self-growing decision tree under each Goal. This module
 * wraps the tree-fetch + lifecycle endpoints (grow / evolve / confirm /
 * select / abandon) and exposes strongly-typed helpers used by the
 * React Flow visualization in `app/tree/[goalId]`.
 *
 * All requests reuse the shared `request()` helper from `lib/api.ts` so
 * the Authorization header, 401-refresh retry, and base URL prefix are
 * handled consistently with the rest of the app.
 */

import { request } from "./api";

// ---------- Types ----------

export interface DecisionTreeNode {
  id: string;
  name: string;
  description?: string;
  status: string;
  node_type: "root" | "decision" | "branch" | "milestone" | string;
  decision_question?: string;
  tree_level: number;
  display_order: number;
  evolution_hint?: string;
  region?: string;
  scenario_id?: string;
  parent_pathway_id?: string;
  children: DecisionTreeNode[];
  requirements: { id: string; name: string; type: string; gap_status: string }[];
  risk_factors: { id: string; name: string; level: string; type: string }[];
  probability?: { p50: number; p10: number; p90: number };
}

export interface PredictedBranch {
  pathway_id: string;
  name: string;
  description: string;
  status: "predicted";
  evolution_hint: string;
  probability: { p50: number; p10: number; p90: number };
  key_risk_factors: { name: string; level: string }[];
  run_error?: string;
}

// The backend returns the full Pathway row for confirm/select/abandon/grow.
// We keep the type loose (Record<string, unknown>) because the shape is
// shared with `api.listPathways` and isn't fully typed today.
export type Pathway = Record<string, unknown>;

interface DecisionTreeResponse {
  goal_id: string;
  goal_title: string;
  roots: DecisionTreeNode[];
}

// ---------- Status normalization ----------
//
// The decision tree defines a canonical state machine:
//   predicted → confirmed → in_progress → (abandoned | milestone)
// plus legacy states that pre-date the tree model. We normalize any
// legacy value to its closest canonical equivalent so the UI only has to
// reason about 4 visual states.

export type CanonicalStatus =
  | "predicted"
  | "confirmed"
  | "in_progress"
  | "abandoned";

export function canonicalizeStatus(raw: string): CanonicalStatus {
  switch (raw) {
    case "predicted":
    case "confirmed":
    case "in_progress":
    case "abandoned":
      return raw;
    // Legacy mappings
    case "candidate":
      return "confirmed";
    case "selected":
      return "in_progress";
    case "rejected":
    case "superseded":
      return "abandoned";
    default:
      // Unknown states default to "confirmed" so the node renders as a
      // solid, non-pulsing card rather than a虚线 AI-prediction.
      return "confirmed";
  }
}

// ---------- API functions ----------

/**
 * GET /api/goals/{goalId}/tree — nested tree structure for React Flow.
 *
 * Returns the root pathway with `children` populated recursively. The
 * caller (the tree page) flattens this into nodes + edges for React Flow.
 */
export async function getDecisionTree(goalId: string): Promise<DecisionTreeNode | null> {
  const result = await request<DecisionTreeResponse>(
    `/goals/${encodeURIComponent(goalId)}/tree`
  );
  if (result.roots.length === 0) return null;
  if (result.roots.length === 1) return result.roots[0];
  return {
    id: `goal:${result.goal_id}`,
    name: result.goal_title,
    description: "",
    status: "confirmed",
    node_type: "root",
    tree_level: -1,
    display_order: 0,
    children: result.roots,
    requirements: [],
    risk_factors: [],
  };
}

/**
 * POST /api/pathways/{pathwayId}/grow — manually add a child branch.
 *
 * Used by the "添加子分支" context-menu action when the user wants to
 * create a branch by hand instead of running the LLM evolution pipeline.
 */
export async function growBranch(
  pathwayId: string,
  data: { name: string; description?: string; region?: string }
): Promise<Pathway> {
  return request<Pathway>(
    `/pathways/${encodeURIComponent(pathwayId)}/grow`,
    {
      method: "POST",
      body: JSON.stringify(data),
    }
  );
}

/**
 * POST /api/pathways/{pathwayId}/evolve — run LLM + math evolution.
 *
 * Triggers the evolution pipeline on the given pathway and returns the
 * predicted child branches that should be added to the tree.
 */
export async function evolveBranch(
  pathwayId: string
): Promise<PredictedBranch[]> {
  const result = await request<{ predicted_branches: PredictedBranch[] }>(
    `/pathways/${encodeURIComponent(pathwayId)}/evolve`,
    { method: "POST" }
  );
  return result.predicted_branches;
}

/**
 * POST /api/pathways/{pathwayId}/confirm — predicted → confirmed.
 *
 * The user accepts an AI-predicted branch, promoting it from 虚线 to 实线.
 */
export async function confirmBranch(pathwayId: string): Promise<Pathway> {
  return request<Pathway>(
    `/pathways/${encodeURIComponent(pathwayId)}/confirm`,
    { method: "POST" }
  );
}

/**
 * POST /api/pathways/{pathwayId}/select — confirmed → in_progress.
 *
 * The user commits to executing this branch. When `abandonSiblings` is
 * true, the backend atomically marks sibling pathways as abandoned so
 * only one in_progress branch exists per parent.
 */
export async function selectBranch(
  pathwayId: string,
  abandonSiblings?: boolean
): Promise<Pathway> {
  return request<Pathway>(
    `/pathways/${encodeURIComponent(pathwayId)}/select`,
    {
      method: "POST",
      body: JSON.stringify({ abandon_siblings: abandonSiblings ?? false }),
    }
  );
}

/**
 * POST /api/pathways/{pathwayId}/abandon — mark as abandoned.
 *
 * Abandoned branches render at 30% opacity with strikethrough text and
 * are excluded from future evolution runs.
 */
export async function abandonBranch(pathwayId: string): Promise<Pathway> {
  return request<Pathway>(
    `/pathways/${encodeURIComponent(pathwayId)}/abandon`,
    { method: "POST" }
  );
}

// ---------- Tree traversal helpers ----------
//
// These are pure utilities used by the page to flatten the nested tree
// returned by `getDecisionTree` into the flat arrays React Flow expects
// (nodes + edges) and to collect leaf nodes for "探索全部".

export interface FlatNode {
  id: string;
  parentId?: string;
  node: DecisionTreeNode;
}

/** Depth-first flatten — preserves parent → child relationships. */
export function flattenTree(root: DecisionTreeNode): FlatNode[] {
  const out: FlatNode[] = [];
  function walk(n: DecisionTreeNode, parentId?: string) {
    out.push({ id: n.id, parentId, node: n });
    for (const child of n.children ?? []) {
      walk(child, n.id);
    }
  }
  walk(root);
  return out;
}

/**
 * Collect leaf pathways (no children). Used by "探索全部" to evolve every
 * leaf in parallel — leaves are the natural growth points of the tree
 * since they represent choices that haven't been explored yet.
 */
export function collectLeaves(root: DecisionTreeNode): DecisionTreeNode[] {
  const leaves: DecisionTreeNode[] = [];
  const blockedStatuses = new Set([
    "predicted",
    "abandoned",
    "rejected",
    "superseded",
    "closed",
  ]);
  function walk(n: DecisionTreeNode) {
    if (!n.children || n.children.length === 0) {
      if (!blockedStatuses.has(n.status)) leaves.push(n);
      return;
    }
    for (const child of n.children) walk(child);
  }
  walk(root);
  return leaves;
}
