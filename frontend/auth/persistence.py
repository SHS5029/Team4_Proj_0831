"""Provider-neutral presentation state for identity persistence outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PersistenceState = Literal["saved", "unavailable", "failed", "blocked"]
FeedbackTone = Literal["success", "info", "warning", "error"]


@dataclass(frozen=True, slots=True)
class PersistenceResult:
    state: PersistenceState
    user_message: str


@dataclass(frozen=True, slots=True)
class PersistenceFeedback:
    tone: FeedbackTone
    retry_allowed: bool
    access_granted: bool


def should_refresh_persistence(
    cached_result: object,
    *,
    cached_identity_key: object,
    current_identity_key: str,
) -> bool:
    """Require a fresh DB authorization check after every successful result.

    Transient failures remain cached until the user explicitly retries. A saved
    result is never treated as durable authorization because the local account
    may have been disabled since the previous Streamlit rerun.
    """

    return (
        cached_identity_key != current_identity_key
        or not isinstance(cached_result, PersistenceResult)
        or cached_result.state == "saved"
    )


def persistence_feedback(result: PersistenceResult) -> PersistenceFeedback:
    """Translate a domain outcome into UI behavior without importing Streamlit."""

    if result.state == "saved":
        return PersistenceFeedback(
            tone="success",
            retry_allowed=False,
            access_granted=True,
        )
    if result.state == "unavailable":
        return PersistenceFeedback(
            tone="info",
            retry_allowed=False,
            access_granted=False,
        )
    if result.state == "blocked":
        return PersistenceFeedback(
            tone="error",
            retry_allowed=False,
            access_granted=False,
        )
    return PersistenceFeedback(
        tone="warning",
        retry_allowed=True,
        access_granted=False,
    )
