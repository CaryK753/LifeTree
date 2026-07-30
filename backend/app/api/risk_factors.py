"""RiskFactor CRUD endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.tenant import AdminUser, CurrentUser
from app.db.postgres import get_db
from app.models.goal import RiskFactor
from app.schemas.entities import (
    RiskFactorCreate,
    RiskFactorRead,
    RiskFactorUpdate,
)
from app.services.graph import GraphService
from app.services.risk_scope import (
    get_mutable_risk,
    get_visible_risk,
    risk_identity_key,
    risk_scope_clause,
)

router = APIRouter(prefix="/risk-factors", tags=["risk-factors"])
graph = GraphService()


@router.post("", response_model=RiskFactorRead, status_code=201)
def create_risk_factor(
    payload: RiskFactorCreate,
    admin: AdminUser,
    db: Session = Depends(get_db),
) -> RiskFactor:
    data = payload.model_dump()
    identity_key = risk_identity_key(data["name"], data["type"], data["region"])
    existing = db.scalar(
        select(RiskFactor).where(
            RiskFactor.user_id.is_(None),
            RiskFactor.deleted_at.is_(None),
            (RiskFactor.identity_key == identity_key)
            | (
                (func.lower(RiskFactor.name) == data["name"].casefold())
                & (RiskFactor.type == data["type"])
                & (RiskFactor.region.is_not_distinct_from(data["region"]))
            ),
        )
    )
    if existing is not None:
        return existing
    rf = RiskFactor(user_id=None, identity_key=identity_key, **data)
    db.add(rf)
    db.commit()
    db.refresh(rf)
    graph.upsert_risk_factor(rf)
    return rf


@router.get("", response_model=list[RiskFactorRead])
def list_risk_factors(
    user: CurrentUser,
    region: str | None = None,
    level: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> list[RiskFactor]:
    stmt = select(RiskFactor).where(
        RiskFactor.deleted_at.is_(None),
        risk_scope_clause(user.id),
    )
    if region:
        stmt = stmt.where(RiskFactor.region == region)
    if level:
        stmt = stmt.where(RiskFactor.level == level)
    return list(db.scalars(stmt.limit(limit).order_by(RiskFactor.level.desc())))


@router.get("/{rf_id}", response_model=RiskFactorRead)
def get_risk_factor(
    rf_id: str,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> RiskFactor:
    return get_visible_risk(db, rf_id, user.id)


@router.patch("/{rf_id}", response_model=RiskFactorRead)
def update_risk_factor(
    rf_id: str,
    payload: RiskFactorUpdate,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> RiskFactor:
    rf = get_mutable_risk(
        db,
        rf_id,
        user_id=user.id,
        is_admin=user.role == "admin",
    )
    updates = payload.model_dump(exclude_unset=True)
    for k, v in updates.items():
        setattr(rf, k, v)
    if {"name", "type", "region"} & updates.keys():
        rf.identity_key = risk_identity_key(rf.name, rf.type, rf.region)
        if rf.user_id is not None:
            duplicate_id = db.scalar(
                select(RiskFactor.id).where(
                    RiskFactor.user_id == rf.user_id,
                    RiskFactor.identity_key == rf.identity_key,
                    RiskFactor.id != rf.id,
                    RiskFactor.deleted_at.is_(None),
                )
            )
            if duplicate_id is not None:
                raise HTTPException(409, "An equivalent risk factor already exists")
    db.commit()
    db.refresh(rf)
    graph.upsert_risk_factor(rf)
    return rf


@router.delete("/{rf_id}", status_code=204)
def delete_risk_factor(
    rf_id: str,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> None:
    rf = get_mutable_risk(
        db,
        rf_id,
        user_id=user.id,
        is_admin=user.role == "admin",
    )
    rf.deleted_at = datetime.now(timezone.utc)
    db.commit()
