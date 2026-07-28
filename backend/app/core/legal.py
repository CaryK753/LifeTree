"""Current legal-document versions used by account registration."""

from __future__ import annotations

TERMS_VERSION = "2026-07-28"
PRIVACY_VERSION = "2026-07-28"


def is_current_consent(
    accepted_terms: bool,
    terms_version: str,
    privacy_version: str,
) -> bool:
    """Return whether a registration accepted the currently published text."""
    return (
        accepted_terms
        and terms_version == TERMS_VERSION
        and privacy_version == PRIVACY_VERSION
    )
