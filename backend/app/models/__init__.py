"""SQLAlchemy ORM model registry.

Importing this package ensures every model is registered on Base.metadata
before Alembic or service code touches it.
"""

from app.models.event import (
    Assertion,
    Event,
    EventFingerprint,
    InformationSource,
    MetricSnapshot,
    Relationship,
)
from app.models.goal import (
    Goal,
    GoalStatus,
    Pathway,
    PathwayStatus,
    Requirement,
    RequirementType,
    RiskFactor,
    RiskFactorType,
)
from app.models.llm_config import (
    AppConfig,
    LLMModel,
    LLMProvider,
)
from app.models.memory import UserMemory
from app.models.notification import (
    NotificationChannel,
    NotificationLog,
    NotificationStatus,
    RiskAssessment,
    RiskPropagationLog,
)
from app.models.scenario import (
    Scenario,
    ScenarioRun,
    ScenarioStatus,
)
from app.models.user import (
    RiskTolerance,
    UserProfile,
    UserUpload,
)

__all__ = [
    # Goal ontology
    "Goal",
    "GoalStatus",
    "Pathway",
    "PathwayStatus",
    "Requirement",
    "RequirementType",
    "RiskFactor",
    "RiskFactorType",
    # Events
    "Event",
    "EventFingerprint",
    "MetricSnapshot",
    "Assertion",
    "Relationship",
    "InformationSource",
    # Scenarios
    "Scenario",
    "ScenarioRun",
    "ScenarioStatus",
    # Users
    "UserProfile",
    "UserUpload",
    "RiskTolerance",
    "UserMemory",
    # Notifications / risk
    "NotificationLog",
    "NotificationChannel",
    "NotificationStatus",
    "RiskAssessment",
    "RiskPropagationLog",
    # LLM config
    "LLMProvider",
    "LLMModel",
    "AppConfig",
]
