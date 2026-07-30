"""Decision-tree operation API (§11.3 self-growing tree).

Endpoints for inspecting / mutating the user's decision tree:

- ``GET /goals/{goal_id}/tree`` — full nested tree structure.
- ``POST /pathways/{pathway_id}/grow`` — manually add a child branch.
- ``POST /pathways/{pathway_id}/evolve`` — run the LLM+math evolution pipeline.
- ``POST /pathways/{pathway_id}/confirm`` — predicted → confirmed.
- ``POST /pathways/{pathway_id}/select`` — confirmed → in_progress (optionally
  abandon sibling branches at the same tree_level).
- ``POST /pathways/{pathway_id}/abandon`` — mark a branch as abandoned.
- ``POST /pathways/{pathway_id}/requirements`` — link a requirement (M2M).
- ``POST /pathways/{pathway_id}/risk-factors`` — link a risk factor (M2M).
- ``DELETE /pathways/{pathway_id}/requirements/{requirement_id}`` — unlink.
- ``DELETE /pathways/{pathway_id}/risk-factors/{risk_factor_id}`` — unlink.

All endpoints require authentication via ``CurrentUser`` and isolate data by
``pathway.goal.user_id == current_user.id`` (admin can read any).

Multi-user isolation mirrors the pattern in :mod:`app.api.goals`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.tenant import CurrentUser
from app.db.postgres import get_db
from app.models.goal import (
    Goal,
    Pathway,
    Requirement,
    RiskFactor,
    pathway_requirements,
    pathway_risk_factors,
)
from app.models.scenario import Scenario
from app.services.risk_scope import get_visible_risk, risk_scope_clause
from app.services.tree_evolution import TreeEvolutionService

router = APIRouter(tags=["decision-tree"])
log = get_logger(__name__)


# ---------- Ownership helpers (mirror goals.py pattern) ----------


def _get_owned_goal(goal_id: str, user: CurrentUser, db: Session) -> Goal:
    goal = db.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(404, "Goal not found")
    if goal.user_id != user.id and user.role != "admin":
        raise HTTPException(403, "You do not have access to this goal")
    return goal


def _get_owned_pathway(pathway_id: str, user: CurrentUser, db: Session) -> Pathway:
    pathway = db.get(Pathway, pathway_id)
    if pathway is None:
        raise HTTPException(404, "Pathway not found")
    goal = db.get(Goal, pathway.goal_id)
    if goal is None:
        raise HTTPException(404, "Goal not found")
    if goal.user_id != user.id and user.role != "admin":
        raise HTTPException(403, "You do not have access to this pathway")
    return pathway


# ---------- Request schemas ----------


class GrowBranchRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    region: str | None = Field(None, max_length=64)
    node_type: str = Field(
        "branch",
        description="One of: 'root', 'decision', 'branch', 'milestone'.",
    )


class SelectBranchRequest(BaseModel):
    abandon_siblings: bool = Field(
        False,
        description="If true, mark all sibling branches at the same tree_level as 'abandoned'.",
    )


class LinkRequirementRequest(BaseModel):
    requirement_id: str = Field(..., description="ID of the requirement to link.")
    is_blocking: bool = Field(
        True, description="Whether meeting this requirement is blocking for the pathway."
    )


class LinkRiskFactorRequest(BaseModel):
    risk_factor_id: str = Field(..., description="ID of the risk factor to link.")


# ---------- Tree serialization ----------


def _serialize_requirement(r: Requirement) -> dict[str, Any]:
    return {
        "id": r.id,
        "name": r.name,
        "type": r.type,
        "description": r.description,
        "threshold": r.threshold or {},
        "current_value": r.current_value or {},
        "gap_status": r.gap_status,
        "gap_delta": r.gap_delta,
        "weight": r.weight,
    }


def _serialize_risk_factor(rf: RiskFactor) -> dict[str, Any]:
    return {
        "id": rf.id,
        "name": rf.name,
        "type": rf.type,
        "description": rf.description,
        "region": rf.region,
        "level": rf.level,
        "urgency": rf.urgency,
        "probability": rf.probability,
        "impact": rf.impact,
    }


def _build_tree_node(
    pathway: Pathway,
    db: Session,
    children_by_parent: dict[str, list[Pathway]],
    requirement_index: dict[str, list[Requirement]],
    risk_factor_index: dict[str, list[RiskFactor]],
) -> dict[str, Any]:
    """Recursively build a nested tree node for a pathway.

    The *_index dicts are pre-built per-goal so we don't re-query the DB
    for every node (avoids N+1).

    As of v0.4.0, probability data is read directly from Pathway (merged
    from Scenario), so no scenario_index is needed.
    """
    reqs = requirement_index.get(pathway.id, [])
    rfs = risk_factor_index.get(pathway.id, [])

    # Read probability directly from Pathway (merged from Scenario in v0.4.0)
    probability: dict[str, Any] | None = None
    sp = pathway.success_probability or {}
    if sp:
        probability = {
            "p50": sp.get("p50"),
            "p10": sp.get("p10"),
            "p90": sp.get("p90"),
            "computed_at": pathway.computed_at.isoformat() if pathway.computed_at else None,
        }

    child_pathways = children_by_parent.get(pathway.id, [])
    children = [
        _build_tree_node(
            child,
            db,
            children_by_parent,
            requirement_index,
            risk_factor_index,
        )
        for child in child_pathways
    ]

    return {
        "id": pathway.id,
        "name": pathway.name,
        "description": pathway.description,
        "status": pathway.status,
        "node_type": pathway.node_type,
        "decision_question": pathway.decision_question,
        "tree_level": pathway.tree_level,
        "display_order": pathway.display_order,
        "evolution_hint": pathway.evolution_hint,
        "region": pathway.region,
        "scenario_id": pathway.scenario_id,
        "parent_pathway_id": pathway.parent_pathway_id,
        "goal_id": pathway.goal_id,
        "requirements": [_serialize_requirement(r) for r in reqs],
        "risk_factors": [_serialize_risk_factor(rf) for rf in rfs],
        "probability": probability,
        "children": children,
    }


def _load_tree_indexes(
    db: Session, goal_id: str, owner_user_id: str
) -> tuple[
    dict[str, list[Pathway]],
    dict[str, list[Requirement]],
    dict[str, list[RiskFactor]],
]:
    """Bulk-load everything needed to serialize a goal's tree in one pass.

    Returns ``(children_by_parent, requirements_by_pathway,
    risk_factors_by_pathway)``.

    As of v0.4.0, probability data is stored directly on Pathway, so the
    scenario_index is no longer needed.
    """
    # 1. All pathways for the goal (not deleted)
    all_pathways = list(
        db.scalars(
            select(Pathway)
            .where(Pathway.goal_id == goal_id)
            .order_by(Pathway.tree_level.asc(), Pathway.display_order.asc())
        )
    )
    pathway_ids = [p.id for p in all_pathways]

    # 2. Children index (parent_pathway_id → list of children)
    children_by_parent: dict[str, list[Pathway]] = {}
    for p in all_pathways:
        if p.parent_pathway_id:
            children_by_parent.setdefault(p.parent_pathway_id, []).append(p)

    # 3. Requirements via M2M (with legacy fallback for unmigrated data)
    requirements_by_pathway: dict[str, list[Requirement]] = {}
    if pathway_ids:
        rows = db.execute(
            select(
                pathway_requirements.c.pathway_id,
                Requirement,
            )
            .select_from(Requirement)
            .join(
                pathway_requirements,
                pathway_requirements.c.requirement_id == Requirement.id,
            )
            .where(pathway_requirements.c.pathway_id.in_(pathway_ids))
            .order_by(pathway_requirements.c.pathway_id, Requirement.weight.desc())
        ).all()
        for pid, req in rows:
            requirements_by_pathway.setdefault(pid, []).append(req)

        # Legacy fallback: any pathway with no M2M rows falls back to the
        # Requirement.pathway_id column.
        missing_pids = [
            pid for pid in pathway_ids if pid not in requirements_by_pathway
        ]
        if missing_pids:
            legacy_rows = list(
                db.scalars(
                    select(Requirement)
                    .where(Requirement.pathway_id.in_(missing_pids))
                    .order_by(Requirement.weight.desc())
                )
            )
            for req in legacy_rows:
                if req.pathway_id:
                    requirements_by_pathway.setdefault(req.pathway_id, []).append(req)

    # 4. Risk factors via M2M
    risk_factors_by_pathway: dict[str, list[RiskFactor]] = {}
    if pathway_ids:
        rows = db.execute(
            select(
                pathway_risk_factors.c.pathway_id,
                RiskFactor,
            )
            .select_from(RiskFactor)
            .join(
                pathway_risk_factors,
                pathway_risk_factors.c.risk_factor_id == RiskFactor.id,
            )
            .where(pathway_risk_factors.c.pathway_id.in_(pathway_ids))
            .where(
                RiskFactor.deleted_at.is_(None),
                risk_scope_clause(owner_user_id),
            )
            .order_by(pathway_risk_factors.c.pathway_id, RiskFactor.level.desc())
        ).all()
        for pid, rf in rows:
            risk_factors_by_pathway.setdefault(pid, []).append(rf)

    return (
        children_by_parent,
        requirements_by_pathway,
        risk_factors_by_pathway,
    )


# ---------- Endpoints ----------


@router.get("/goals/{goal_id}/tree")
def get_decision_tree(
    goal_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Return the full decision tree for a goal as a nested structure.

    Each node includes id/name/description/status/node_type/decision_question/
    tree_level/display_order/evolution_hint/region/scenario_id/
    parent_pathway_id, plus linked requirements/risk_factors (via M2M), the
    latest scenario probability if a scenario is linked, and the recursive
    ``children`` array.
    """
    goal = _get_owned_goal(goal_id, user, db)
    (
        children_by_parent,
        requirements_by_pathway,
        risk_factors_by_pathway,
    ) = _load_tree_indexes(db, goal.id, goal.user_id)

    # Roots = pathways with no parent_pathway_id. If there are none, fall back
    # to the goal's first pathway by created_at (legacy single-pathway goals).
    root_pathways = [
        p for p in db.scalars(
            select(Pathway)
            .where(Pathway.goal_id == goal.id, Pathway.parent_pathway_id.is_(None))
            .order_by(Pathway.tree_level.asc(), Pathway.display_order.asc(), Pathway.created_at.asc())
        )
    ]
    if not root_pathways:
        first = db.scalar(
            select(Pathway)
            .where(Pathway.goal_id == goal.id)
            .order_by(Pathway.created_at.asc())
        )
        if first is not None:
            root_pathways = [first]

    roots = [
        _build_tree_node(
            p,
            db,
            children_by_parent,
            requirements_by_pathway,
            risk_factors_by_pathway,
        )
        for p in root_pathways
    ]
    return {
        "goal_id": goal.id,
        "goal_title": goal.title,
        "roots": roots,
    }


@router.post("/pathways/{pathway_id}/grow")
def grow_branch(
    pathway_id: str,
    payload: GrowBranchRequest,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Manually add a child branch to a pathway.

    Creates a new Pathway with ``parent_pathway_id`` set,
    ``tree_level = parent.tree_level + 1``, ``status='confirmed'``.

    v0.4.0：不再创建子 Scenario。子 Pathway 直接继承父 Pathway 的
    ``assumptions``（向后兼容：父 Pathway 没有 assumptions 时回退到关联
    Scenario 的 assumptions）。``success_probability`` / ``risk_score`` /
    ``key_risk_factors`` / ``computed_at`` 初始化为空，等推理引擎填充。
    """
    parent = _get_owned_pathway(pathway_id, user, db)
    goal = db.get(Goal, parent.goal_id)

    # 解析父 Pathway 的 assumptions（向后兼容：回退到关联 Scenario）
    parent_assumptions = dict(parent.assumptions or {})
    if not parent_assumptions:
        parent_sc = db.get(Scenario, parent.scenario_id) if parent.scenario_id else None
        if parent_sc is None:
            # 反查 scenarios 表
            parent_sc = db.scalar(
                select(Scenario).where(
                    Scenario.pathway_id == parent.id,
                    Scenario.goal_id == parent.goal_id,
                ).order_by(Scenario.created_at.desc())
            )
        if parent_sc is not None:
            parent_assumptions = dict(parent_sc.assumptions or {})

    new_pathway = Pathway(
        goal_id=parent.goal_id,
        name=payload.name,
        description=payload.description,
        region=payload.region or parent.region,
        status="confirmed",
        parent_pathway_id=parent.id,
        node_type=payload.node_type or "branch",
        tree_level=(parent.tree_level or 0) + 1,
        display_order=0,
        # 继承父 Pathway 的 assumptions
        assumptions=parent_assumptions,
        # 概率/风险字段初始化为空，等推理引擎填充
        success_probability={},
        risk_score=None,
        key_risk_factors=[],
        computed_at=None,
        impact_threshold=0.05,
    )
    db.add(new_pathway)
    db.flush()

    # Link parent requirements + risk_factors to the new branch (M2M) so the
    # new branch inherits the parent's eligibility profile.
    now_iso = datetime.now(timezone.utc).isoformat()
    parent_req_ids = {
        r.id for r in db.scalars(
            select(Requirement).join(
                pathway_requirements,
                pathway_requirements.c.requirement_id == Requirement.id,
            ).where(pathway_requirements.c.pathway_id == parent.id)
        )
    }
    if not parent_req_ids:
        # Legacy fallback
        parent_req_ids = {
            r.id for r in db.scalars(
                select(Requirement).where(Requirement.pathway_id == parent.id)
            )
        }
    for req_id in parent_req_ids:
        db.execute(
            pathway_requirements.insert().values(
                pathway_id=new_pathway.id,
                requirement_id=req_id,
                is_blocking=True,
                created_at=now_iso,
            )
        )

    parent_rf_ids = {
        rf.id for rf in db.scalars(
            select(RiskFactor).join(
                pathway_risk_factors,
                pathway_risk_factors.c.risk_factor_id == RiskFactor.id,
            ).where(
                pathway_risk_factors.c.pathway_id == parent.id,
                RiskFactor.deleted_at.is_(None),
                risk_scope_clause(goal.user_id),
            )
        )
    }
    for rf_id in parent_rf_ids:
        db.execute(
            pathway_risk_factors.insert().values(
                pathway_id=new_pathway.id,
                risk_factor_id=rf_id,
                created_at=now_iso,
            )
        )

    db.commit()
    db.refresh(new_pathway)

    log.info(
        "decision_tree.grown",
        parent_pathway_id=parent.id,
        new_pathway_id=new_pathway.id,
        goal_id=goal.id if goal else None,
    )
    return {
        "id": new_pathway.id,
        "name": new_pathway.name,
        "description": new_pathway.description,
        "status": new_pathway.status,
        "node_type": new_pathway.node_type,
        "tree_level": new_pathway.tree_level,
        "parent_pathway_id": new_pathway.parent_pathway_id,
        "scenario_id": new_pathway.scenario_id,
        "region": new_pathway.region,
    }


@router.post("/pathways/{pathway_id}/evolve")
def evolve_branch_endpoint(
    pathway_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Run the LLM+math evolution pipeline on a pathway (the "自生长" endpoint).

    Returns the newly predicted child branches. v0.4.0：分支的 probability
    字段为空（None），后续由推理引擎单独填充。
    """
    from app.core.exceptions import LifeTreeError

    pathway = _get_owned_pathway(pathway_id, user, db)
    service = TreeEvolutionService(db)
    try:
        branches = service.evolve_branch(pathway, user)
    except LifeTreeError:
        raise  # domain errors (e.g. LLMNotConfiguredError) have proper status codes
    except Exception as exc:
        log.error("decision_tree.evolve_failed", pathway_id=pathway_id, error=str(exc))
        raise HTTPException(500, f"Evolution failed: {exc}") from exc
    return {
        "parent_pathway_id": pathway.id,
        "predicted_branches": branches,
        "count": len(branches),
    }


@router.post("/pathways/{pathway_id}/evolve-timeline")
def evolve_timeline_endpoint(
    pathway_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Run the LLM timeline projection on a pathway (the "自演化" endpoint).

    Projects future events over the next 24 months based on the user's
    accumulated data. Results are stored directly on the Pathway
    (success_probability, risk_score, key_risk_factors, computed_at).

    v0.4.0：合并后直接基于 Pathway 工作，不再需要 Scenario 中转。
    """
    from app.core.exceptions import LifeTreeError
    from app.services.evolution import EvolutionService

    pathway = _get_owned_pathway(pathway_id, user, db)
    service = EvolutionService(db)
    try:
        result = service.evolve(pathway, user)
    except LifeTreeError:
        raise
    except Exception as exc:
        log.error("decision_tree.evolve_timeline_failed", pathway_id=pathway_id, error=str(exc))
        raise HTTPException(500, f"Timeline evolution failed: {exc}") from exc
    # EvolutionService.evolve() returns a plain dict[str, Any] (projection +
    # trajectory + feedback). FastAPI serializes it directly.
    return result


@router.get("/pathways/{pathway_id}/evolve-timeline")
def get_timeline_evolution(
    pathway_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> dict[str, Any] | None:
    """Get the cached timeline projection for a pathway.

    Returns the last projection stored on the linked Scenario's
    ``meta["evolution"]`` field (backward compat). Returns null if the
    pathway has no linked Scenario or has never been evolved.

    Note: Pathway itself doesn't have a ``meta`` column yet — the full
    projection (events, trajectory, summary) is cached on the linked
    Scenario. Numerical outputs (success_probability, risk_score, etc.)
    are always available directly on the Pathway.
    """
    pathway = _get_owned_pathway(pathway_id, user, db)

    # Try to read the full projection from a linked Scenario's meta.
    scenario: Scenario | None = None
    if pathway.scenario_id:
        scenario = db.get(Scenario, pathway.scenario_id)
    if scenario is None:
        # Reverse lookup: scenarios.pathway_id → pathway.id
        scenario = db.scalar(
            select(Scenario).where(
                Scenario.pathway_id == pathway.id,
                Scenario.goal_id == pathway.goal_id,
            ).order_by(Scenario.created_at.desc())
        )
    if scenario is None:
        return None

    meta = dict(scenario.meta or {})
    cached = meta.get("evolution")
    if not cached:
        return None
    return {
        "summary": cached.get("summary", ""),
        "projected_events": cached.get("projected_events", []),
        "trajectory": cached.get("trajectory", []),
        "final_probability": cached.get("final_probability", 0.0),
        "confidence": cached.get("confidence", 0.0),
        "evolved_at": cached.get("evolved_at"),
        "horizon_months": 24,
        "cached": True,
    }


@router.post("/pathways/{pathway_id}/confirm")
def confirm_branch(
    pathway_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Change a pathway's status from 'predicted' to 'confirmed'.

    Use this when the user accepts an LLM-predicted branch as a real option.
    """
    pathway = _get_owned_pathway(pathway_id, user, db)
    if pathway.status != "predicted":
        raise HTTPException(
            409,
            f"Pathway is in status '{pathway.status}', can only confirm 'predicted' branches.",
        )
    pathway.status = "confirmed"
    db.add(pathway)
    db.commit()
    db.refresh(pathway)
    log.info("decision_tree.confirmed", pathway_id=pathway.id)
    return {
        "id": pathway.id,
        "name": pathway.name,
        "status": pathway.status,
        "node_type": pathway.node_type,
        "tree_level": pathway.tree_level,
    }


@router.post("/pathways/{pathway_id}/select")
def select_branch(
    pathway_id: str,
    payload: SelectBranchRequest,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Mark a branch as 'in_progress' (user is actively executing this path).

    Optionally abandon sibling branches at the same tree_level so the user's
    focus is clear.
    """
    pathway = _get_owned_pathway(pathway_id, user, db)
    if pathway.status not in ("confirmed", "predicted", "selected", "candidate"):
        raise HTTPException(
            409,
            f"Pathway is in status '{pathway.status}', cannot select.",
        )

    pathway.status = "in_progress"
    db.add(pathway)

    abandoned_siblings: list[str] = []
    if payload.abandon_siblings and pathway.parent_pathway_id:
        siblings = list(
            db.scalars(
                select(Pathway).where(
                    Pathway.parent_pathway_id == pathway.parent_pathway_id,
                    Pathway.id != pathway.id,
                    Pathway.status.in_(
                        ["predicted", "confirmed", "candidate", "selected"]
                    ),
                )
            )
        )
        for sib in siblings:
            sib.status = "abandoned"
            db.add(sib)
            abandoned_siblings.append(sib.id)

    db.commit()
    db.refresh(pathway)
    log.info(
        "decision_tree.selected",
        pathway_id=pathway.id,
        abandoned_siblings=abandoned_siblings,
    )
    return {
        "id": pathway.id,
        "name": pathway.name,
        "status": pathway.status,
        "node_type": pathway.node_type,
        "tree_level": pathway.tree_level,
        "abandoned_siblings": abandoned_siblings,
    }


@router.post("/pathways/{pathway_id}/abandon")
def abandon_branch(
    pathway_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Mark a branch as 'abandoned'."""
    pathway = _get_owned_pathway(pathway_id, user, db)
    pathway.status = "abandoned"
    db.add(pathway)
    db.commit()
    db.refresh(pathway)
    log.info("decision_tree.abandoned", pathway_id=pathway.id)
    return {
        "id": pathway.id,
        "name": pathway.name,
        "status": pathway.status,
        "node_type": pathway.node_type,
        "tree_level": pathway.tree_level,
    }


@router.post("/pathways/{pathway_id}/requirements")
def link_requirement(
    pathway_id: str,
    payload: LinkRequirementRequest,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Link a requirement to a pathway (M2M)."""
    pathway = _get_owned_pathway(pathway_id, user, db)
    req = db.get(Requirement, payload.requirement_id)
    if req is None:
        raise HTTPException(404, "Requirement not found")
    # Soft ownership check: requirement must belong to a pathway under a goal
    # the user owns (or be unlinked/legacy).
    if req.pathway_id:
        owner_pathway = db.get(Pathway, req.pathway_id)
        if owner_pathway is not None:
            owner_goal = db.get(Goal, owner_pathway.goal_id)
            if owner_goal is None or (
                owner_goal.user_id != user.id and user.role != "admin"
            ):
                raise HTTPException(403, "You do not have access to this requirement")

    # Idempotent: if the link already exists, just update is_blocking.
    existing = db.execute(
        select(pathway_requirements).where(
            pathway_requirements.c.pathway_id == pathway.id,
            pathway_requirements.c.requirement_id == req.id,
        )
    ).first()
    if existing:
        db.execute(
            pathway_requirements.update()
            .where(
                pathway_requirements.c.pathway_id == pathway.id,
                pathway_requirements.c.requirement_id == req.id,
            )
            .values(is_blocking=payload.is_blocking)
        )
    else:
        db.execute(
            pathway_requirements.insert().values(
                pathway_id=pathway.id,
                requirement_id=req.id,
                is_blocking=payload.is_blocking,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        )
    db.commit()
    return {
        "ok": True,
        "pathway_id": pathway.id,
        "requirement_id": req.id,
        "is_blocking": payload.is_blocking,
    }


@router.post("/pathways/{pathway_id}/risk-factors")
def link_risk_factor(
    pathway_id: str,
    payload: LinkRiskFactorRequest,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Link a risk factor to a pathway (M2M)."""
    pathway = _get_owned_pathway(pathway_id, user, db)
    goal = db.get(Goal, pathway.goal_id)
    if goal is None:
        raise HTTPException(404, "Goal not found")
    rf = get_visible_risk(db, payload.risk_factor_id, goal.user_id)

    # Idempotent: skip if already linked.
    existing = db.execute(
        select(pathway_risk_factors).where(
            pathway_risk_factors.c.pathway_id == pathway.id,
            pathway_risk_factors.c.risk_factor_id == rf.id,
        )
    ).first()
    if not existing:
        db.execute(
            pathway_risk_factors.insert().values(
                pathway_id=pathway.id,
                risk_factor_id=rf.id,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        )
        db.commit()
    return {
        "ok": True,
        "pathway_id": pathway.id,
        "risk_factor_id": rf.id,
    }


@router.delete("/pathways/{pathway_id}/requirements/{requirement_id}")
def unlink_requirement(
    pathway_id: str,
    requirement_id: str,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Unlink a requirement from a pathway (M2M)."""
    pathway = _get_owned_pathway(pathway_id, user, db)
    db.execute(
        pathway_requirements.delete().where(
            pathway_requirements.c.pathway_id == pathway.id,
            pathway_requirements.c.requirement_id == requirement_id,
        )
    )
    db.commit()
    return {"ok": True, "pathway_id": pathway.id, "requirement_id": requirement_id}


@router.delete("/pathways/{pathway_id}/risk-factors/{risk_factor_id}")
def unlink_risk_factor(
    pathway_id: str,
    risk_factor_id: str,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Unlink a risk factor from a pathway (M2M)."""
    pathway = _get_owned_pathway(pathway_id, user, db)
    db.execute(
        pathway_risk_factors.delete().where(
            pathway_risk_factors.c.pathway_id == pathway.id,
            pathway_risk_factors.c.risk_factor_id == risk_factor_id,
        )
    )
    db.commit()
    return {"ok": True, "pathway_id": pathway.id, "risk_factor_id": risk_factor_id}
