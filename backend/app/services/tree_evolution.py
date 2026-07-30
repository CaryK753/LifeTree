"""Self-growing decision-tree evolution service (§11.3).

Implements the "LLM diverge → math model converge" pipeline that powers
``POST /pathways/{pathway_id}/evolve``:

1. **LLM DIVERGE** — given a pathway + its goal/requirements/risk_factors/
   user profile/memories/recent events, the chat-role LLM proposes 2-5
   alternative child branches. Structured output is enforced via
   ``instructor`` + the :class:`BranchProposal` Pydantic schema (mirrors
   the pattern in :mod:`app.services.evolution`).

2. **MATH MODEL CONVERGE** — for each proposed branch:
   a. A ``Pathway`` row with ``status='predicted'``, ``node_type='branch'``,
      ``tree_level = parent.tree_level + 1``, ``evolution_hint = rationale``
      is created. The child Pathway directly inherits the parent Pathway's
      ``assumptions`` (v0.4.0：不再创建子 Scenario)。
   b. Parent requirements / risk_factors are linked to the new pathway via
      the ``pathway_requirements`` / ``pathway_risk_factors`` M2M tables.
      LLM-proposed new requirements / risks are also created and linked.
   c. ``success_probability`` / ``risk_score`` / ``key_risk_factors`` /
      ``computed_at`` 初始化为空，等待推理引擎后续单独填充。
   d. （已移除）不再 inline 调用 ScenarioService.run_reasoning，因为没有
      子 Scenario 可供推理。剪枝逻辑（P50 < 5% 删除）也随之移除 ——
      推理引擎后续会单独填充概率字段，那时再做剪枝。

3. Surviving branches are returned with empty probability data (to be
   filled by the reasoning engine later).

Only ONE level deep is predicted. The user must confirm a branch before
further evolution from it.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, ExternalServiceError, LLMNotConfiguredError
from app.core.logging import get_logger
from app.core.tenant import CurrentUser
from app.db.postgres import SessionLocal
from app.llm.client import get_instructor_sync
from app.models.event import Event
from app.models.goal import (
    Goal,
    Pathway,
    PathwayStatus,
    Requirement,
    RiskFactor,
    pathway_requirements,
    pathway_risk_factors,
)
from app.models.memory import UserMemory
# 保留 Scenario 导入：向后兼容时反查父 Pathway 关联的 Scenario 取 assumptions
from app.models.scenario import Scenario
from app.models.user import UserProfile
from app.services.risk_adoption import get_or_create_user_risk
from app.services.risk_scope import risk_scope_clause
from app.services.tree_evolution_contracts import (
    BranchProposal,
    CompactBranchProposal,
    ProposedBranch,
    branch_identity_key,
)

log = get_logger(__name__)


# ---------------- Service ----------------


class TreeEvolutionService:
    """LLM diverge → math model converge pipeline for the self-growing tree."""

    # P50 below this threshold → branch is unviable, delete it.
    MIN_VIABLE_P50 = 0.05

    MAX_MEMORIES = 10
    MAX_EVENTS = 8
    MAX_REQUIREMENTS = 12
    MAX_RISK_FACTORS = 8

    def __init__(self, db: Session) -> None:
        self.db = db

    def evolve_branch(self, pathway: Pathway, user: CurrentUser) -> list[dict[str, Any]]:
        """Generate 2-5 candidate child branches for ``pathway``.

        Returns the surviving branches (post P50 filter) with their
        probability data and linked requirement / risk factor ids.
        """
        if pathway.status in {
            PathwayStatus.PREDICTED.value,
            PathwayStatus.ABANDONED.value,
            PathwayStatus.REJECTED.value,
            PathwayStatus.SUPERSEDED.value,
        }:
            raise ConflictError(
                "Only active or confirmed branches can evolve. Confirm predicted branches first."
            )

        t0 = time.perf_counter()
        goal = self.db.get(Goal, pathway.goal_id)
        if goal is None:
            raise RuntimeError(f"pathway {pathway.id} has no parent goal")

        # ---------- 1. LLM DIVERGE ----------
        context = self._build_context(pathway, goal, user)
        proposal = self._propose_branches(pathway, goal, context)

        # ---------- 2. MATH MODEL CONVERGE ----------
        surviving: list[dict[str, Any]] = []
        existing_keys = {branch_identity_key(child.name) for child in context["existing_children"]}
        for idx, branch in enumerate(proposal.branches[:5]):
            identity_key = branch_identity_key(branch.branch_name)
            if not identity_key or identity_key in existing_keys:
                log.info(
                    "tree_evolution.duplicate_branch_skipped",
                    pathway_id=pathway.id,
                    branch_name=branch.branch_name,
                )
                continue
            existing_keys.add(identity_key)
            try:
                result = self._instantiate_and_score(
                    branch=branch,
                    parent=pathway,
                    goal=goal,
                    user=user,
                    display_order=idx,
                )
                if result is None:
                    continue  # filtered out (P50 too low) or instantiate failed
                surviving.append(result)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "tree_evolution.branch_failed",
                    pathway_id=pathway.id,
                    branch_name=branch.branch_name,
                    error=str(exc),
                )
                continue

        log.info(
            "tree_evolution.completed",
            pathway_id=pathway.id,
            proposed=len(proposal.branches),
            surviving=len(surviving),
            ms=int((time.perf_counter() - t0) * 1000),
        )
        return surviving

    # ---------------- Context loading ----------------

    def _build_context(
        self,
        pathway: Pathway,
        goal: Goal,
        user: CurrentUser,
    ) -> dict[str, Any]:
        """Load all long-term accumulated data that informs the proposal."""
        # §11.3: requirements via M2M with legacy fallback
        requirements = list(
            self.db.scalars(
                select(Requirement)
                .join(
                    pathway_requirements,
                    pathway_requirements.c.requirement_id == Requirement.id,
                )
                .where(pathway_requirements.c.pathway_id == pathway.id)
                .order_by(Requirement.weight.desc())
                .limit(self.MAX_REQUIREMENTS)
            )
        )
        if not requirements:
            requirements = list(
                self.db.scalars(
                    select(Requirement)
                    .where(Requirement.pathway_id == pathway.id)
                    .order_by(Requirement.weight.desc())
                    .limit(self.MAX_REQUIREMENTS)
                )
            )

        risk_factors = list(
            self.db.scalars(
                select(RiskFactor)
                .join(
                    pathway_risk_factors,
                    pathway_risk_factors.c.risk_factor_id == RiskFactor.id,
                )
                .where(pathway_risk_factors.c.pathway_id == pathway.id)
                .where(
                    RiskFactor.deleted_at.is_(None),
                    risk_scope_clause(goal.user_id),
                )
                .order_by(RiskFactor.level.desc())
                .limit(self.MAX_RISK_FACTORS)
            )
        )

        profile = self.db.get(UserProfile, user.id)
        memories = list(
            self.db.scalars(
                select(UserMemory)
                .where(UserMemory.user_id == user.id)
                .order_by(UserMemory.importance.desc())
                .limit(self.MAX_MEMORIES)
            )
        )
        recent_events = list(
            self.db.scalars(
                select(Event)
                .where(Event.user_id == user.id)
                .order_by(Event.created_at.desc())
                .limit(self.MAX_EVENTS)
            )
        )

        # Resolve chat model name (instructor needs it explicitly)
        from app.llm.client import get_chat_model

        try:
            model_name = get_chat_model().model.name
        except LLMNotConfiguredError:
            model_name = "gpt-4o-mini"  # instructor will raise anyway

        # Existing child branches — tell the LLM what's already on the tree
        # so it doesn't propose duplicates.
        existing_children = list(
            self.db.scalars(
                select(Pathway)
                .where(
                    Pathway.parent_pathway_id == pathway.id,
                    Pathway.deleted_at.is_(None),
                )
                .order_by(Pathway.created_at.asc())
            )
        )

        return {
            "goal": goal,
            "pathway": pathway,
            "requirements": requirements,
            "risk_factors": risk_factors,
            "profile": profile,
            "memories": memories,
            "recent_events": recent_events,
            "existing_children": existing_children,
            "model_name": model_name,
            "summary": self._summarize_context(
                goal,
                pathway,
                requirements,
                risk_factors,
                profile,
                memories,
                recent_events,
                existing_children,
            ),
        }

    @staticmethod
    def _summarize_context(
        goal: Goal,
        pathway: Pathway,
        requirements: list[Requirement],
        risk_factors: list[RiskFactor],
        profile: UserProfile | None,
        memories: list[UserMemory],
        recent_events: list[Event],
        existing_children: list[Pathway],
    ) -> str:
        parts: list[str] = []
        parts.append(f"Goal: {goal.title}")
        if goal.description:
            parts.append(f"Goal description: {goal.description[:200]}")
        parts.append(
            f"Current pathway: {pathway.name} "
            f"(region={pathway.region or 'global'}, level={pathway.tree_level})"
        )
        if pathway.decision_question:
            parts.append(f"Decision question: {pathway.decision_question}")
        if requirements:
            req_lines = [
                f"  - {r.name} [{r.gap_status}] (weight={r.weight:.1f})" for r in requirements[:8]
            ]
            parts.append("Top requirements:\n" + "\n".join(req_lines))
        if risk_factors:
            rf_lines = [f"  - {rf.name} [{rf.level}] (type={rf.type})" for rf in risk_factors[:6]]
            parts.append("Key risk factors:\n" + "\n".join(rf_lines))
        if profile:
            parts.append(f"User: {profile.display_name}, risk_tolerance={profile.risk_tolerance}")
            if profile.demographics:
                parts.append(f"Demographics: {dict(profile.demographics)}")
        if memories:
            mem_lines = [f"  - [{m.category}] {m.content}" for m in memories[:8]]
            parts.append("Long-term memories:\n" + "\n".join(mem_lines))
        if recent_events:
            ev_lines = [
                f"  - {e.subject} {e.action}" + (f" {e.object}" if e.object else "")
                for e in recent_events[:5]
            ]
            parts.append("Recent events:\n" + "\n".join(ev_lines))
        if existing_children:
            child_lines = [f"  - {c.name} [{c.status}]" for c in existing_children[:8]]
            parts.append("Already-explored child branches:\n" + "\n".join(child_lines))
        return "\n".join(parts)

    # ---------------- LLM proposal ----------------

    def _propose_branches(
        self,
        pathway: Pathway,
        goal: Goal,
        context: dict[str, Any],
    ) -> BranchProposal:
        """Call the LLM via instructor to get a structured branch proposal."""
        try:
            instructor = get_instructor_sync()
        except LLMNotConfiguredError:
            raise  # propagate as 503 to the client

        prompt_messages = self._build_prompt(pathway, goal, context)
        try:
            proposal: BranchProposal = instructor.chat.completions.create(
                model=context["model_name"],
                messages=prompt_messages,
                response_model=BranchProposal,
                temperature=0.6,
                max_tokens=4000,
                max_retries=2,
            )
        except Exception as primary_exc:
            log.warning(
                "tree_evolution.structured_output_retry",
                pathway_id=pathway.id,
                error=str(primary_exc)[:300],
            )
            fallback_messages = [
                *prompt_messages,
                {
                    "role": "user",
                    "content": (
                        "Retry with 1-3 concise branches. Return only branch_name, "
                        "branch_description, region, and rationale; omit requirements and risks."
                    ),
                },
            ]
            try:
                compact: CompactBranchProposal = instructor.chat.completions.create(
                    model=context["model_name"],
                    messages=fallback_messages,
                    response_model=CompactBranchProposal,
                    temperature=0.4,
                    max_tokens=1600,
                    max_retries=1,
                )
                proposal = compact.expand()
            except Exception as fallback_exc:
                raise ExternalServiceError(
                    "The model returned an invalid branch proposal after retrying.",
                    details={
                        "primary_error": str(primary_exc)[:300],
                        "fallback_error": str(fallback_exc)[:300],
                    },
                ) from fallback_exc
        return proposal

    def _build_prompt(
        self, pathway: Pathway, goal: Goal, context: dict[str, Any]
    ) -> list[dict[str, str]]:
        system = (
            "You are a strategic foresight assistant inside LifeTree, a long-horizon "
            "decision intelligence system. Your task is to GROW the user's decision "
            "tree by proposing 2-5 alternative child branches for a given pathway.\n\n"
            "DIVERGE broadly: think about distinct routes the user could take from "
            "this decision point. Each branch should represent a meaningfully "
            "different approach, not a minor variation.\n\n"
            "You MUST respond with a single valid JSON object conforming EXACTLY to "
            "this schema (no markdown fences, no commentary, no prose outside the JSON):\n"
            "{\n"
            '  "branches": [\n'
            "    {\n"
            '      "branch_name": "<string, max 200 chars>",\n'
            '      "branch_description": "<1-2 sentence string>",\n'
            '      "region": "<region tag e.g. CA, UK, SG, or empty string>",\n'
            '      "rationale": "<why this route makes sense>",\n'
            '      "key_requirements": [\n'
            "        {\n"
            '          "name": "<requirement name>",\n'
            '          "type": "<one of: language | financial | education | experience | health | legal | other>",\n'
            '          "threshold": {"<key>": "<value>"},\n'
            '          "gap_status": "<one of: met | partial | unmet | unknown>",\n'
            '          "weight": <float 0.05-2.0>\n'
            "        }\n"
            "      ],\n"
            '      "key_risks": [\n'
            "        {\n"
            '          "name": "<risk name>",\n'
            '          "type": "<one of: policy | economic | security | political | health | operational | other>",\n'
            '          "level": "<one of: low | medium | high>",\n'
            '          "probability": <float 0-1>,\n'
            '          "impact": <float 0-1>\n'
            "        }\n"
            "      ]\n"
            "    }\n"
            "  ]\n"
            "}\n\n"
            "Field requirements:\n"
            "- branches: array of 1-8 proposed branches (aim for 2-5 distinct routes).\n"
            "  - branch_name: short, distinctive name, max 200 chars.\n"
            "  - branch_description: 1-2 sentence description of what this route entails.\n"
            "  - region: region tag if applicable (e.g. 'CA', 'UK', 'SG'), or empty string.\n"
            "  - rationale: why this route makes sense given the user's context.\n"
            "  - key_requirements: critical eligibility criteria specific to this route.\n"
            "    - name: requirement name.\n"
            "    - type: one of language/financial/education/experience/health/legal/other.\n"
            "    - threshold: object mapping key to value (e.g. {\"score\": 67}).\n"
            "    - gap_status: one of met/partial/unmet/unknown — estimate from the "
            "user's current evidence.\n"
            "    - weight: float 0.05-2.0 indicating relative importance.\n"
            "  - key_risks: risks specific to this route (not the parent pathway).\n"
            "    - name: risk name.\n"
            "    - type: one of policy/economic/security/political/health/operational/other.\n"
            "    - level: one of low/medium/high.\n"
            "    - probability: evidence-based float 0-1.\n"
            "    - impact: evidence-based float 0-1.\n\n"
            "Output rules:\n"
            "- Return ONLY the JSON object. No markdown, no code fences, no prefix/suffix text.\n"
            "- All keys must be present. Use empty arrays for key_requirements / "
            "key_risks when none apply.\n"
            "- Do not invent fields beyond the schema above.\n\n"
            "Guidelines:\n"
            "- Ground proposals in the user's actual goal, requirements, risks, "
            "memories, and recent events.\n"
            "- Don't propose branches that already exist as children of this pathway.\n"
            "- Each branch must be a plausible path toward the goal, not a dead end.\n"
            "- Vary branches by region, approach, or constraint trade-offs.\n"
            "- 2-5 branches total — favor quality over quantity."
        )
        user_msg = (
            f"Goal: {goal.title}\n"
            f"Pathway to evolve: {pathway.name}\n"
            f"Pathway description: {pathway.description or 'N/A'}\n\n"
            f"Context:\n{context['summary']}\n\n"
            f"Propose 2-5 alternative child branches for this pathway. "
            f"Respond with only the JSON object described in the system prompt."
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ]

    # ---------------- Branch instantiation + scoring ----------------

    def _resolve_linked_scenario(self, pathway: Pathway) -> Scenario | None:
        """查找 Pathway 关联的 Scenario（向后兼容用）。

        当父 Pathway 上没有 assumptions 时，回退到关联 Scenario 的 assumptions。
        优先用 ``pathway.scenario_id``；找不到则按 ``scenarios.pathway_id`` 反查。
        """
        if pathway.scenario_id:
            sc = self.db.get(Scenario, pathway.scenario_id)
            if sc is not None and sc.goal_id == pathway.goal_id:
                return sc
        sc = self.db.scalar(
            select(Scenario)
            .where(
                Scenario.pathway_id == pathway.id,
                Scenario.goal_id == pathway.goal_id,
            )
            .order_by(Scenario.created_at.desc())
        )
        return sc

    def _instantiate_and_score(
        self,
        *,
        branch: ProposedBranch,
        parent: Pathway,
        goal: Goal,
        user: CurrentUser,
        display_order: int,
    ) -> dict[str, Any] | None:
        """为提议的分支创建子 Pathway（v0.4.0：不再创建子 Scenario）。

        - 子 Pathway 直接继承父 Pathway 的 ``assumptions``（向后兼容：父
          Pathway 没有 assumptions 时回退到关联 Scenario 的 assumptions）。
        - ``success_probability`` / ``risk_score`` / ``key_risk_factors`` /
          ``computed_at`` 初始化为空，等待推理引擎后续单独填充。
        - 不再 inline 调用 ``ScenarioService.run_reasoning``，因此也不再
          做 P50 < 5% 的剪枝（推理引擎后续填充概率时再做）。
        """
        now_iso = datetime.now(timezone.utc).isoformat()

        # 解析父 Pathway 的 assumptions（向后兼容：回退到关联 Scenario）
        parent_assumptions = dict(parent.assumptions or {})
        if not parent_assumptions:
            parent_sc = self._resolve_linked_scenario(parent)
            if parent_sc is not None:
                parent_assumptions = dict(parent_sc.assumptions or {})

        # a. 创建子 Pathway，继承父 Pathway 的 assumptions，概率/风险字段留空
        new_pathway = Pathway(
            id=str(uuid.uuid4()),
            goal_id=goal.id,
            name=branch.branch_name,
            description=branch.branch_description,
            status="predicted",
            region=branch.region or parent.region,
            parent_pathway_id=parent.id,
            node_type="branch",
            tree_level=(parent.tree_level or 0) + 1,
            display_order=display_order,
            evolution_hint=branch.rationale,
            # 继承父 Pathway 的 assumptions，并标记演化来源
            assumptions={
                **parent_assumptions,
                "evolved_from": parent.id,
                "rationale": branch.rationale,
            },
            # 概率/风险字段初始化为空，等待推理引擎填充
            success_probability={},
            risk_score=None,
            key_risk_factors=[],
            computed_at=None,
            impact_threshold=self.MIN_VIABLE_P50,
        )
        self.db.add(new_pathway)
        self.db.flush()

        # b. Link parent requirements + risk_factors to the new pathway (M2M).
        # The new branch inherits everything its parent had, plus the
        # branch-specific items the LLM proposed below.
        parent_req_ids = {
            r.id
            for r in self.db.scalars(
                select(Requirement)
                .join(
                    pathway_requirements,
                    pathway_requirements.c.requirement_id == Requirement.id,
                )
                .where(pathway_requirements.c.pathway_id == parent.id)
            )
        }
        # Legacy fallback
        if not parent_req_ids:
            parent_req_ids = {
                r.id
                for r in self.db.scalars(
                    select(Requirement).where(Requirement.pathway_id == parent.id)
                )
            }
        for req_id in parent_req_ids:
            self.db.execute(
                pathway_requirements.insert().values(
                    pathway_id=new_pathway.id,
                    requirement_id=req_id,
                    is_blocking=True,
                    created_at=now_iso,
                )
            )

        parent_rf_ids = {
            rf.id
            for rf in self.db.scalars(
                select(RiskFactor)
                .join(
                    pathway_risk_factors,
                    pathway_risk_factors.c.risk_factor_id == RiskFactor.id,
                )
                .where(
                    pathway_risk_factors.c.pathway_id == parent.id,
                    RiskFactor.deleted_at.is_(None),
                    risk_scope_clause(goal.user_id),
                )
            )
        }
        for rf_id in parent_rf_ids:
            self.db.execute(
                pathway_risk_factors.insert().values(
                    pathway_id=new_pathway.id,
                    risk_factor_id=rf_id,
                    created_at=now_iso,
                )
            )

        # Create the LLM-proposed branch-specific requirements / risks and
        # link them too. We create them as fresh rows so they don't pollute
        # the parent pathway's risk set.
        for req in branch.key_requirements:
            r = Requirement(
                id=str(uuid.uuid4()),
                pathway_id=new_pathway.id,  # legacy column for back-compat
                name=req.name,
                type=req.type,
                threshold=req.threshold or {},
                current_value={},
                gap_status=req.gap_status,
                weight=req.weight,
            )
            self.db.add(r)
            self.db.flush()
            self.db.execute(
                pathway_requirements.insert().values(
                    pathway_id=new_pathway.id,
                    requirement_id=r.id,
                    is_blocking=True,
                    created_at=now_iso,
                )
            )

        linked_risk_ids = set(parent_rf_ids)
        for risk in branch.key_risks:
            rf, _ = get_or_create_user_risk(
                self.db,
                user_id=goal.user_id,
                name=risk.name,
                risk_type=risk.type,
                region=branch.region or parent.region,
                values={
                    "level": risk.level,
                    "urgency": "normal",
                    "probability": risk.probability,
                    "impact": risk.impact,
                },
            )
            if rf.id in linked_risk_ids:
                continue
            self.db.execute(
                pathway_risk_factors.insert().values(
                    pathway_id=new_pathway.id,
                    risk_factor_id=rf.id,
                    created_at=now_iso,
                )
            )
            linked_risk_ids.add(rf.id)

        self.db.commit()

        # c. （v0.4.0 已移除）不再 inline 调用 ScenarioService.run_reasoning ——
        # 没有子 Scenario 可供推理。success_probability 等字段保持为空，
        # 后续由推理引擎单独填充。剪枝逻辑（P50 < 5% 删除）也一并移除。

        # d. 返回新建分支（probability 字段为空，等推理引擎填充）
        return {
            "pathway_id": new_pathway.id,
            "name": new_pathway.name,
            "description": new_pathway.description,
            "region": new_pathway.region,
            "parent_pathway_id": new_pathway.parent_pathway_id,
            "tree_level": new_pathway.tree_level,
            "display_order": new_pathway.display_order,
            "evolution_hint": new_pathway.evolution_hint,
            "status": new_pathway.status,
            "node_type": new_pathway.node_type,
            "scenario_id": new_pathway.scenario_id,
            "probability": {
                "p50": None,
                "p10": None,
                "p90": None,
            },
            "key_risk_factors": [],
            "run_error": None,
        }


def evolve_branch_async(pathway_id: str, user_id: str) -> list[dict[str, Any]]:
    """Standalone entry point for non-request-scoped callers (e.g. Celery).

    Opens its own DB session and resolves the user from ``user_id``.
    """
    with SessionLocal() as db:
        pathway = db.get(Pathway, pathway_id)
        if pathway is None:
            raise RuntimeError(f"Pathway {pathway_id} not found")
        # Minimal CurrentUser-like object — only .id is needed for scoping.
        user = type("U", (), {"id": user_id, "role": "user"})()
        return TreeEvolutionService(db).evolve_branch(pathway, user)
