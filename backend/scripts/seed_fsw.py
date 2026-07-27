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

        # ----- Pathway: OINP (Ontario Immigrant Nominee Program) -----
        # Human Capital Priorities stream — for Express Entry candidates
        # with CRS 400+ and a strong Ontario connection. Gives a 600-point
        # CRS boost, effectively guaranteeing an ITA.
        oinp = Pathway(
            goal_id=goal.id,
            name="OINP - Human Capital Priorities",
            description="Ontario nomination via Express Entry HCP stream (+600 CRS)",
            region="CA-ON",
            status=PathwayStatus.CANDIDATE.value,
            eligibility={
                "express_entry_profile": True,
                "min_crss": 400,
                "work_experience": "1 year skilled (NOC TEER 0/1/2/3)",
                "education": "post-secondary",
                "intention": "reside in Ontario",
            },
            milestones=[
                {"label": "Express Entry profile active", "due": "2026-12-15", "status": "pending"},
                {"label": "OINP Notification of Interest", "due": "2027-03-01", "status": "pending"},
                {"label": "OINP application submitted", "due": "2027-05-15", "status": "pending"},
                {"label": "Provincial nomination received", "due": "2027-08-01", "status": "pending"},
                {"label": "ITA (600 CRS boost)", "due": "2027-09-15", "status": "pending"},
                {"label": "PR granted", "due": "2028-06-30", "status": "pending"},
            ],
        )
        db.add(oinp)
        db.flush()
        graph.upsert_pathway(oinp)
        log.info("seed.pathway.oinp", pathway_id=oinp.id)

        oinp_reqs = [
            Requirement(
                pathway_id=oinp.id, name="Express Entry Profile", type="other",
                description="Active EE profile in the federal pool",
                threshold={"required": True},
                current_value={"active": False},
                gap_status="missing", weight=1.5,
            ),
            Requirement(
                pathway_id=oinp.id, name="CRS Score >= 400", type="other",
                description="Minimum CRS for OINP HCP eligibility",
                threshold={"min": 400},
                current_value={"estimated": 432},
                gap_status="met", weight=1.0,
            ),
            Requirement(
                pathway_id=oinp.id, name="Ontario Residency Intent", type="other",
                description="Genuine intent to reside in Ontario",
                threshold={"required": True},
                current_value={"declared": False},
                gap_status="missing", weight=0.8,
            ),
            Requirement(
                pathway_id=oinp.id, name="Education (Post-Secondary)", type="education",
                description="Canadian or equivalent foreign credential",
                threshold={"min_level": "post_secondary"},
                current_value={"level": "master"},
                gap_status="met", weight=1.0,
            ),
        ]
        for r in oinp_reqs:
            db.add(r)
            db.flush()
            graph.upsert_requirement(r)

        # ----- Pathway: PNP (Provincial Nominee Program - BC / Alberta) -----
        # Employer-driven or Express Entry-aligned streams in other provinces.
        # Used as a fallback when Ontario is oversubscribed.
        pnp = Pathway(
            goal_id=goal.id,
            name="BC PNP / Alberta AAIP (Express Entry-aligned)",
            description="Provincial nomination via BC or Alberta EE-aligned streams (+600 CRS)",
            region="CA-BC",
            status=PathwayStatus.CANDIDATE.value,
            eligibility={
                "express_entry_profile": True,
                "min_crss": 300,
                "employer_offer": "preferred_not_required",
                "work_experience": "1 year skilled",
                "province_selection": "BC Tech Pilot or Alberta Express Entry",
            },
            milestones=[
                {"label": "Express Entry profile active", "due": "2026-12-15", "status": "pending"},
                {"label": "Provincial application strategy selected", "due": "2027-01-15", "status": "pending"},
                {"label": "Provincial application submitted", "due": "2027-04-01", "status": "pending"},
                {"label": "Provincial nomination received", "due": "2027-07-15", "status": "pending"},
                {"label": "ITA (600 CRS boost)", "due": "2027-09-01", "status": "pending"},
                {"label": "PR granted", "due": "2028-09-30", "status": "pending"},
            ],
        )
        db.add(pnp)
        db.flush()
        graph.upsert_pathway(pnp)
        log.info("seed.pathway.pnp", pathway_id=pnp.id)

        pnp_reqs = [
            Requirement(
                pathway_id=pnp.id, name="Express Entry Profile", type="other",
                description="Active EE profile required for EE-aligned PNP",
                threshold={"required": True},
                current_value={"active": False},
                gap_status="missing", weight=1.5,
            ),
            Requirement(
                pathway_id=pnp.id, name="Provincial Strategy Selection", type="other",
                description="Choose between BC Tech Pilot (tech occupation) or Alberta EE stream",
                threshold={"required": True},
                current_value={"selected": None},
                gap_status="missing", weight=1.0,
            ),
            Requirement(
                pathway_id=pnp.id, name="1 Year Skilled Work Experience", type="experience",
                description="NOC TEER 0/1/2/3, paid, within last 10 years",
                threshold={"min_years": 1, "noc": "TEER 0/1/2/3"},
                current_value={"years": 4, "noc": "TEER 1"},
                gap_status="met", weight=1.2,
            ),
            Requirement(
                pathway_id=pnp.id, name="Sufficient Settlement Funds", type="financial",
                description="Varies by province and family size (~CAD 15K-20K single)",
                threshold={"min_cad": 15000},
                current_value={"cad": 25000},
                gap_status="met", weight=0.8,
            ),
            Requirement(
                pathway_id=pnp.id, name="Language (CLB 6+)", type="language",
                description="Minimum CLB 6 for most PNP streams; CLB 7+ for BC Tech",
                threshold={"min": "CLB 6"},
                current_value={"clb": None},
                gap_status="missing", weight=1.0,
            ),
        ]
        for r in pnp_reqs:
            db.add(r)
            db.flush()
            graph.upsert_requirement(r)

        # ----- Pathway: CEC (Canadian Experience Class) -----
        # For workers with at least 1 year of Canadian skilled work experience.
        # No proof of funds required. Currently the user lacks Canadian
        # experience, so this is a longer-term fallback (e.g., via study→PGWP→CEC).
        cec = Pathway(
            goal_id=goal.id,
            name="Canadian Experience Class (CEC)",
            description="PR via 1+ year Canadian skilled work experience (Express Entry)",
            region="CA",
            status=PathwayStatus.CANDIDATE.value,
            eligibility={
                "canadian_work_exp": "1 year skilled (NOC TEER 0/1/2/3)",
                "work_exp_recency": "within last 3 years",
                "language_min": "CLB 7 (TEER 0/1) or CLB 5 (TEER 2/3)",
                "proof_of_funds": False,
                "education_min": "none_required",
            },
            milestones=[
                {"label": "Obtain Canadian work permit (PGWP or LMIA)", "due": "2027-06-01", "status": "pending"},
                {"label": "1 year Canadian work experience", "due": "2028-06-01", "status": "pending"},
                {"label": "Language test CLB 7+", "due": "2028-03-01", "status": "pending"},
                {"label": "Express Entry profile (CEC)", "due": "2028-07-15", "status": "pending"},
                {"label": "ITA received", "due": "2028-12-01", "status": "pending"},
                {"label": "PR granted", "due": "2029-06-30", "status": "pending"},
            ],
        )
        db.add(cec)
        db.flush()
        graph.upsert_pathway(cec)
        log.info("seed.pathway.cec", pathway_id=cec.id)

        cec_reqs = [
            Requirement(
                pathway_id=cec.id, name="1 Year Canadian Work Experience", type="experience",
                description="Skilled work in Canada (NOC TEER 0/1/2/3), paid, full-time equivalent",
                threshold={"min_years": 1, "location": "Canada", "noc": "TEER 0/1/2/3"},
                current_value={"years": 0},
                gap_status="missing", gap_delta=-1.0, weight=2.0,
            ),
            Requirement(
                pathway_id=cec.id, name="Canadian Work Permit", type="other",
                description="Valid work permit (PGWP after study, or LMIA-based)",
                threshold={"required": True},
                current_value={"held": False},
                gap_status="missing", weight=1.8,
            ),
            Requirement(
                pathway_id=cec.id, name="Language CLB 7+", type="language",
                description="CLB 7 for NOC TEER 0/1; CLB 5 for TEER 2/3",
                threshold={"min": "CLB 7"},
                current_value={"clb": None},
                gap_status="missing", weight=1.2,
            ),
            Requirement(
                pathway_id=cec.id, name="Work Experience Recency", type="experience",
                description="Canadian experience must be within the last 3 years",
                threshold={"recency_years": 3},
                current_value={"years": 0},
                gap_status="missing", weight=1.0,
            ),
        ]
        for r in cec_reqs:
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
                "crs_boost": 600,
            },
            impact_threshold=0.05,
        )
        db.add(retake)
        db.flush()
        graph.upsert_scenario(retake)

        # ----- Scenario: Study → PGWP → CEC (longer-term fallback) -----
        cec_scenario = Scenario(
            goal_id=goal.id,
            name="Study in Canada → PGWP → CEC",
            description="Enroll in a 1-year master's in Canada, get PGWP, accumulate 1 year Canadian experience, then apply via CEC",
            status=ScenarioStatus.DRAFT.value,
            parent_scenario_id=baseline.id,
            assumptions={
                "study_program": "1-year master in Canada",
                "pgwp_duration": "3 years",
                "canadian_work_years": 1,
                "pathway": "CEC",
                "timeline_months": 36,
                "proof_of_funds_required": False,
            },
            impact_threshold=0.05,
        )
        db.add(cec_scenario)
        db.flush()
        graph.upsert_scenario(cec_scenario)

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
        src3 = InformationSource(
            kind="official", title="OINP: 2026 intake allocations announced",
            url="https://www.ontario.ca/page/ontario-immigrant-nominee-program-oinp",
            publisher="Government of Ontario",
            published_at=datetime.now(timezone.utc) - timedelta(days=7),
            credibility="high", credibility_score=0.92,
            raw_text=(
                "Ontario received an allocation of 9,750 nominations for 2026. "
                "The Human Capital Priorities stream will continue issuing "
                "Notifications of Interest to Express Entry candidates with "
                "CRS 400+ and an active profile. Masters Graduate stream remains "
                "competitive."
            ),
        )
        src4 = InformationSource(
            kind="news", title="BC PNP Tech Pilot made permanent as Tech Priority",
            url="https://www.welcomebc.ca/",
            publisher="WelcomeBC",
            published_at=datetime.now(timezone.utc) - timedelta(days=21),
            credibility="medium", credibility_score=0.75,
            raw_text=(
                "British Columbia's Tech Pilot has been made permanent under the "
                "Tech Priority program. Tech workers with a job offer in an "
                "eligible occupation can apply for expedited BC PNP nomination, "
                "typically processed within 2-3 months."
            ),
        )
        db.add_all([src1, src2, src3, src4])
        db.flush()
        for s in (src1, src2, src3, src4):
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
        ev3 = Event(
            source_id=src3.id,
            subject="Ontario OINP", action="announced", object="2026 nomination allocations",
            occurred_at=datetime.now(timezone.utc) - timedelta(days=7),
            old_value=None, new_value={"allocations": 9750, "streams": ["HCP", "Masters", "PhD"]},
            risk_flag_level="low", risk_flag_type="policy",
            risk_flag_urgency="normal",
            extraction_confidence=0.9,
        )
        ev4 = Event(
            source_id=src4.id,
            subject="BC PNP", action="made permanent", object="Tech Priority stream",
            occurred_at=datetime.now(timezone.utc) - timedelta(days=21),
            old_value={"program": "Tech Pilot (temporary)"}, new_value={"program": "Tech Priority (permanent)"},
            risk_flag_level="low", risk_flag_type="policy",
            risk_flag_urgency="normal",
            extraction_confidence=0.85,
        )
        db.add_all([ev1, ev2, ev3, ev4])
        db.flush()
        for ev in (ev1, ev2, ev3, ev4):
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
            MetricSnapshot(
                source_id=src3.id, name="oinp_2026_allocations", region="CA-ON",
                value=9750, unit="nominations",
                captured_at=datetime.now(timezone.utc) - timedelta(days=7),
            ),
            MetricSnapshot(
                source_id=src4.id, name="bc_pnp_tech_processing_months", region="CA-BC",
                value=2.5, unit="months",
                captured_at=datetime.now(timezone.utc) - timedelta(days=21),
            ),
        ])

        # ----- Run baseline reasoning -----
        from app.services.scenarios import ScenarioService
        ScenarioService(db).run_reasoning(baseline.id)

        db.commit()
        log.info("seed.complete",
                 user_id=user.id, goal_id=goal.id,
                 pathways=4, requirements=len(reqs) + len(oinp_reqs) + len(pnp_reqs) + len(cec_reqs),
                 risk_factors=len(rfs), scenarios=3)

    except Exception as exc:  # noqa: BLE001
        db.rollback()
        log.error("seed.failed", error=str(exc))
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
