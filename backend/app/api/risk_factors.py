"""RiskFactor CRUD endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.models.goal import RiskFactor
from app.schemas.entities import (
    RiskFactorCreate,
    RiskFactorRead,
    RiskFactorUpdate,
)
from app.services.graph import GraphService

router = APIRouter(prefix="/risk-factors", tags=["risk-factors"])
graph = GraphService()


@router.post("", response_model=RiskFactorRead, status_code=201)
def create_risk_factor(
    payload: RiskFactorCreate, db: Session = Depends(get_db)
) -> RiskFactor:
    rf = RiskFactor(**payload.model_dump())
    db.add(rf)
    db.commit()
    db.refresh(rf)
    graph.upsert_risk_factor(rf)
    return rf


@router.get("", response_model=list[RiskFactorRead])
def list_risk_factors(
    region: str | None = None,
    level: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> list[RiskFactor]:
    stmt = select(RiskFactor)
    if region:
        stmt = stmt.where(RiskFactor.region == region)
    if level:
        stmt = stmt.where(RiskFactor.level == level)
    return list(db.scalars(stmt.limit(limit).order_by(RiskFactor.level.desc())))


@router.get("/{rf_id}", response_model=RiskFactorRead)
def get_risk_factor(rf_id: str, db: Session = Depends(get_db)) -> RiskFactor:
    rf = db.get(RiskFactor, rf_id)
    if rf is None:
        raise HTTPException(404, "RiskFactor not found")
    return rf


@router.patch("/{rf_id}", response_model=RiskFactorRead)
def update_risk_factor(
    rf_id: str, payload: RiskFactorUpdate, db: Session = Depends(get_db)
) -> RiskFactor:
    rf = db.get(RiskFactor, rf_id)
    if rf is None:
        raise HTTPException(404, "RiskFactor not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(rf, k, v)
    db.commit()
    db.refresh(rf)
    graph.upsert_risk_factor(rf)
    return rf


@router.delete("/{rf_id}", status_code=204)
def delete_risk_factor(rf_id: str, db: Session = Depends(get_db)) -> None:
    rf = db.get(RiskFactor, rf_id)
    if rf is None:
        raise HTTPException(404, "RiskFactor not found")
    db.delete(rf)
    db.commit()
