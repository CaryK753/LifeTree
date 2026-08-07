"""SQLAlchemy ORM model registry.

Importing this package ensures every model is registered on Base.metadata
before Alembic or service code touches it.
"""

from app.models.action import Action, ActionStatus
from app.models.chat_stream import ChatStream
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
from app.models.intelligence import (
    CalibrationReport,
    ConflictResolution,
    EvolutionMilestone,
    RiskProposal,
    SourceAccuracyLog,
)
from app.models.llm_config import (
    AppConfig,
    LLMModel,
    LLMProvider,
)
from app.models.memory import UserMemory
from app.models.model_params import ModelParam, PredictionOutcome
from app.models.notification import (
    NotificationChannel,
    NotificationLog,
    NotificationStatus,
    RiskAssessment,
    RiskPropagationLog,
    WebPushSubscription,
)
from app.models.research import ResearchJob, ResearchStatus
from app.models.scenario import (
    Scenario,
    ScenarioRun,
    ScenarioStatus,
)
from app.models.source_proposal import SourceProposal
from app.models.user import (
    RiskTolerance,
    UserProfile,
    UserUpload,
)
from app.models.user_oauth_link import UserOAuthLink
from app.models.user_passkey import UserPasskey
from app.models.user_plugin import UserPlugin
from app.models.user_runtime import UserMCPServer, UserServiceConfig, UserSkill

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
    # Actions
    "Action",
    "ActionStatus",
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
    # Model params & prediction outcomes (缺口 G)
    "ModelParam",
    "PredictionOutcome",
    "CalibrationReport",
    "ConflictResolution",
    "EvolutionMilestone",
    "RiskProposal",
    "SourceAccuracyLog",
    # Users
    "UserProfile",
    "UserUpload",
    "RiskTolerance",
    "UserMemory",
    "UserPlugin",
    "UserOAuthLink",
    "UserPasskey",
    "UserServiceConfig",
    "UserMCPServer",
    "UserSkill",
    # Notifications / risk
    "NotificationLog",
    "NotificationChannel",
    "NotificationStatus",
    "RiskAssessment",
    "RiskPropagationLog",
    "WebPushSubscription",
    # LLM config
    "LLMProvider",
    "LLMModel",
    "AppConfig",
    # Source auto-discovery (P1)
    "SourceProposal",
    # Deep research (§C.1)
    "ResearchJob",
    "ResearchStatus",
    # Chat streams (background chat execution)
    "ChatStream",
]
