from auth.persistence import (
    PersistenceResult,
    persistence_feedback,
    should_refresh_persistence,
)


def test_blocked_account_is_an_error_without_retry() -> None:
    result = PersistenceResult(
        state="blocked",
        user_message="비활성화된 계정입니다. 관리자에게 문의해 주세요.",
    )

    feedback = persistence_feedback(result)

    assert feedback.tone == "error"
    assert feedback.retry_allowed is False
    assert feedback.access_granted is False


def test_transient_persistence_failure_can_be_retried() -> None:
    result = PersistenceResult(state="failed", user_message="저장하지 못했어요.")

    feedback = persistence_feedback(result)

    assert feedback.tone == "warning"
    assert feedback.retry_allowed is True
    assert feedback.access_granted is False


def test_only_a_saved_active_user_receives_application_access() -> None:
    result = PersistenceResult(state="saved", user_message="저장됐어요.")

    feedback = persistence_feedback(result)

    assert feedback.tone == "success"
    assert feedback.access_granted is True


def test_saved_result_is_revalidated_for_the_same_identity_on_every_rerun() -> None:
    cached_result = PersistenceResult(state="saved", user_message="저장됐어요.")

    assert should_refresh_persistence(
        cached_result,
        cached_identity_key="google:subject",
        current_identity_key="google:subject",
    ) is True


def test_failed_result_remains_cached_until_retry_for_the_same_identity() -> None:
    cached_result = PersistenceResult(state="failed", user_message="실패했어요.")

    assert should_refresh_persistence(
        cached_result,
        cached_identity_key="google:subject",
        current_identity_key="google:subject",
    ) is False
