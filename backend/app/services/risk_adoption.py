"""Idempotent creation and pathway adoption for personal risk factors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.goal import Goal, Pathway, RiskFactor, pathway_risk_factors
from app.services.risk_scope import lock_risk_identity, risk_identity_key


@dataclass(frozen=True)
class RiskAdoption:
    risk_factor: RiskFactor
    created: bool
    linked: bool


def get_or_create_user_risk(
    db: Session,
    *,
    user_id: str,
    name: str,
    risk_type: str,
    region: str | None,
    values: dict[str, Any],
) -> tuple[RiskFactor, bool]:
    """Reuse an equivalent personal/global risk or create a personal one."""
    identity_key = risk_identity_key(name, risk_type, region)
    lock_risk_identity(db, user_id, identity_key)

    existing = db.scalar(
        select(RiskFactor)
        .where(
            RiskFactor.deleted_at.is_(None),
            (
                (RiskFactor.user_id == user_id)
                & (RiskFactor.identity_key == identity_key)
            )
            | (
                (RiskFactor.user_id.is_(None))
                & (func.lower(RiskFactor.name) == name.casefold())
                & (RiskFactor.type == risk_type)
                & (RiskFactor.region.is_not_distinct_from(region))
            ),
        )
        .order_by(case((RiskFactor.user_id == user_id, 0), else_=1))
        .limit(1)
    )
    if existing is not None:
        return existing, False

    risk = RiskFactor(
        user_id=user_id,
        identity_key=identity_key,
        name=name,
        type=risk_type,
        region=region,
        **values,
    )
    db.add(risk)
    db.flush()
    return risk, True


def adopt_risk_for_pathway(
    db: Session,
    *,
    user_id: str,
    pathway_id: str,
    name: str,
    risk_type: str,
    region: str | None,
    values: dict[str, Any],
) -> RiskAdoption:
    """Adopt an equivalent risk into one user-owned pathway."""
    pathway = db.get(Pathway, pathway_id)
    if pathway is None:
        raise NotFoundError("Pathway not found")
    goal = db.get(Goal, pathway.goal_id)
    if goal is None or goal.user_id != user_id:
        raise NotFoundError("Pathway not found")

    risk, created = get_or_create_user_risk(
        db,
        user_id=user_id,
        name=name,
        risk_type=risk_type,
        region=region,
        values=values,
    )
    existing_link = db.execute(
        select(pathway_risk_factors).where(
            pathway_risk_factors.c.pathway_id == pathway.id,
            pathway_risk_factors.c.risk_factor_id == risk.id,
        )
    ).first()
    linked = existing_link is None
    if linked:
        db.execute(
            pathway_risk_factors.insert().values(
                pathway_id=pathway.id,
                risk_factor_id=risk.id,
            )
        )
    db.commit()
    db.refresh(risk)
    return RiskAdoption(risk_factor=risk, created=created, linked=linked)


__all__ = ["RiskAdoption", "adopt_risk_for_pathway", "get_or_create_user_risk"]
