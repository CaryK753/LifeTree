"""Bayesian source reputation and collection-quality tracking."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.event import InformationSource
from app.models.intelligence import SourceAccuracyLog

PRIOR_STRENGTH = 4.0


class SourceReputationService:
    def __init__(self, db: Session, user_id: str) -> None:
        self.db = db
        self.user_id = user_id

    def record_verdict(
        self,
        source: InformationSource,
        *,
        evidence_key: str,
        confirmed: bool,
        meta: dict | None = None,
    ) -> SourceAccuracyLog:
        existing = self.db.scalar(select(SourceAccuracyLog).where(
            SourceAccuracyLog.source_id == source.id,
            SourceAccuracyLog.evidence_key == evidence_key,
        ))
        if existing is not None:
            return existing

        source_meta = dict(getattr(source, "meta", None) or {})
        alpha = float(source_meta.get("reputation_alpha", source.credibility_score * PRIOR_STRENGTH))
        beta = float(source_meta.get("reputation_beta", (1.0 - source.credibility_score) * PRIOR_STRENGTH))
        posterior_alpha = alpha + (1.0 if confirmed else 0.0)
        posterior_beta = beta + (0.0 if confirmed else 1.0)
        score = posterior_alpha / (posterior_alpha + posterior_beta)

        row = SourceAccuracyLog(
            user_id=self.user_id,
            source_id=source.id,
            evidence_key=evidence_key,
            verdict="confirmed" if confirmed else "refuted",
            prior_alpha=alpha,
            prior_beta=beta,
            posterior_alpha=posterior_alpha,
            posterior_beta=posterior_beta,
            resulting_score=score,
            meta=meta or {},
        )
        source_meta["reputation_alpha"] = posterior_alpha
        source_meta["reputation_beta"] = posterior_beta
        source_meta["accuracy_observations"] = int(
            source_meta.get("accuracy_observations", 0)
        ) + 1
        source.meta = source_meta
        source.credibility_score = score
        self.db.add(source)
        self.db.add(row)
        return row

    def record_fetch(self, source: InformationSource, *, succeeded: bool) -> None:
        meta = dict(source.meta or {})
        total = int(meta.get("fetch_attempts", 0)) + 1
        successes = int(meta.get("fetch_successes", 0)) + int(succeeded)
        meta.update({
            "fetch_attempts": total,
            "fetch_successes": successes,
            "fetch_success_rate": round(successes / total, 4),
        })
        source.meta = meta
        self.db.add(source)

    def summary(self, source_id: str) -> dict:
        source = self.db.get(InformationSource, source_id)
        if source is None or source.user_id != self.user_id:
            return {"ok": False, "error": "source_not_found"}
        logs = list(self.db.scalars(
            select(SourceAccuracyLog)
            .where(SourceAccuracyLog.source_id == source_id)
            .order_by(SourceAccuracyLog.created_at.desc())
            .limit(100)
        ))
        return {
            "ok": True,
            "source_id": source.id,
            "credibility_score": source.credibility_score,
            "fetch_success_rate": (source.meta or {}).get("fetch_success_rate"),
            "observations": len(logs),
            "history": [
                {
                    "evidence_key": row.evidence_key,
                    "verdict": row.verdict,
                    "resulting_score": row.resulting_score,
                    "created_at": row.created_at.isoformat(),
                }
                for row in logs
            ],
        }
