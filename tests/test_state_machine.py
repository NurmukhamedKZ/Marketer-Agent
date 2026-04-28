import pytest
from app.models.state_machine import validate_transition, InvalidStateTransition

VALID_TRANSITIONS = [
    ("draft", "pending"),
    ("pending", "approved"),
    ("pending", "rejected"),
    ("pending", "pending"),
    ("approved", "published"),
    ("approved", "failed"),
    ("failed", "approved"),
]

INVALID_TRANSITIONS = [
    ("draft", "approved"),
    ("draft", "rejected"),
    ("draft", "published"),
    ("draft", "failed"),
    ("pending", "draft"),
    ("pending", "published"),
    ("pending", "failed"),
    ("approved", "draft"),
    ("approved", "pending"),
    ("approved", "rejected"),
    ("approved", "approved"),
    ("published", "draft"),
    ("published", "pending"),
    ("published", "approved"),
    ("published", "rejected"),
    ("published", "published"),
    ("published", "failed"),
    ("rejected", "draft"),
    ("rejected", "pending"),
    ("rejected", "approved"),
    ("rejected", "published"),
    ("rejected", "rejected"),
    ("rejected", "failed"),
    ("failed", "draft"),
    ("failed", "pending"),
    ("failed", "rejected"),
    ("failed", "published"),
    ("failed", "failed"),
]


@pytest.mark.parametrize("from_state,to_state", VALID_TRANSITIONS)
def test_valid_transitions(from_state: str, to_state: str) -> None:
    validate_transition("test-post-id", from_state, to_state)


@pytest.mark.parametrize("from_state,to_state", INVALID_TRANSITIONS)
def test_invalid_transitions(from_state: str, to_state: str) -> None:
    with pytest.raises(InvalidStateTransition) as exc_info:
        validate_transition("test-post-id", from_state, to_state)
    assert exc_info.value.post_id == "test-post-id"
    assert exc_info.value.from_state == from_state
    assert exc_info.value.to_state == to_state


def test_exception_message_contains_states() -> None:
    with pytest.raises(InvalidStateTransition) as exc_info:
        validate_transition("abc-123", "draft", "published")
    msg = str(exc_info.value)
    assert "abc-123" in msg
    assert "draft" in msg
    assert "published" in msg
