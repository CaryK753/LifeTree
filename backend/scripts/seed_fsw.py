"""FSW (Federal Skilled Worker) example data seeder.

Populates a generic-skeleton schema with Canadian FSW immigration data so
the LifeTree UI has something concrete to render on first launch.

Run via:  python scripts/seed_fsw.py
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# Make `app.*` importable when running this script directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.logging import configure_logging, get_logger  # noqa: E402
from app.core.tenant import DEFAULT_USER_ID  # noqa: E402
from app.db.postgres import SessionLocal  # noqa: E402
from app.models.event import (  # noqa: E402
    Event,
    InformationSource,
    MetricSnapshot,
)
from app.models.goal import (  # noqa: E402
    Goal,
    GoalStatus,
    Pathway,
    PathwayStatus,
    Requirement,
    RiskFactor,
)
from app.models.scenario import Scenario, ScenarioStatus  # noqa: E402
from app.models.user import UserProfile  # noqa: E402
from app.services.graph import GraphService  # noqa: E402

log = get_logger(__name__)


def seed() -> None:
    configure_logging("INFO")
    db = SessionLocal()
    graph = GraphService()
    try:
        # ----- User (pinned to DEFAULT_USER_ID for single-user mode) -----
        user = db.get(UserProfile, DEFAULT_USER_ID)
        if user is None:
            user = UserProfile(
                id=DEFAULT_USER_ID,
                display_name="Alex Chen",
                email="alex@example.com",
                demographics={
                    "age": 32,
                    "nationality": "CN",
                    "education": "master",
                    "languages": {"ielts": None, "french": None},
                    "funds_cad": 25000,
                },
                priority_factors={"cost": True, "speed": True, "climate": True},
                risk_tolerance="medium",
                notify_channels={"email": True, "in_app": True},
                quiet_hours={"start": 23, "end": 7},
            )
            db.add(user)
            db.flush()
            log.info("seed.user_created", user_id=user.id)
        else:
            log.info("seed.user_reused", user_id=user.id)

        # ----- Goal -----
        goal = Goal(
            user_id=user.id,
            title="Obtain Canadian PR via Federal Skilled Worker",
            description="Target Express Entry ITA within 18 months",
            scenario="fsw",
            target_date=date.today().replace(year=date.today().year + 2),
            status=GoalStatus.ACTIVE.value,
            meta={"region": "CA", "program": "Express Entry / FSW"},
        )
        db.add(goal)
        db.flush()
        user.primary_goal_id = goal.id
        graph.upsert_goal(goal)
        log.info("seed.goal", goal_id=goal.id)

        # ----- Pathway: Federal Skilled Worker -----
        fsw = Pathway(
            goal_id=goal.id,
            name="Federal Skilled Worker (Express Entry)",
            description="Skilled worker PR via CRS-ranked Express Entry pool",
            region="CA",
            status=PathwayStatus.SELECTED.value,
            eligibility={
                "min_crss": 67,
                "min_one_year_skilled_work": True,
                "language_min": "CLB 7",
                "education_min": "secondary",
            },
            milestones=[
                {"label": "IELTS >= 8777", "due": "2026-10-01", "status": "pending"},
                {"label": "WES ECA submitted", "due": "2026-11-15", "status": "pending"},
                {"label": "Express Entry profile", "due": "2026-12-15", "status": "pending"},
                {"label": "ITA received", "due": "2027-06-30", "status": "pending"},
                {"label": "PR granted", "due": "2028-06-30", "status": "pending"},
            ],
        )
        db.add(fsw)
        db.flush()
        user.preferred_pathway_id = fsw.id
        graph.upsert_pathway(fsw)
        log.info("seed.pathway", pathway_id=fsw.id)

        # ----- Requirements -----
        reqs = [
            Requirement(
                pathway_id=fsw.id, name="IELTS General", type="language",
                description="CLB 9+ (L:8 R:8 W:7 S:7) for max CRS points",
                threshold={"min": "8.0", "min_per_band": "7.0"},
                current_value={"overall": None},
                gap_status="missing", weight=1.5,
            ),
            Requirement(
                pathway_id=fsw.id, name="WES Educational Credential Assessment", type="education",
                description="Foreign degree equivalency report",
                threshold={"required": True, "min_level": "secondary"},
                current_value={"submitted": False},
                gap_status="missing", weight=1.0,
            ),
            Requirement(
                pathway_id=fsw.id, name="Proof of Funds (CAD)", type="financial",
                description="Settlement funds for family of 1: CAD 14,690",
                threshold={"min_cad": 14690},
                current_value={"cad": 25000},
                gap_status="met", weight=0.8,
            ),
            Requirement(
                pathway_id=fsw.id, name="1 Year Skilled Work Experience", type="experience",
                description="NOC TEER 0/1/2/3, continuous, paid",
                threshold={"min_years": 1, "noc": "TEER 0/1/2/3"},
                current_value={"years": 4, "noc": "TEER 1"},
                gap_status="met", weight=1.2,
            ),
            Requirement(
                pathway_id=fsw.id, name="CRS Score >= 500", type="other",
                description="Recent FSW draw cutoff ~500; competitive target 500+",
                threshold={"min": 500},
                current_value={"estimated": 432},
                gap_status="partial", gap_delta=-68.0, weight=1.8,
            ),
        ]
        for r in reqs:
            db.add(r)
            db.flush()
            graph.upsert_requirement(r)

        # ----- Risk Factors -----
        rfs = [
            RiskFactor(
                type="policy", name="FSW Draw Cutoff Inflation",
                description="CRS cutoffs rising due to CEC-only draws",
                region="CA", level="high", urgency="elevated",
                probability=0.7, impact=0.6, half_life_days=180,
            ),
            RiskFactor(
                type="economic", name="CAD/CNY Exchange Volatility",
                description="FX swings affecting proof-of-funds purchasing power",
                region="CA", level="medium", urgency="normal",
                probability=0.5, impact=0.3, half_life_days=90,
            ),
            RiskFactor(
                type="policy", name="IRCC Processing Backlogs",
                description="Backlog growth could delay ITA→COPR timeline",
                region="CA", level="medium", urgency="normal",
                probability=0.6, impact=0.4, half_life_days=180,
            ),
            RiskFactor(
                type="political", name="Canadian Immigration Policy Shift",
                description="Post-election immigration level adjustments",
                region="CA", level="low", urgency="normal",
                probability=0.3, impact=0.5, half_life_days=365,
            ),
        ]
        for rf in rfs:
            db.add(rf)
            db.flush()
            graph.upsert_risk_factor(rf)

        # ----- Scenario: baseline -----
        baseline = Scenario(
            goal_id=goal.id,
            name="Baseline (current trajectory)",
            description="Assumes current CRS score, no retake of IELTS",
            status=ScenarioStatus.ACTIVE.value,
            assumptions={
                "ielts_target": "current",
                "funds_cad": 25000,
                "draw_cutoff_trend": "rising_5_per_draw",
            },
            impact_threshold=0.05,
        )
        db.add(baseline)
        db.flush()
        graph.upsert_scenario(baseline)

        # ----- Scenario: IELTS retake -----
        retake = Scenario(
            goal_id=goal.id,
            name="IELTS 8777 + Provincial Nominee",
            description="Retake IELTS to maximize CRS; pursue Ontario OINP nomination",
            status=ScenarioStatus.DRAFT.value,
            parent_scenario_id=baseline.id,
            assumptions={
                "ielts_target": "8777",
                "oinp_nomination": True,
                "crs_boost": 60,
            },
            impact_threshold=0.05,
        )
        db.add(retake)
        db.flush()
        graph.upsert_scenario(retake)

        # ----- Information Sources -----
        src1 = InformationSource(
            kind="official", title="IRCC Express Entry draw #321",
            url="https://www.canada.ca/en/immigration-refugees-citizenship.html",
            publisher="IRCC",
            published_at=datetime.now(timezone.utc) - timedelta(days=14),
            credibility="high", credibility_score=0.95,
            raw_text=(
                "IRCC issued 917 ITAs in Express Entry draw #321 on July 11, 2026. "
                "The CRS cutoff was 511, up 6 points from the previous general draw. "
                "Program-specific draws may continue."
            ),
        )
        src2 = InformationSource(
            kind="news", title="CIC News: CRS cutoff analysis Q3 2026",
            url="https://www.cicnews.com/",
            publisher="CIC News",
            published_at=datetime.now(timezone.utc) - timedelta(days=3),
            credibility="medium", credibility_score=0.7,
            raw_text=(
                "Analysts project CRS cutoffs will remain above 500 for the next "
                "two quarters. Provincial Nominee Programs (PNP) remain the most "
                "reliable path to a 600-point boost."
            ),
        )
        db.add_all([src1, src2])
        db.flush()
        for s in (src1, src2):
            graph.upsert_source(s)

        # ----- Events -----
        ev1 = Event(
            source_id=src1.id,
            subject="IRCC", action="issued", object="Express Entry ITAs",
            occurred_at=datetime.now(timezone.utc) - timedelta(days=14),
            old_value=None, new_value={"count": 917, "cutoff": 511},
            risk_flag_level="high", risk_flag_type="policy",
            risk_flag_urgency="elevated",
            extraction_confidence=0.95,
        )
        ev2 = Event(
            source_id=src2.id,
            subject="CRS cutoff", action="trended upward",
            object="Express Entry pool",
            occurred_at=datetime.now(timezone.utc) - timedelta(days=3),
            old_value=505, new_value=511,
            risk_flag_level="medium", risk_flag_type="policy",
            risk_flag_urgency="normal",
            extraction_confidence=0.8,
        )
        db.add_all([ev1, ev2])
        db.flush()
        for ev in (ev1, ev2):
            graph.upsert_event(ev, None)

        # ----- Metrics -----
        db.add_all([
            MetricSnapshot(
                source_id=src1.id, name="CRS_cutoff", region="CA",
                value=511, unit="points",
                captured_at=datetime.now(timezone.utc) - timedelta(days=14),
            ),
            MetricSnapshot(
                source_id=src2.id, name="CRS_cutoff_forecast_q4", region="CA",
                value=515, unit="points",
                captured_at=datetime.now(timezone.utc) - timedelta(days=3),
            ),
            MetricSnapshot(
                name="proof_of_funds_cad_single", region="CA",
                value=14690, unit="CAD",
                captured_at=datetime.now(timezone.utc),
            ),
        ])

        # ----- Run baseline reasoning -----
        from app.services.scenarios import ScenarioService
        ScenarioService(db).run_reasoning(baseline.id)

        db.commit()
        log.info("seed.complete",
                 user_id=user.id, goal_id=goal.id,
                 pathways=1, requirements=len(reqs),
                 risk_factors=len(rfs), scenarios=2)

    except Exception as exc:  # noqa: BLE001
        db.rollback()
        log.error("seed.failed", error=str(exc))
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
