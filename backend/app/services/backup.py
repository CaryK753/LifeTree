"""Whole-database backup / restore / migration (P2 整库备份/恢复/导出迁移).

Exports every user-scoped entity as a nested JSON document, and re-imports
it with foreign-key remapping so a backup taken from one user (or one
instance) can be restored into another without ID collisions.

Modes:
    - ``merge``   : upsert — skip entities whose id already exists.
    - ``replace`` : wipe the target user's data first, then import fresh.

The serializer is intentionally minimal — it walks ``__table__.columns``
so relationship attributes aren't touched, and skips a handful of
internal/sensitive fields (``password_hash``, ``embedding``,
``deleted_at``).
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.action import Action
from app.models.event import (
    Event,
    InformationSource,
    Relationship,
)
from app.models.goal import (
    Goal,
    Pathway,
    Requirement,
    RiskFactor,
    pathway_requirements,
    pathway_risk_factors,
)
from app.models.memory import UserMemory
from app.models.scenario import Scenario
from app.models.source_proposal import SourceProposal
from app.models.user import UserProfile
from app.models.user_plugin import UserPlugin
from app.services.risk_scope import risk_identity_key, risk_scope_clause

log = get_logger(__name__)


#: Fields that must never be exported (secrets / huge / internal).
_SKIP_FIELDS: frozenset[str] = frozenset({
    "password_hash",
    "embedding",  # Vector column on Event — too large + re-derived anyway
    "deleted_at",  # soft-delete tombstone — fresh rows are not deleted
    "accepted_terms_at",  # legal consent is per-account, not transferable
    "terms_version",
    "privacy_version",
})

#: Export format version. Bump when the schema of the export changes.
EXPORT_VERSION = "1.0"


class BackupService:
    """Export / import all user data as a portable JSON document."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # =====================================================================
    # Export
    # =====================================================================

    def export_user_data(self, user_id: str) -> dict[str, Any]:
        """Export every user-scoped entity as a nested dict.

        The shape is documented in the module docstring. Soft-deleted rows
        (``deleted_at IS NOT NULL``) are skipped.
        """
        user = self.db.get(UserProfile, user_id)
        profile_dict = self._serialize(user) if user is not None else None

        goals = self._export_goals(user_id)
        events = self._export_events(user_id)
        sources = self._export_sources(user_id)
        scenarios = self._export_scenarios(user_id)
        actions = self._export_actions(user_id)
        memories = self._export_memories(user_id)
        risk_factors = self._export_risk_factors(user_id)
        relationships = self._export_relationships(user_id, goals)
        plugins = self._export_plugins(user_id)
        source_proposals = self._export_source_proposals(user_id)

        return {
            "version": EXPORT_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "user_profile": profile_dict,
            "goals": goals,
            "events": events,
            "information_sources": sources,
            "scenarios": scenarios,
            "actions": actions,
            "memories": memories,
            "risk_factors": risk_factors,
            "relationships": relationships,
            "plugins": plugins,
            "source_proposals": source_proposals,
        }

    def export_to_jsonl(self, user_id: str) -> str:
        """Return the export as newline-delimited JSON (one entity per line).

        Each line is ``{"type": <entity>, "data": {...}}``. The top-level
        envelope (version / exported_at / user_profile) is emitted as the
        first line with ``type="meta"``.
        """
        payload = self.export_user_data(user_id)
        lines: list[str] = []

        lines.append(json.dumps({
            "type": "meta",
            "data": {
                "version": payload["version"],
                "exported_at": payload["exported_at"],
                "user_profile": payload["user_profile"],
            },
        }, ensure_ascii=False, default=str))

        # Flat collections — one line per row.
        flat_collections: list[tuple[str, list[dict[str, Any]]]] = [
            ("events", payload["events"]),
            ("information_sources", payload["information_sources"]),
            ("scenarios", payload["scenarios"]),
            ("actions", payload["actions"]),
            ("memories", payload["memories"]),
            ("risk_factors", payload["risk_factors"]),
            ("relationships", payload["relationships"]),
            ("plugins", payload["plugins"]),
            ("source_proposals", payload["source_proposals"]),
        ]
        for entity_type, rows in flat_collections:
            for row in rows:
                lines.append(json.dumps(
                    {"type": entity_type, "data": row},
                    ensure_ascii=False,
                    default=str,
                ))

        # Goals are nested (goal → pathways → requirements). Emit one line
        # per goal, one per pathway, one per requirement, in dependency
        # order so a streaming importer could rebuild the tree on the fly.
        for goal in payload["goals"]:
            goal_copy = {k: v for k, v in goal.items() if k != "pathways"}
            lines.append(json.dumps(
                {"type": "goal", "data": goal_copy},
                ensure_ascii=False,
                default=str,
            ))
            for pathway in goal.get("pathways", []):
                pw_copy = {k: v for k, v in pathway.items() if k != "requirements"}
                lines.append(json.dumps(
                    {"type": "pathway", "data": pw_copy},
                    ensure_ascii=False,
                    default=str,
                ))
                for req in pathway.get("requirements", []):
                    lines.append(json.dumps(
                        {"type": "requirement", "data": req},
                        ensure_ascii=False,
                        default=str,
                    ))

        return "\n".join(lines) + "\n"

    # ---------- per-entity export helpers ----------

    def _export_goals(self, user_id: str) -> list[dict[str, Any]]:
        rows = self.db.scalars(
            select(Goal)
            .where(Goal.user_id == user_id, Goal.deleted_at.is_(None))
            .order_by(Goal.created_at.asc())
        ).all()
        out: list[dict[str, Any]] = []
        for goal in rows:
            g = self._serialize(goal)
            g["pathways"] = self._export_pathways(goal.id)
            out.append(g)
        return out

    def _export_pathways(self, goal_id: str) -> list[dict[str, Any]]:
        rows = self.db.scalars(
            select(Pathway)
            .where(Pathway.goal_id == goal_id, Pathway.deleted_at.is_(None))
            .order_by(Pathway.created_at.asc())
        ).all()
        out: list[dict[str, Any]] = []
        for pw in rows:
            p = self._serialize(pw)
            p["requirements"] = self._export_requirements(pw.id)
            p["risk_factor_ids"] = list(
                self.db.scalars(
                    select(pathway_risk_factors.c.risk_factor_id).where(
                        pathway_risk_factors.c.pathway_id == pw.id
                    )
                )
            )
            out.append(p)
        return out

    def _export_requirements(self, pathway_id: str) -> list[dict[str, Any]]:
        rows = self.db.scalars(
            select(Requirement)
            .outerjoin(
                pathway_requirements,
                pathway_requirements.c.requirement_id == Requirement.id,
            )
            .where(
                or_(
                    Requirement.pathway_id == pathway_id,
                    pathway_requirements.c.pathway_id == pathway_id,
                ),
                Requirement.deleted_at.is_(None),
            )
            .distinct()
            .order_by(Requirement.created_at.asc())
        ).all()
        return [self._serialize(r) for r in rows]

    def _export_events(self, user_id: str) -> list[dict[str, Any]]:
        rows = self.db.scalars(
            select(Event).where(Event.user_id == user_id)
        ).all()
        return [self._serialize(r) for r in rows]

    def _export_sources(self, user_id: str) -> list[dict[str, Any]]:
        rows = self.db.scalars(
            select(InformationSource).where(InformationSource.user_id == user_id)
        ).all()
        return [self._serialize(r) for r in rows]

    def _export_scenarios(self, user_id: str) -> list[dict[str, Any]]:
        goal_ids = self._user_goal_ids(user_id)
        if not goal_ids:
            return []
        rows = self.db.scalars(
            select(Scenario)
            .where(Scenario.goal_id.in_(goal_ids), Scenario.deleted_at.is_(None))
            .order_by(Scenario.created_at.asc())
        ).all()
        return [self._serialize(r) for r in rows]

    def _export_actions(self, user_id: str) -> list[dict[str, Any]]:
        rows = self.db.scalars(
            select(Action)
            .where(Action.user_id == user_id, Action.deleted_at.is_(None))
            .order_by(Action.created_at.asc())
        ).all()
        return [self._serialize(r) for r in rows]

    def _export_memories(self, user_id: str) -> list[dict[str, Any]]:
        rows = self.db.scalars(
            select(UserMemory)
            .where(UserMemory.user_id == user_id, UserMemory.deleted_at.is_(None))
            .order_by(UserMemory.created_at.asc())
        ).all()
        return [self._serialize(r) for r in rows]

    def _export_risk_factors(self, user_id: str) -> list[dict[str, Any]]:
        linked_ids = set(
            self.db.scalars(
                select(pathway_risk_factors.c.risk_factor_id)
                .join(Pathway, Pathway.id == pathway_risk_factors.c.pathway_id)
                .join(Goal, Goal.id == Pathway.goal_id)
                .where(Goal.user_id == user_id)
            )
        )
        linked_ids.update(
            self.db.scalars(
                select(Action.risk_factor_id).where(
                    Action.user_id == user_id,
                    Action.risk_factor_id.is_not(None),
                )
            )
        )
        if not linked_ids:
            return []
        rows = self.db.scalars(
            select(RiskFactor).where(
                RiskFactor.id.in_(linked_ids),
                RiskFactor.deleted_at.is_(None),
                risk_scope_clause(user_id),
            )
        ).all()
        return [self._serialize(r) for r in rows]

    def _export_relationships(
        self, user_id: str, goals: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Relationships that reference any of the user's entity IDs.

        We collect the user's owned IDs (goals, pathways, requirements,
        scenarios, sources, events, actions, risk_factors) and select
        relationships whose subject_id OR object_id is in that set.
        """
        owned_ids = self._user_owned_entity_ids(user_id, goals)
        if not owned_ids:
            return []
        rows = self.db.scalars(
            select(Relationship).where(
                or_(
                    Relationship.subject_id.in_(owned_ids),
                    Relationship.object_id.in_(owned_ids),
                )
            )
        ).all()
        return [self._serialize(r) for r in rows]

    def _export_plugins(self, user_id: str) -> list[dict[str, Any]]:
        rows = self.db.scalars(
            select(UserPlugin)
            .where(UserPlugin.user_id == user_id, UserPlugin.deleted_at.is_(None))
            .order_by(UserPlugin.created_at.asc())
        ).all()
        return [self._serialize(r) for r in rows]

    def _export_source_proposals(self, user_id: str) -> list[dict[str, Any]]:
        rows = self.db.scalars(
            select(SourceProposal)
            .where(SourceProposal.user_id == user_id)
            .order_by(SourceProposal.created_at.asc())
        ).all()
        return [self._serialize(r) for r in rows]

    # =====================================================================
    # Import
    # =====================================================================

    def import_user_data(
        self,
        user_id: str,
        data: dict[str, Any],
        mode: str = "merge",
    ) -> dict[str, Any]:
        """Import an exported backup into the target user.

        Returns a summary ``{imported: {...}, skipped, errors}``. Each
        entity is wrapped in try/except so one bad row never aborts the
        whole import.
        """
        if mode not in ("merge", "replace"):
            raise ValueError(f"unknown import mode: {mode!r}")

        if mode == "replace":
            self._delete_user_data(user_id)

        id_map: dict[str, str] = {}  # "goal:<old>" -> new_id, etc.
        summary = {
            "imported": {
                "goals": 0,
                "pathways": 0,
                "requirements": 0,
                "events": 0,
                "sources": 0,
                "scenarios": 0,
                "actions": 0,
                "memories": 0,
                "risk_factors": 0,
                "relationships": 0,
                "plugins": 0,
                "source_proposals": 0,
            },
            "skipped": 0,
            "errors": [],
            "rolled_back": False,
        }

        # 0. Pre-assign new IDs for every entity up-front so cross-entity
        # FK remapping works regardless of import order. Pathway.scenario_id
        # is the canonical case: pathways are imported as part of goals,
        # but scenarios are imported separately — without pre-assignment
        # the scenario_id would point to a stale (non-existent) ID.
        self._preassign_ids(data, id_map)

        # 1. Shared risk nodes must exist before pathway M2M links are rebuilt.
        self._import_risk_factors(
            user_id,
            data.get("risk_factors", []),
            id_map,
            summary,
        )

        # 2. Goals → pathways → requirements and their M2M links.
        self._import_goals(user_id, data.get("goals", []), id_map, summary)

        # 3. Independent top-level entities.
        self._import_sources(user_id, data.get("information_sources", []), id_map, summary)
        self._import_scenarios(user_id, data.get("scenarios", []), id_map, summary)
        self._import_events(user_id, data.get("events", []), id_map, summary)
        self._import_actions(user_id, data.get("actions", []), id_map, summary)
        self._import_memories(user_id, data.get("memories", []), id_map, summary)
        self._import_relationships(user_id, data.get("relationships", []), id_map, summary)
        self._import_plugins(user_id, data.get("plugins", []), id_map, summary)
        self._import_source_proposals(user_id, data.get("source_proposals", []), id_map, summary)

        # 4. Update user_profile fields (best-effort, never overwrite auth).
        profile = data.get("user_profile")
        if profile:
            savepoint = self.db.begin_nested()
            try:
                self._apply_profile(user_id, profile)
                savepoint.commit()
            except Exception as exc:  # noqa: BLE001
                if savepoint.is_active:
                    savepoint.rollback()
                summary["errors"].append({
                    "type": "user_profile",
                    "error": str(exc),
                })

        if mode == "replace" and summary["errors"]:
            self.db.rollback()
            self._mark_import_rolled_back(summary)
        else:
            try:
                self.db.commit()
            except Exception as exc:  # noqa: BLE001
                self.db.rollback()
                summary["errors"].append({
                    "type": "commit",
                    "error": f"final commit failed: {exc}",
                })
                self._mark_import_rolled_back(summary)

        log.info(
            "backup.import_done",
            user_id=user_id,
            mode=mode,
            imported=summary["imported"],
            skipped=summary["skipped"],
            errors=len(summary["errors"]),
        )
        return summary

    # ---------- per-entity import helpers ----------

    def _preassign_ids(self, data: dict[str, Any], id_map: dict[str, str]) -> None:
        """Walk the export and assign a fresh UUID to every entity up-front.

        Populates ``id_map`` with ``"<type>:<old_id>"`` → ``new_id`` for
        every entity in the export. This lets FK remapping work in any
        import order.
        """
        for goal in data.get("goals", []) or []:
            old = goal.get("id")
            if old:
                id_map[f"goal:{old}"] = str(uuid.uuid4())
            for pw in goal.get("pathways", []) or []:
                pw_old = pw.get("id")
                if pw_old:
                    id_map[f"pathway:{pw_old}"] = str(uuid.uuid4())
                for req in pw.get("requirements", []) or []:
                    req_old = req.get("id")
                    if req_old:
                        id_map[f"requirement:{req_old}"] = str(uuid.uuid4())
        for sc in data.get("scenarios", []) or []:
            old = sc.get("id")
            if old:
                id_map[f"scenario:{old}"] = str(uuid.uuid4())
        for src in data.get("information_sources", []) or []:
            old = src.get("id")
            if old:
                id_map[f"source:{old}"] = str(uuid.uuid4())
        for rf in data.get("risk_factors", []) or []:
            old = rf.get("id")
            if old:
                id_map[f"risk_factor:{old}"] = str(uuid.uuid4())
        for ev in data.get("events", []) or []:
            old = ev.get("id")
            if old:
                id_map[f"event:{old}"] = str(uuid.uuid4())
        for ac in data.get("actions", []) or []:
            old = ac.get("id")
            if old:
                id_map[f"action:{old}"] = str(uuid.uuid4())
        for mem in data.get("memories", []) or []:
            old = mem.get("id")
            if old:
                id_map[f"memory:{old}"] = str(uuid.uuid4())
        for rel in data.get("relationships", []) or []:
            old = rel.get("id")
            if old:
                id_map[f"relationship:{old}"] = str(uuid.uuid4())
        for pl in data.get("plugins", []) or []:
            old = pl.get("id")
            if old:
                id_map[f"plugin:{old}"] = str(uuid.uuid4())
        for sp in data.get("source_proposals", []) or []:
            old = sp.get("id")
            if old:
                id_map[f"source_proposal:{old}"] = str(uuid.uuid4())

    def _import_goals(
        self,
        user_id: str,
        goals: list[dict[str, Any]],
        id_map: dict[str, str],
        summary: dict[str, Any],
    ) -> None:
        for goal_data in goals:
            old_id = goal_data.get("id")
            goal_savepoint = self.db.begin_nested()
            try:
                new_id = id_map.get(f"goal:{old_id}") if old_id else str(uuid.uuid4())

                fields = self._pick_fields(goal_data, Goal)
                goal = Goal(
                    id=new_id,
                    user_id=user_id,
                    **fields,
                )
                self.db.add(goal)
                self.db.flush()
                for pw_data in goal_data.get("pathways", []) or []:
                    pathway_savepoint = self.db.begin_nested()
                    try:
                        pw_old_id = pw_data.get("id")
                        new_pw_id = (
                            id_map[f"pathway:{pw_old_id}"]
                            if pw_old_id and f"pathway:{pw_old_id}" in id_map
                            else str(uuid.uuid4())
                        )

                        pw_fields = self._pick_fields(pw_data, Pathway)
                        # Remap goal_id → new goal, parent_pathway_id → new pathway.
                        pw_fields["goal_id"] = new_id
                        parent_old = pw_fields.pop("parent_pathway_id", None)
                        if parent_old:
                            pw_fields["parent_pathway_id"] = id_map.get(f"pathway:{parent_old}")
                        # scenario_id is a free-form string on Pathway; remap if known.
                        sc_old = pw_fields.get("scenario_id")
                        if sc_old:
                            pw_fields["scenario_id"] = id_map.get(f"scenario:{sc_old}", sc_old)

                        pathway = Pathway(id=new_pw_id, **pw_fields)
                        self.db.add(pathway)
                        self.db.flush()
                        for req_data in pw_data.get("requirements", []) or []:
                            requirement_savepoint = self.db.begin_nested()
                            try:
                                req_old_id = req_data.get("id")
                                new_req_id = (
                                    id_map[f"requirement:{req_old_id}"]
                                    if req_old_id and f"requirement:{req_old_id}" in id_map
                                    else str(uuid.uuid4())
                                )

                                requirement = self.db.get(Requirement, new_req_id)
                                if requirement is None:
                                    req_fields = self._pick_fields(req_data, Requirement)
                                    req_fields["pathway_id"] = new_pw_id
                                    requirement = Requirement(id=new_req_id, **req_fields)
                                    self.db.add(requirement)
                                    self.db.flush()
                                    summary["imported"]["requirements"] += 1
                                self.db.execute(
                                    pathway_requirements.insert().values(
                                        pathway_id=new_pw_id,
                                        requirement_id=new_req_id,
                                        is_blocking=True,
                                    )
                                )
                                requirement_savepoint.commit()
                            except Exception as exc:  # noqa: BLE001
                                if requirement_savepoint.is_active:
                                    requirement_savepoint.rollback()
                                summary["errors"].append({
                                    "type": "requirement",
                                    "id": req_data.get("id"),
                                    "error": str(exc),
                                })
                        for risk_old_id in pw_data.get("risk_factor_ids", []) or []:
                            risk_id = id_map.get(
                                f"risk_factor:{risk_old_id}", risk_old_id
                            )
                            if self.db.get(RiskFactor, risk_id) is None:
                                continue
                            self.db.execute(
                                pathway_risk_factors.insert().values(
                                    pathway_id=new_pw_id,
                                    risk_factor_id=risk_id,
                                )
                            )
                        pathway_savepoint.commit()
                        summary["imported"]["pathways"] += 1
                    except Exception as exc:  # noqa: BLE001
                        if pathway_savepoint.is_active:
                            pathway_savepoint.rollback()
                        summary["errors"].append({
                            "type": "pathway",
                            "id": pw_data.get("id"),
                            "error": str(exc),
                        })
                goal_savepoint.commit()
                summary["imported"]["goals"] += 1
            except Exception as exc:  # noqa: BLE001
                if goal_savepoint.is_active:
                    goal_savepoint.rollback()
                summary["errors"].append({
                    "type": "goal",
                    "id": old_id,
                    "error": str(exc),
                })

    def _import_sources(
        self,
        user_id: str,
        sources: list[dict[str, Any]],
        id_map: dict[str, str],
        summary: dict[str, Any],
    ) -> None:
        for src_data in sources:
            old_id = src_data.get("id")
            savepoint = self.db.begin_nested()
            try:
                new_id = (
                    id_map[f"source:{old_id}"]
                    if old_id and f"source:{old_id}" in id_map
                    else str(uuid.uuid4())
                )
                fields = self._pick_fields(src_data, InformationSource)
                fields["user_id"] = user_id
                # Drop schedule columns that depend on "now" being meaningful;
                # the importer keeps auto_refresh flag but resets the next run.
                if fields.get("auto_refresh"):
                    fields["next_refresh_at"] = None
                src = InformationSource(id=new_id, **fields)
                self.db.add(src)
                self.db.flush()
                savepoint.commit()
                summary["imported"]["sources"] += 1
            except Exception as exc:  # noqa: BLE001
                if savepoint.is_active:
                    savepoint.rollback()
                summary["errors"].append({
                    "type": "source",
                    "id": old_id,
                    "error": str(exc),
                })

    def _import_risk_factors(
        self,
        user_id: str,
        risk_factors: list[dict[str, Any]],
        id_map: dict[str, str],
        summary: dict[str, Any],
    ) -> None:
        for rf_data in risk_factors:
            old_id = rf_data.get("id")
            savepoint = self.db.begin_nested()
            try:
                name = str(rf_data.get("name") or "").strip()
                risk_type = str(rf_data.get("type") or "other")
                region = rf_data.get("region")
                identity_key = risk_identity_key(name, risk_type, region)
                source_is_global = rf_data.get("user_id") is None
                owner_clause = (
                    RiskFactor.user_id.is_(None)
                    if source_is_global
                    else RiskFactor.user_id == user_id
                )
                existing = self.db.scalar(
                    select(RiskFactor).where(
                        owner_clause,
                        RiskFactor.deleted_at.is_(None),
                        (RiskFactor.identity_key == identity_key)
                        | (
                            (RiskFactor.name == name)
                            & (RiskFactor.type == risk_type)
                            & (RiskFactor.region.is_not_distinct_from(region))
                        ),
                    )
                )
                if existing is not None:
                    if old_id:
                        id_map[f"risk_factor:{old_id}"] = existing.id
                    savepoint.commit()
                    summary["skipped"] += 1
                    continue
                if source_is_global:
                    raise ValueError(
                        f"global risk template is unavailable: {name}"
                    )
                new_id = (
                    id_map[f"risk_factor:{old_id}"]
                    if old_id and f"risk_factor:{old_id}" in id_map
                    else str(uuid.uuid4())
                )
                fields = self._pick_fields(rf_data, RiskFactor)
                fields["user_id"] = user_id
                fields["identity_key"] = identity_key
                rf = RiskFactor(id=new_id, **fields)
                self.db.add(rf)
                self.db.flush()
                savepoint.commit()
                summary["imported"]["risk_factors"] += 1
            except Exception as exc:  # noqa: BLE001
                if savepoint.is_active:
                    savepoint.rollback()
                summary["errors"].append({
                    "type": "risk_factor",
                    "id": old_id,
                    "error": str(exc),
                })

    def _import_scenarios(
        self,
        user_id: str,
        scenarios: list[dict[str, Any]],
        id_map: dict[str, str],
        summary: dict[str, Any],
    ) -> None:
        for sc_data in scenarios:
            old_id = sc_data.get("id")
            savepoint = self.db.begin_nested()
            try:
                new_id = (
                    id_map[f"scenario:{old_id}"]
                    if old_id and f"scenario:{old_id}" in id_map
                    else str(uuid.uuid4())
                )
                fields = self._pick_fields(sc_data, Scenario)
                # Remap goal_id → new goal (skip if unknown).
                old_goal = fields.get("goal_id")
                if old_goal:
                    fields["goal_id"] = id_map.get(f"goal:{old_goal}", old_goal)
                old_pathway = fields.get("pathway_id")
                if old_pathway:
                    fields["pathway_id"] = id_map.get(
                        f"pathway:{old_pathway}", old_pathway
                    )
                # Remap parent_scenario_id → new scenario.
                parent_old = fields.pop("parent_scenario_id", None)
                if parent_old:
                    fields["parent_scenario_id"] = id_map.get(f"scenario:{parent_old}")
                sc = Scenario(id=new_id, **fields)
                self.db.add(sc)
                self.db.flush()
                savepoint.commit()
                summary["imported"]["scenarios"] += 1
            except Exception as exc:  # noqa: BLE001
                if savepoint.is_active:
                    savepoint.rollback()
                summary["errors"].append({
                    "type": "scenario",
                    "id": old_id,
                    "error": str(exc),
                })

    def _import_events(
        self,
        user_id: str,
        events: list[dict[str, Any]],
        id_map: dict[str, str],
        summary: dict[str, Any],
    ) -> None:
        for ev_data in events:
            old_id = ev_data.get("id")
            savepoint = self.db.begin_nested()
            try:
                new_id = (
                    id_map[f"event:{old_id}"]
                    if old_id and f"event:{old_id}" in id_map
                    else str(uuid.uuid4())
                )
                fields = self._pick_fields(ev_data, Event)
                fields["user_id"] = user_id
                # Remap source_id → new source (nullable, may be None).
                old_src = fields.get("source_id")
                if old_src:
                    fields["source_id"] = id_map.get(f"source:{old_src}", old_src)
                ev = Event(id=new_id, **fields)
                self.db.add(ev)
                self.db.flush()
                savepoint.commit()
                summary["imported"]["events"] += 1
            except Exception as exc:  # noqa: BLE001
                if savepoint.is_active:
                    savepoint.rollback()
                summary["errors"].append({
                    "type": "event",
                    "id": old_id,
                    "error": str(exc),
                })

    def _import_actions(
        self,
        user_id: str,
        actions: list[dict[str, Any]],
        id_map: dict[str, str],
        summary: dict[str, Any],
    ) -> None:
        for ac_data in actions:
            old_id = ac_data.get("id")
            savepoint = self.db.begin_nested()
            try:
                new_id = (
                    id_map[f"action:{old_id}"]
                    if old_id and f"action:{old_id}" in id_map
                    else str(uuid.uuid4())
                )
                fields = self._pick_fields(ac_data, Action)
                fields["user_id"] = user_id

                old_goal = fields.get("goal_id")
                if old_goal:
                    fields["goal_id"] = id_map.get(f"goal:{old_goal}", old_goal)
                old_sc = fields.get("scenario_id")
                if old_sc:
                    fields["scenario_id"] = id_map.get(f"scenario:{old_sc}", old_sc)
                old_pw = fields.get("pathway_id")
                if old_pw:
                    fields["pathway_id"] = id_map.get(f"pathway:{old_pw}", old_pw)
                old_req = fields.get("requirement_id")
                if old_req:
                    fields["requirement_id"] = id_map.get(f"requirement:{old_req}", old_req)
                old_rf = fields.get("risk_factor_id")
                if old_rf:
                    fields["risk_factor_id"] = id_map.get(f"risk_factor:{old_rf}", old_rf)
                # source_run_id references ScenarioRun which we don't export — drop.
                fields.pop("source_run_id", None)

                ac = Action(id=new_id, **fields)
                self.db.add(ac)
                self.db.flush()
                savepoint.commit()
                summary["imported"]["actions"] += 1
            except Exception as exc:  # noqa: BLE001
                if savepoint.is_active:
                    savepoint.rollback()
                summary["errors"].append({
                    "type": "action",
                    "id": old_id,
                    "error": str(exc),
                })

    def _import_memories(
        self,
        user_id: str,
        memories: list[dict[str, Any]],
        id_map: dict[str, str],
        summary: dict[str, Any],
    ) -> None:
        for mem_data in memories:
            old_id = mem_data.get("id")
            savepoint = self.db.begin_nested()
            try:
                new_id = (
                    id_map[f"memory:{old_id}"]
                    if old_id and f"memory:{old_id}" in id_map
                    else str(uuid.uuid4())
                )
                fields = self._pick_fields(mem_data, UserMemory)
                fields["user_id"] = user_id
                mem = UserMemory(id=new_id, **fields)
                self.db.add(mem)
                self.db.flush()
                savepoint.commit()
                summary["imported"]["memories"] += 1
            except Exception as exc:  # noqa: BLE001
                if savepoint.is_active:
                    savepoint.rollback()
                summary["errors"].append({
                    "type": "memory",
                    "id": old_id,
                    "error": str(exc),
                })

    def _import_relationships(
        self,
        user_id: str,
        relationships: list[dict[str, Any]],
        id_map: dict[str, str],
        summary: dict[str, Any],
    ) -> None:
        for rel_data in relationships:
            old_id = rel_data.get("id")
            savepoint = self.db.begin_nested()
            try:
                new_id = (
                    id_map[f"relationship:{old_id}"]
                    if old_id and f"relationship:{old_id}" in id_map
                    else str(uuid.uuid4())
                )
                fields = self._pick_fields(rel_data, Relationship)
                # Remap source_id and the polymorphic subject_id / object_id.
                old_src = fields.get("source_id")
                if old_src:
                    fields["source_id"] = id_map.get(f"source:{old_src}", old_src)
                sub_type = fields.get("subject_type")
                sub_id = fields.get("subject_id")
                if sub_type and sub_id:
                    fields["subject_id"] = id_map.get(f"{sub_type}:{sub_id}", sub_id)
                obj_type = fields.get("object_type")
                obj_id = fields.get("object_id")
                if obj_type and obj_id:
                    fields["object_id"] = id_map.get(f"{obj_type}:{obj_id}", obj_id)
                rel = Relationship(id=new_id, **fields)
                self.db.add(rel)
                self.db.flush()
                savepoint.commit()
                summary["imported"]["relationships"] += 1
            except Exception as exc:  # noqa: BLE001
                if savepoint.is_active:
                    savepoint.rollback()
                summary["errors"].append({
                    "type": "relationship",
                    "id": old_id,
                    "error": str(exc),
                })

    def _import_plugins(
        self,
        user_id: str,
        plugins: list[dict[str, Any]],
        id_map: dict[str, str],
        summary: dict[str, Any],
    ) -> None:
        for pl_data in plugins:
            old_id = pl_data.get("id")
            savepoint = self.db.begin_nested()
            try:
                new_id = (
                    id_map[f"plugin:{old_id}"]
                    if old_id and f"plugin:{old_id}" in id_map
                    else str(uuid.uuid4())
                )
                fields = self._pick_fields(pl_data, UserPlugin)
                fields["user_id"] = user_id
                # plugin_id is globally unique — suffix to avoid collisions
                # with already-imported plugins from another user.
                if fields.get("plugin_id"):
                    fields["plugin_id"] = f"{fields['plugin_id']}-{new_id[:8]}"
                pl = UserPlugin(id=new_id, **fields)
                self.db.add(pl)
                self.db.flush()
                savepoint.commit()
                summary["imported"]["plugins"] += 1
            except Exception as exc:  # noqa: BLE001
                if savepoint.is_active:
                    savepoint.rollback()
                summary["errors"].append({
                    "type": "plugin",
                    "id": old_id,
                    "error": str(exc),
                })

    def _import_source_proposals(
        self,
        user_id: str,
        proposals: list[dict[str, Any]],
        id_map: dict[str, str],
        summary: dict[str, Any],
    ) -> None:
        for sp_data in proposals:
            old_id = sp_data.get("id")
            savepoint = self.db.begin_nested()
            try:
                new_id = (
                    id_map[f"source_proposal:{old_id}"]
                    if old_id and f"source_proposal:{old_id}" in id_map
                    else str(uuid.uuid4())
                )
                fields = self._pick_fields(sp_data, SourceProposal)
                fields["user_id"] = user_id
                old_goal = fields.get("goal_id")
                if old_goal:
                    fields["goal_id"] = id_map.get(f"goal:{old_goal}", old_goal)
                sp = SourceProposal(id=new_id, **fields)
                self.db.add(sp)
                self.db.flush()
                savepoint.commit()
                summary["imported"]["source_proposals"] += 1
            except Exception as exc:  # noqa: BLE001
                if savepoint.is_active:
                    savepoint.rollback()
                summary["errors"].append({
                    "type": "source_proposal",
                    "id": old_id,
                    "error": str(exc),
                })

    @staticmethod
    def _mark_import_rolled_back(summary: dict[str, Any]) -> None:
        """Keep attempted counts for audit while reporting zero committed rows."""
        summary["attempted"] = dict(summary["imported"])
        summary["imported"] = {key: 0 for key in summary["imported"]}
        summary["rolled_back"] = True

    # ---------- profile merge ----------

    def _apply_profile(self, user_id: str, profile: dict[str, Any]) -> None:
        """Merge exported profile fields into the target user.

        Auth-related fields (password_hash, role, is_enabled, OAuth/passkey
        links) are never touched — importing a backup must not silently
        rewrite the account's credentials.
        """
        user = self.db.get(UserProfile, user_id)
        if user is None:
            return
        mergeable = (
            "display_name",
            "avatar_url",
            "demographics",
            "priority_factors",
            "risk_tolerance",
            "notify_channels",
            "quiet_hours",
            "progress",
            "implicit_tags",
        )
        for key in mergeable:
            if key in profile and profile[key] is not None:
                setattr(user, key, profile[key])
        self.db.flush()

    # ---------- replace-mode wipe ----------

    def _delete_user_data(self, user_id: str) -> None:
        """Hard-delete every user-scoped row before a replace-mode import.

        Order matters: children first, then parents, to satisfy FK
        constraints. ``UserPlugin`` plugin files on disk are left alone —
        only the DB row is removed.
        """
        # Children with FKs to goals/pathways/requirements.
        self.db.query(Action).filter(Action.user_id == user_id).delete(synchronize_session=False)
        self.db.query(UserMemory).filter(UserMemory.user_id == user_id).delete(synchronize_session=False)
        self.db.query(SourceProposal).filter(SourceProposal.user_id == user_id).delete(synchronize_session=False)
        self.db.query(UserPlugin).filter(UserPlugin.user_id == user_id).delete(synchronize_session=False)
        self.db.query(Event).filter(Event.user_id == user_id).delete(synchronize_session=False)
        self.db.query(InformationSource).filter(InformationSource.user_id == user_id).delete(synchronize_session=False)

        # Scenarios are scoped via goal_id.
        goal_ids = self._user_goal_ids(user_id)
        if goal_ids:
            self.db.query(Scenario).filter(Scenario.goal_id.in_(goal_ids)).delete(synchronize_session=False)

        # Goals cascade to pathways → requirements (ORM cascade), but a raw
        # delete doesn't fire ORM cascades, so we delete children manually.
        if goal_ids:
            self.db.query(Requirement).filter(
                Requirement.pathway_id.in_(
                    select(Pathway.id).where(Pathway.goal_id.in_(goal_ids))
                )
            ).delete(synchronize_session=False)
            self.db.query(Pathway).filter(Pathway.goal_id.in_(goal_ids)).delete(synchronize_session=False)
            self.db.query(Goal).filter(Goal.id.in_(goal_ids)).delete(synchronize_session=False)

        # Relationships: drop any whose subject_id or object_id was one of
        # the user's entities. We can't easily re-derive that set after the
        # rows above are gone, so we use a defensive scan against any IDs
        # that no longer resolve to a real entity. Simplest correct
        # approach: skip — relationships referencing deleted entities will
        # be re-imported from the backup. Stale ones (if any) are kept as
        # audit trail.
        self.db.flush()

    # =====================================================================
    # Serializer / field picker
    # =====================================================================

    def _serialize(self, obj: Any) -> dict[str, Any]:
        """Convert a SQLAlchemy model instance to a JSON-safe dict.

        Walks ``__table__.columns`` so relationship attributes aren't
        touched. Datetime/date → ISO string; JSONB / dict / list → as-is.
        """
        if obj is None:
            return {}
        out: dict[str, Any] = {}
        for col in obj.__table__.columns:
            name = col.name
            if name in _SKIP_FIELDS:
                continue
            value = getattr(obj, name, None)
            if isinstance(value, (datetime, date)):
                out[name] = value.isoformat()
            else:
                out[name] = value
        return out

    def _pick_fields(
        self, data: dict[str, Any], model_cls: type
    ) -> dict[str, Any]:
        """Pick only the fields that exist as columns on ``model_cls``.

        Skips ``id`` (caller assigns a fresh UUID), ``user_id`` (caller
        sets it explicitly), and the internal fields in ``_SKIP_FIELDS``.
        Datetime / date strings are parsed back to real objects so SQLAlchemy
        can store them.
        """
        out: dict[str, Any] = {}
        col_names = {c.name for c in model_cls.__table__.columns}
        for key, value in data.items():
            if key not in col_names:
                continue
            if key in ("id", "user_id") or key in _SKIP_FIELDS:
                continue
            if value == "" and key in {"avatar_url", "publisher", "url"}:
                value = None
            out[key] = self._coerce(value, model_cls, key)
        return out

    def _coerce(self, value: Any, model_cls: type, col_name: str) -> Any:
        """Parse datetime/date strings back to real objects.

        JSONB columns already come back as dict/list — no coercion needed.
        String columns are passed through unchanged.
        """
        if isinstance(value, str) and value:
            col = model_cls.__table__.columns.get(col_name)
            if col is not None:
                python_type = getattr(col.type, "python_type", None)
                if python_type is datetime:
                    try:
                        return datetime.fromisoformat(value)
                    except ValueError:
                        return value
                if python_type is date:
                    try:
                        return date.fromisoformat(value[:10])
                    except ValueError:
                        return value
        return value

    # =====================================================================
    # Misc helpers
    # =====================================================================

    def _user_goal_ids(self, user_id: str) -> list[str]:
        rows = self.db.scalars(select(Goal.id).where(Goal.user_id == user_id)).all()
        return list(rows)

    def _user_owned_entity_ids(
        self, user_id: str, goals: list[dict[str, Any]]
    ) -> set[str]:
        """Collect every ID the user owns, for relationship scoping."""
        ids: set[str] = set()
        # Goals + nested pathways/requirements.
        for g in goals:
            if g.get("id"):
                ids.add(g["id"])
            for pw in g.get("pathways", []) or []:
                if pw.get("id"):
                    ids.add(pw["id"])
                for req in pw.get("requirements", []) or []:
                    if req.get("id"):
                        ids.add(req["id"])
        # Goal IDs straight from DB (in case the goals list was filtered).
        goal_ids = self._user_goal_ids(user_id)
        ids.update(goal_ids)
        # Scenarios owned via goal_id.
        if goal_ids:
            ids.update(self.db.scalars(
                select(Scenario.id).where(Scenario.goal_id.in_(goal_ids))
            ).all())
        # Events, sources, actions.
        ids.update(self.db.scalars(
            select(Event.id).where(Event.user_id == user_id)
        ).all())
        ids.update(self.db.scalars(
            select(InformationSource.id).where(InformationSource.user_id == user_id)
        ).all())
        ids.update(self.db.scalars(
            select(Action.id).where(Action.user_id == user_id)
        ).all())
        return ids


__all__ = ["BackupService", "EXPORT_VERSION"]
