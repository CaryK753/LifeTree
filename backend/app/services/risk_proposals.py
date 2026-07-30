"""Persistence and state transitions for emerging-risk proposals."""

from __future__ import annotations

import hashlib
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.goal import Goal, Pathway
from app.models.intelligence import RiskProposal


class RiskProposalService:
    def __init__(self, db: Session, user_id: str) -> None:
        self.db = db
        self.user_id = user_id

    def persist(self, proposals: list[dict]) -> list[RiskProposal]:
        rows: list[RiskProposal] = []
        for proposal in proposals:
            fingerprint = self._fingerprint(proposal)
            row = self.db.scalar(select(RiskProposal).where(
                RiskProposal.user_id == self.user_id,
                RiskProposal.fingerprint == fingerprint,
            ))
            if row is None:
                row = RiskProposal(
                    user_id=self.user_id,
                    fingerprint=fingerprint,
                    name=proposal.get("name") or "Unknown risk",
                )
                self.db.add(row)
            if row.status == "proposed":
                row.type = proposal.get("type") or "other"
                row.region = proposal.get("region")
                row.urgency = proposal.get("urgency") or "normal"
                row.description = proposal.get("description") or ""
                row.cluster_size = int(proposal.get("cluster_size") or 0)
                row.affected_goals_count = int(
                    proposal.get("affected_goals_count") or 0
                )
                row.evidence = [
                    {"title": title} for title in proposal.get("sample_events", [])
                ]
                row.impact_preview = {
                    "affected_goals_count": row.affected_goals_count,
                    "affected_pathways_hint": proposal.get("affected_pathways_hint"),
                    "suggested_pathway_id": self._suggest_pathway(row.region),
                }
            rows.append(row)
        self.db.commit()
        for row in rows:
            self.db.refresh(row)
        return rows

    def list(self, status: str | None = "proposed") -> list[RiskProposal]:
        stmt = select(RiskProposal).where(RiskProposal.user_id == self.user_id)
        if status:
            stmt = stmt.where(RiskProposal.status == status)
        return list(self.db.scalars(stmt.order_by(RiskProposal.created_at.desc())))

    def get_owned(self, proposal_id: str) -> RiskProposal | None:
        proposal = self.db.get(RiskProposal, proposal_id)
        if proposal is None or proposal.user_id != self.user_id:
            return None
        return proposal

    def reject(self, proposal_id: str) -> RiskProposal | None:
        proposal = self.get_owned(proposal_id)
        if proposal is None:
            return None
        if proposal.status == "adopted":
            return proposal
        proposal.status = "rejected"
        self.db.add(proposal)
        self.db.commit()
        self.db.refresh(proposal)
        return proposal

    def mark_adopted(self, proposal_id: str, risk_factor_id: str) -> RiskProposal | None:
        proposal = self.get_owned(proposal_id)
        if proposal is None:
            return None
        proposal.status = "adopted"
        proposal.adopted_risk_factor_id = risk_factor_id
        self.db.add(proposal)
        self.db.commit()
        self.db.refresh(proposal)
        return proposal

    @staticmethod
    def serialize(row: RiskProposal) -> dict:
        return {
            "id": row.id,
            "name": row.name,
            "type": row.type,
            "region": row.region,
            "urgency": row.urgency,
            "description": row.description,
            "status": row.status,
            "cluster_size": row.cluster_size,
            "affected_goals_count": row.affected_goals_count,
            "evidence": row.evidence,
            "impact_preview": row.impact_preview,
            "adopted_risk_factor_id": row.adopted_risk_factor_id,
            "created_at": row.created_at.isoformat(),
        }

    @staticmethod
    def _fingerprint(proposal: dict) -> str:
        parts = [
            re.sub(r"\W+", "", str(proposal.get("name") or "").lower()),
            str(proposal.get("type") or "other").lower(),
            str(proposal.get("region") or "global").lower(),
        ]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()

    def _suggest_pathway(self, region: str | None) -> str | None:
        stmt = (
            select(Pathway.id)
            .join(Goal, Goal.id == Pathway.goal_id)
            .where(Goal.user_id == self.user_id)
            .order_by(Pathway.created_at.desc())
        )
        if region:
            stmt = stmt.where(Pathway.region == region)
        return self.db.scalar(stmt.limit(1))
