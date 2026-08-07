"""Domain-aware engine recommendation.

Maps a query's subject matter to the engines that cover it best, enabling
cross-domain cross-validation: the same fact retrieved from different
domain engines (official + academic + Chinese news) carries more
independent-verification weight than the same fact from one engine.

Design doc: docs/specs/2026-08-07-...md §A.7
"""

from __future__ import annotations

import re

from app.core.logging import get_logger
from app.services.search_engines.base import SearchEngine

log = get_logger(__name__)

# Keyword heuristics for domain detection
_CHINA_POLICY_KEYWORDS = re.compile(
    r"政策|规定|办法|条例|公告|通知|移民|签证|居留|落户|积分|"
    r"中介|论坛|知乎|小红书|微信公众号",
    re.IGNORECASE,
)
_ACADEMIC_KEYWORDS = re.compile(
    r"论文|研究|paper|research|study|DOI|correlation|"
    r"statistics|学术|期刊|journal|university|论文",
    re.IGNORECASE,
)
_VERTICAL_KEYWORDS = re.compile(
    r"配额|quota|利率|汇率|stock|financial|金融|"
    r"data|数据|统计|statistical|报告|report",
    re.IGNORECASE,
)
_OFFICIAL_KEYWORDS = re.compile(
    r"official|官方|政府|government|regulation|law|法规|"
    r"IRCC|USCIS|ministry|department",
    re.IGNORECASE,
)

# Engine priority by domain
_DOMAIN_ENGINE_MAP: dict[str, list[str]] = {
    "china_policy": ["bocha", "tavily"],
    "academic": ["exa", "tavily"],
    "vertical": ["anysearch", "tavily"],
    "official": ["tavily", "anysearch"],
    "general": ["tavily"],
}


def detect_domains(query: str) -> list[str]:
    """Detect which domains a query likely belongs to."""
    domains: list[str] = []
    if _CHINA_POLICY_KEYWORDS.search(query):
        domains.append("china_policy")
    if _ACADEMIC_KEYWORDS.search(query):
        domains.append("academic")
    if _VERTICAL_KEYWORDS.search(query):
        domains.append("vertical")
    if _OFFICIAL_KEYWORDS.search(query):
        domains.append("official")
    if not domains:
        domains.append("general")
    return domains


def recommend_engines(
    query: str,
    scope: dict | None = None,
    *,
    available_engines: list[str] | None = None,
    cross_validate: bool = False,
) -> list[str]:
    """Recommend engine combinations for a query.

    Args:
        query: The search query text.
        scope: Optional scope dict (e.g. {"goal_id": ..., "region": ...}).
        available_engines: Engines the user has keys for. If None, all engines
            are considered available (caller should filter).
        cross_validate: If True, return 2-3 engines from different domains
            for cross-validation. If False, return the single best engine.

    Returns:
        List of engine names, filtered by available_engines.
    """
    domains = detect_domains(query)

    # Collect candidate engines from detected domains
    candidates: list[str] = []
    for d in domains:
        for e in _DOMAIN_ENGINE_MAP.get(d, ["tavily"]):
            if e not in candidates:
                candidates.append(e)

    # Filter by availability
    if available_engines:
        candidates = [e for e in candidates if e in available_engines]
    if not candidates:
        candidates = ["tavily"]

    if not cross_validate:
        return candidates[:1]

    # Cross-validation: ensure at least 2 different-domain engines
    if len(candidates) < 2 and "tavily" not in candidates:
        candidates.append("tavily")
    # Cap at 3 for cost control
    return candidates[:3]
