"""Phase 4 multi-scenario expansion: Australia & UK study-abroad seed data.

Adds two new goals to demonstrate LifeTree's ability to model immigration
scenarios beyond Canada:
  1. Australia: Study → Temporary Graduate (485) → Skilled PR (189/190/491)
  2. UK: Study → Graduate Route → Skilled Worker Visa

Run via:  python scripts/seed_study_abroad.py

This script is idempotent — it skips goals that already exist (matched by
title) so re-running won't create duplicates.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.logging import configure_logging, get_logger  # noqa: E402
from app.core.tenant import DEFAULT_USER_ID  # noqa: E402
from app.db.postgres import SessionLocal  # noqa: E402
from app.models.event import Event, InformationSource, MetricSnapshot  # noqa: E402
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

NOW = datetime.now(timezone.utc)


def _seed_australia(db, graph, user: UserProfile) -> None:
    """Australia: Study → 485 Graduate → 189/190/491 Skilled PR."""

    # Skip if already seeded (idempotent).
    existing = db.query(Goal).filter(Goal.title.like("Obtain Australian PR%")).first()
    if existing:
        log.info("seed.au.skip", goal_id=existing.id)
        return

    goal = Goal(
        user_id=user.id,
        title="Obtain Australian PR via Study Pathway",
        description="Enroll in an Australian master's program, use Subclass 485 for post-study work, then transition to skilled PR",
        scenario="au_study_pr",
        target_date=date.today().replace(year=date.today().year + 4),
        status=GoalStatus.ACTIVE.value,
        meta={"region": "AU", "program": "Student Visa → 485 → 189/190/491"},
    )
    db.add(goal)
    db.flush()
    graph.upsert_goal(goal)
    log.info("seed.au.goal", goal_id=goal.id)

    # ----- Pathway: Subclass 500 (Student Visa) -----
    student_500 = Pathway(
        goal_id=goal.id,
        name="Subclass 500 (Student Visa)",
        description="Study a master's degree in Australia (2-3 years)",
        region="AU",
        status=PathwayStatus.SELECTED.value,
        eligibility={
            "acceptance": "CoE from CRICOS-registered institution",
            "gte_requirement": "Genuine Temporary Entrant",
            "financial_capacity": "AUD 21,041/year living costs",
            "oshc": "Overseas Student Health Cover required",
            "english": "IELTS 6.0+ (varies by institution)",
        },
        milestones=[
            {"label": "IELTS/PTE test", "due": "2027-03-01", "status": "pending"},
            {"label": "University application & CoE", "due": "2027-06-01", "status": "pending"},
            {"label": "OSHC purchased", "due": "2027-07-01", "status": "pending"},
            {"label": "Subclass 500 visa granted", "due": "2027-08-15", "status": "pending"},
            {"label": "Arrive & commence studies", "due": "2027-09-01", "status": "pending"},
            {"label": "Degree completed", "due": "2029-12-01", "status": "pending"},
        ],
    )
    db.add(student_500)
    db.flush()
    graph.upsert_pathway(student_500)

    for r in [
        Requirement(
            pathway_id=student_500.id, name="IELTS Academic 6.5+", type="language",
            description="Most master's programs require IELTS 6.5 (no band < 6.0)",
            threshold={"min": 6.5, "min_per_band": 6.0},
            current_value={"overall": None},
            gap_status="missing", weight=1.5,
        ),
        Requirement(
            pathway_id=student_500.id, name="Confirmation of Enrolment (CoE)", type="education",
            description="Acceptance from a CRICOS-registered Australian institution",
            threshold={"required": True},
            current_value={"issued": False},
            gap_status="missing", weight=2.0,
        ),
        Requirement(
            pathway_id=student_500.id, name="Financial Capacity (AUD)", type="financial",
            description="AUD 21,041/year living + tuition + travel",
            threshold={"min_aud": 21041},
            current_value={"aud": 25000},
            gap_status="met", weight=1.0,
        ),
        Requirement(
            pathway_id=student_500.id, name="Overseas Student Health Cover (OSHC)", type="health",
            description="Mandatory health insurance for the duration of the visa",
            threshold={"required": True},
            current_value={"purchased": False},
            gap_status="missing", weight=0.8,
        ),
        Requirement(
            pathway_id=student_500.id, name="Genuine Temporary Entrant (GTE)", type="legal",
            description="Statement demonstrating temporary stay intention",
            threshold={"required": True},
            current_value={"submitted": False},
            gap_status="missing", weight=1.2,
        ),
    ]:
        db.add(r)
        db.flush()
        graph.upsert_requirement(r)

    # ----- Pathway: Subclass 485 (Temporary Graduate) -----
    grad_485 = Pathway(
        goal_id=goal.id,
        name="Subclass 485 (Temporary Graduate)",
        description="Post-study work rights: 2-4 years in Australia after graduation",
        region="AU",
        status=PathwayStatus.CANDIDATE.value,
        eligibility={
            "qualification": "Australian degree/diploma (CRICOS)",
            "study_duration": ">= 92 weeks (2 academic years)",
            "age": "< 50 at application",
            "english": "IELTS 6.0 (or equivalent)",
            "health_insurance": "OSHC required",
        },
        milestones=[
            {"label": "Degree completed (CRICOS)", "due": "2029-12-01", "status": "pending"},
            {"label": "Skills assessment obtained", "due": "2030-01-15", "status": "pending"},
            {"label": "Subclass 485 lodged", "due": "2030-02-01", "status": "pending"},
            {"label": "485 visa granted", "due": "2030-05-01", "status": "pending"},
            {"label": "Skilled work experience (1 year)", "due": "2031-05-01", "status": "pending"},
        ],
    )
    db.add(grad_485)
    db.flush()
    graph.upsert_pathway(grad_485)

    for r in [
        Requirement(
            pathway_id=grad_485.id, name="Australian Qualification", type="education",
            description="Completed Australian degree from a CRICOS institution (≥92 weeks study)",
            threshold={"min_weeks": 92, "institution": "CRICOS"},
            current_value={"completed": False},
            gap_status="missing", gap_delta=-2.0, weight=2.0,
        ),
        Requirement(
            pathway_id=grad_485.id, name="Skills Assessment", type="other",
            description="Positive skills assessment from relevant authority (e.g., ACS, VETASSESS, Engineers Australia)",
            threshold={"required": True},
            current_value={"obtained": False},
            gap_status="missing", weight=1.5,
        ),
        Requirement(
            pathway_id=grad_485.id, name="Age < 50", type="other",
            description="Must be under 50 at time of application",
            threshold={"max_age": 50},
            current_value={"age": 32},
            gap_status="met", weight=0.5,
        ),
        Requirement(
            pathway_id=grad_485.id, name="English IELTS 6.0+", type="language",
            description="Functional English requirement",
            threshold={"min": 6.0},
            current_value={"overall": None},
            gap_status="missing", weight=1.0,
        ),
    ]:
        db.add(r)
        db.flush()
        graph.upsert_requirement(r)

    # ----- Pathway: Subclass 189 (Skilled Independent) -----
    skilled_189 = Pathway(
        goal_id=goal.id,
        name="Subclass 189 (Skilled Independent PR)",
        description="Points-tested permanent visa, no sponsor required (requires 65+ points)",
        region="AU",
        status=PathwayStatus.CANDIDATE.value,
        eligibility={
            "points_min": 65,
            "occupation": "on Medium and Long-term Strategic Skills List (MLTSSL)",
            "skills_assessment": "positive assessment from relevant authority",
            "age": "< 45",
            "english": "Competent (IELTS 6.0) or above",
        },
        milestones=[
            {"label": "Skills assessment", "due": "2030-01-15", "status": "pending"},
            {"label": "EOI submitted (SkillSelect)", "due": "2031-03-01", "status": "pending"},
            {"label": "Invitation to apply", "due": "2031-09-01", "status": "pending"},
            {"label": "Subclass 189 lodged", "due": "2031-10-01", "status": "pending"},
            {"label": "PR granted", "due": "2032-06-01", "status": "pending"},
        ],
    )
    db.add(skilled_189)
    db.flush()
    graph.upsert_pathway(skilled_189)

    for r in [
        Requirement(
            pathway_id=skilled_189.id, name="Points Score >= 65", type="other",
            description="Points from age, English, education, experience, etc. Competitive cutoffs often 80-90+",
            threshold={"min": 65, "competitive": 85},
            current_value={"estimated": 60},
            gap_status="partial", gap_delta=-25.0, weight=2.0,
        ),
        Requirement(
            pathway_id=skilled_189.id, name="Occupation on MLTSSL", type="other",
            description="Nominated occupation must be on the Medium and Long-term Strategic Skills List",
            threshold={"required": True},
            current_value={"nominated": None},
            gap_status="missing", weight=1.8,
        ),
        Requirement(
            pathway_id=skilled_189.id, name="Skills Assessment", type="other",
            description="Positive skills assessment from the relevant assessing authority",
            threshold={"required": True},
            current_value={"obtained": False},
            gap_status="missing", weight=1.5,
        ),
        Requirement(
            pathway_id=skilled_189.id, name="Age < 45", type="other",
            description="Must be under 45 at time of invitation",
            threshold={"max_age": 45},
            current_value={"age": 34},
            gap_status="met", weight=0.8,
        ),
    ]:
        db.add(r)
        db.flush()
        graph.upsert_requirement(r)

    # ----- Risk Factors -----
    for rf in [
        RiskFactor(
            type="policy", name="Australia Immigration Policy Changes",
            description="Migration strategy reviews and occupation list updates",
            region="AU", level="medium", urgency="normal",
            probability=0.5, impact=0.5, half_life_days=365,
        ),
        RiskFactor(
            type="economic", name="AUD/CNY Exchange Volatility",
            description="FX swings affecting tuition and living costs",
            region="AU", level="low", urgency="normal",
            probability=0.4, impact=0.3, half_life_days=180,
        ),
    ]:
        db.add(rf)
        db.flush()
        graph.upsert_risk_factor(rf)

    # ----- Scenarios -----
    baseline = Scenario(
        goal_id=goal.id,
        name="Baseline (Study → 485 → 189)",
        description="Current trajectory: complete master's, use 485 for work, apply for 189 PR",
        status=ScenarioStatus.ACTIVE.value,
        assumptions={
            "study_program": "2-year master in IT",
            "points_estimated": 60,
            "points_target": 85,
            "pathway": "189",
        },
        impact_threshold=0.05,
    )
    db.add(baseline)
    db.flush()
    graph.upsert_scenario(baseline)

    state_nominated = Scenario(
        goal_id=goal.id,
        name="State Nomination (Subclass 190)",
        description="Pursue state nomination for 5 extra points + priority processing",
        status=ScenarioStatus.DRAFT.value,
        parent_scenario_id=baseline.id,
        assumptions={
            "pathway": "190",
            "state_nomination": True,
            "points_boost": 5,
            "state": "NSW or Victoria",
        },
        impact_threshold=0.05,
    )
    db.add(state_nominated)
    db.flush()
    graph.upsert_scenario(state_nominated)

    regional = Scenario(
        goal_id=goal.id,
        name="Regional Pathway (Subclass 491)",
        description="Skilled Work Regional visa — 491 (provisional) → 191 (PR after 3 years)",
        status=ScenarioStatus.DRAFT.value,
        parent_scenario_id=baseline.id,
        assumptions={
            "pathway": "491",
            "regional_sponsorship": True,
            "points_boost": 15,
            "timeline_years": 5,
        },
        impact_threshold=0.05,
    )
    db.add(regional)
    db.flush()
    graph.upsert_scenario(regional)

    # ----- Sources & Events -----
    au_src1 = InformationSource(
        kind="official", title="Department of Home Affairs: Skilled Migration Updates",
        url="https://immi.homeaffairs.gov.au/",
        publisher="Australian Government — Home Affairs",
        published_at=NOW - timedelta(days=10),
        credibility="high", credibility_score=0.95,
        raw_text=(
            "The Department of Home Affairs has released updated occupation lists for "
            "the 2026-27 migration program. Key changes include additions to the MLTSSL "
            "in the IT and healthcare sectors. The minimum points threshold for Subclass "
            "189 invitations remains at 65, but competitive cutoffs are 85+."
        ),
    )
    au_src2 = InformationSource(
        kind="news", title="Study Australia: 2026 intake data released",
        url="https://www.studyaustralia.gov.au/",
        publisher="Study Australia",
        published_at=NOW - timedelta(days=5),
        credibility="medium", credibility_score=0.75,
        raw_text=(
            "Australian universities report strong international enrollment for the 2026 "
            "intake. Post-study work rights remain at 2-4 years for master's graduates "
            "via Subclass 485. Applications for IT and engineering programs are particularly "
            "competitive."
        ),
    )
    db.add_all([au_src1, au_src2])
    db.flush()
    for s in (au_src1, au_src2):
        graph.upsert_source(s)

    db.add_all([
        Event(
            source_id=au_src1.id,
            subject="Home Affairs", action="updated", object="MLTSSL occupation list",
            occurred_at=NOW - timedelta(days=10),
            old_value=None, new_value={"added": ["261312", "263111"], "removed": []},
            risk_flag_level="low", risk_flag_type="policy",
            extraction_confidence=0.92,
        ),
        Event(
            source_id=au_src2.id,
            subject="Australian universities", action="reported",
            object="2026 international enrollment",
            occurred_at=NOW - timedelta(days=5),
            old_value=None, new_value={"intake": "strong", "competitive_sectors": ["IT", "engineering"]},
            risk_flag_level="low", risk_flag_type="economic",
            extraction_confidence=0.8,
        ),
        MetricSnapshot(
            source_id=au_src1.id, name="au_189_competitive_cutoff", region="AU",
            value=85, unit="points",
            captured_at=NOW - timedelta(days=10),
        ),
        MetricSnapshot(
            name="au_living_cost_aud_year", region="AU",
            value=21041, unit="AUD",
            captured_at=NOW,
        ),
    ])

    log.info("seed.au.complete", goal_id=goal.id, pathways=3, scenarios=3)


def _seed_uk(db, graph, user: UserProfile) -> None:
    """UK: Study → Graduate Route → Skilled Worker Visa."""

    existing = db.query(Goal).filter(Goal.title.like("Obtain UK PR%")).first()
    if existing:
        log.info("seed.uk.skip", goal_id=existing.id)
        return

    goal = Goal(
        user_id=user.id,
        title="Obtain UK PR via Study & Work Pathway",
        description="Study a master's in the UK, use Graduate Route for post-study work, then transition to Skilled Worker Visa and ILR",
        scenario="uk_study_pr",
        target_date=date.today().replace(year=date.today().year + 6),
        status=GoalStatus.ACTIVE.value,
        meta={"region": "UK", "program": "Student Visa → Graduate Route → Skilled Worker → ILR"},
    )
    db.add(goal)
    db.flush()
    graph.upsert_goal(goal)
    log.info("seed.uk.goal", goal_id=goal.id)

    # ----- Pathway: Student Visa -----
    student_uk = Pathway(
        goal_id=goal.id,
        name="UK Student Visa",
        description="Study a master's degree at a UK university (1-2 years)",
        region="UK",
        status=PathwayStatus.SELECTED.value,
        eligibility={
            "acceptance": "unconditional offer from licensed sponsor (university)",
            "financial": "GBP 1,334/month (London) or GBP 1,023/month (outside London)",
            "english": "CEFR B2 (IELTS 5.5-6.5 depending on course)",
            "tuberculosis": "required for some countries",
        },
        milestones=[
            {"label": "IELTS/TOEFL test", "due": "2027-03-01", "status": "pending"},
            {"label": "University application & offer", "due": "2027-05-01", "status": "pending"},
            {"label": "CAS issued", "due": "2027-07-01", "status": "pending"},
            {"label": "Student visa granted", "due": "2027-08-15", "status": "pending"},
            {"label": "Arrive & commence studies", "due": "2027-09-01", "status": "pending"},
            {"label": "Degree completed", "due": "2028-09-01", "status": "pending"},
        ],
    )
    db.add(student_uk)
    db.flush()
    graph.upsert_pathway(student_uk)

    for r in [
        Requirement(
            pathway_id=student_uk.id, name="IELTS Academic 6.5+", type="language",
            description="Most UK master's programs require IELTS 6.5 (no band < 6.0)",
            threshold={"min": 6.5, "min_per_band": 6.0},
            current_value={"overall": None},
            gap_status="missing", weight=1.5,
        ),
        Requirement(
            pathway_id=student_uk.id, name="Confirmation of Acceptance for Studies (CAS)", type="education",
            description="CAS from a UK university with a Student Sponsor license",
            threshold={"required": True},
            current_value={"issued": False},
            gap_status="missing", weight=2.0,
        ),
        Requirement(
            pathway_id=student_uk.id, name="Financial Proof (GBP)", type="financial",
            description="GBP 1,334/month (London) or GBP 1,023/month (outside London) for up to 9 months",
            threshold={"min_gbp_london": 12006, "min_gbp_other": 9207},
            current_value={"gbp": 14000},
            gap_status="met", weight=1.0,
        ),
    ]:
        db.add(r)
        db.flush()
        graph.upsert_requirement(r)

    # ----- Pathway: Graduate Route -----
    grad_uk = Pathway(
        goal_id=goal.id,
        name="UK Graduate Route Visa",
        description="2-year post-study work rights (3 years for PhD graduates)",
        region="UK",
        status=PathwayStatus.CANDIDATE.value,
        eligibility={
            "qualification": "UK degree from a Student Sponsor institution",
            "study_location": "must have studied in the UK",
            "application_timing": "before Student Visa expires",
            "english": "already met via degree",
        },
        milestones=[
            {"label": "Degree completed", "due": "2028-09-01", "status": "pending"},
            {"label": "Graduate Route visa applied", "due": "2028-10-01", "status": "pending"},
            {"label": "Graduate visa granted (2 years)", "due": "2028-11-15", "status": "pending"},
            {"label": "Skilled job secured", "due": "2029-06-01", "status": "pending"},
        ],
    )
    db.add(grad_uk)
    db.flush()
    graph.upsert_pathway(grad_uk)

    for r in [
        Requirement(
            pathway_id=grad_uk.id, name="UK Qualification", type="education",
            description="Completed a UK bachelor's or master's degree from a licensed Student Sponsor",
            threshold={"required": True, "location": "UK"},
            current_value={"completed": False},
            gap_status="missing", gap_delta=-1.0, weight=2.0,
        ),
        Requirement(
            pathway_id=grad_uk.id, name="Valid Student Visa at Application", type="legal",
            description="Must apply before current Student Visa expires, while in the UK",
            threshold={"required": True},
            current_value={"held": False},
            gap_status="missing", weight=1.5,
        ),
    ]:
        db.add(r)
        db.flush()
        graph.upsert_requirement(r)

    # ----- Pathway: Skilled Worker Visa -----
    skilled_uk = Pathway(
        goal_id=goal.id,
        name="UK Skilled Worker Visa (→ ILR)",
        description="Employer-sponsored work visa; leads to Indefinite Leave to Remain after 5 years",
        region="UK",
        status=PathwayStatus.CANDIDATE.value,
        eligibility={
            "job_offer": "from a licensed UK employer (sponsor)",
            "skill_level": "RQF Level 3+ (A-level equivalent)",
            "salary_min": "GBP 38,700/year (general threshold, Apr 2024)",
            "english": "CEFR B1 (IELTS 4.0)",
            "points": "50 points (sponsor + job + English)",
        },
        milestones=[
            {"label": "Skilled job secured (sponsor)", "due": "2029-06-01", "status": "pending"},
            {"label": "Certificate of Sponsorship (CoS)", "due": "2029-07-01", "status": "pending"},
            {"label": "Skilled Worker visa granted", "due": "2029-09-01", "status": "pending"},
            {"label": "5 years on Skilled Worker", "due": "2034-09-01", "status": "pending"},
            {"label": "ILR application", "due": "2034-10-01", "status": "pending"},
            {"label": "ILR granted (PR)", "due": "2035-01-01", "status": "pending"},
        ],
    )
    db.add(skilled_uk)
    db.flush()
    graph.upsert_pathway(skilled_uk)

    for r in [
        Requirement(
            pathway_id=skilled_uk.id, name="Job Offer from Licensed Sponsor", type="experience",
            description="Must have a job offer from a UK employer with a Skilled Worker sponsor license",
            threshold={"required": True},
            current_value={"secured": False},
            gap_status="missing", weight=2.0,
        ),
        Requirement(
            pathway_id=skilled_uk.id, name="Salary >= GBP 38,700", type="financial",
            description="General salary threshold (lower for new entrants and some occupations)",
            threshold={"min_gbp": 38700},
            current_value={"estimated_gbp": None},
            gap_status="missing", weight=1.5,
        ),
        Requirement(
            pathway_id=skilled_uk.id, name="English CEFR B1", type="language",
            description="IELTS 4.0 overall (or degree taught in English)",
            threshold={"min": "B1"},
            current_value={"level": None},
            gap_status="missing", weight=1.0,
        ),
        Requirement(
            pathway_id=skilled_uk.id, name="5 Years UK Residence", type="legal",
            description="Must complete 5 years on Skilled Worker visa before ILR eligibility",
            threshold={"min_years": 5},
            current_value={"years": 0},
            gap_status="missing", gap_delta=-5.0, weight=1.8,
        ),
    ]:
        db.add(r)
        db.flush()
        graph.upsert_requirement(r)

    # ----- Risk Factors -----
    for rf in [
        RiskFactor(
            type="policy", name="UK Immigration Salary Threshold Changes",
            description="Salary threshold raised to GBP 38,700 in April 2024; further changes possible",
            region="UK", level="medium", urgency="elevated",
            probability=0.6, impact=0.5, half_life_days=365,
        ),
        RiskFactor(
            type="economic", name="GBP/CNY Exchange & Cost of Living",
            description="London cost of living and tuition fees may strain finances",
            region="UK", level="medium", urgency="normal",
            probability=0.5, impact=0.4, half_life_days=180,
        ),
        RiskFactor(
            type="political", name="UK Government Immigration Policy Shifts",
            description="Post-election immigration policies may alter visa routes",
            region="UK", level="low", urgency="normal",
            probability=0.3, impact=0.5, half_life_days=365,
        ),
    ]:
        db.add(rf)
        db.flush()
        graph.upsert_risk_factor(rf)

    # ----- Scenarios -----
    baseline = Scenario(
        goal_id=goal.id,
        name="Baseline (Study → Graduate → Skilled Worker → ILR)",
        description="Current trajectory: 1-year master's, 2-year graduate route, 5-year skilled worker, then ILR",
        status=ScenarioStatus.ACTIVE.value,
        assumptions={
            "study_duration_years": 1,
            "graduate_route_years": 2,
            "skilled_worker_years": 5,
            "total_timeline_years": 8,
        },
        impact_threshold=0.05,
    )
    db.add(baseline)
    db.flush()
    graph.upsert_scenario(baseline)

    global_talent = Scenario(
        goal_id=goal.id,
        name="Global Talent Visa Fast-Track",
        description="If exceptional talent in tech/digital, apply for Global Talent Visa (5-year route to ILR, no sponsor needed)",
        status=ScenarioStatus.DRAFT.value,
        parent_scenario_id=baseline.id,
        assumptions={
            "pathway": "global_talent",
            "endorsement": "Tech Nation endorsement",
            "no_sponsor_needed": True,
            "ilr_years": 3,
        },
        impact_threshold=0.05,
    )
    db.add(global_talent)
    db.flush()
    graph.upsert_scenario(global_talent)

    # ----- Sources & Events -----
    uk_src1 = InformationSource(
        kind="official", title="UK Home Office: Immigration Rules Update",
        url="https://www.gov.uk/government/organisations/home-office",
        publisher="UK Home Office",
        published_at=NOW - timedelta(days=12),
        credibility="high", credibility_score=0.93,
        raw_text=(
            "The general salary threshold for Skilled Worker visas remains at GBP 38,700 "
            "as of April 2024. New entrants can claim a 20% discount on the threshold. "
            "The Graduate Route remains unchanged at 2 years for master's graduates."
        ),
    )
    uk_src2 = InformationSource(
        kind="news", title="QS World University Rankings: UK Universities 2026",
        url="https://www.topuniversities.com/",
        publisher="QS Quacquarelli Symonds",
        published_at=NOW - timedelta(days=8),
        credibility="medium", credibility_score=0.7,
        raw_text=(
            "UK universities continue to dominate global rankings, with Oxford, Cambridge, "
            "Imperial, and UCL in the top 10. Applications for 2026 entry are competitive, "
            "especially for computer science and engineering programs. Early application "
            "is recommended for international students."
        ),
    )
    db.add_all([uk_src1, uk_src2])
    db.flush()
    for s in (uk_src1, uk_src2):
        graph.upsert_source(s)

    db.add_all([
        Event(
            source_id=uk_src1.id,
            subject="UK Home Office", action="confirmed",
            object="Graduate Route remains 2 years",
            occurred_at=NOW - timedelta(days=12),
            old_value=None, new_value={"graduate_route_years": 2, "salary_threshold_gbp": 38700},
            risk_flag_level="low", risk_flag_type="policy",
            extraction_confidence=0.9,
        ),
        Event(
            source_id=uk_src2.id,
            subject="QS Rankings", action="published",
            object="2026 university rankings",
            occurred_at=NOW - timedelta(days=8),
            old_value=None, new_value={"uk_top10": 4, "competitive_fields": ["CS", "engineering"]},
            risk_flag_level="low", risk_flag_type="economic",
            extraction_confidence=0.85,
        ),
        MetricSnapshot(
            source_id=uk_src1.id, name="uk_skilled_worker_salary_threshold", region="UK",
            value=38700, unit="GBP",
            captured_at=NOW - timedelta(days=12),
        ),
        MetricSnapshot(
            name="uk_living_cost_gbp_month_london", region="UK",
            value=1334, unit="GBP",
            captured_at=NOW,
        ),
    ])

    log.info("seed.uk.complete", goal_id=goal.id, pathways=3, scenarios=2)


def seed() -> None:
    configure_logging("INFO")
    db = SessionLocal()
    graph = GraphService()
    try:
        user = db.get(UserProfile, DEFAULT_USER_ID)
        if user is None:
            log.warning("seed_study_abroad.no_user", user_id=DEFAULT_USER_ID)
            log.warning("Run seed_fsw.py first to create the default user.")
            return

        _seed_australia(db, graph, user)
        _seed_uk(db, graph, user)

        db.commit()
        log.info("seed_study_abroad.complete")

    except Exception as exc:  # noqa: BLE001
        db.rollback()
        log.error("seed_study_abroad.failed", error=str(exc))
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
