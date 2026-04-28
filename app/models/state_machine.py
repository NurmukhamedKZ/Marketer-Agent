from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.models.post import PostState

ALLOWED_TRANSITIONS: dict[PostState, set[PostState]] = {
    PostState.draft: {PostState.pending},
    PostState.pending: {PostState.approved, PostState.rejected, PostState.pending},
    PostState.approved: {PostState.published, PostState.failed},
    PostState.failed: {PostState.approved},
}


class InvalidStateTransition(Exception):
    def __init__(self, post_id: str, from_state: str, to_state: str) -> None:
        super().__init__(
            f"Cannot transition post {post_id} from {from_state!r} to {to_state!r}"
        )
        self.post_id = post_id
        self.from_state = from_state
        self.to_state = to_state


def validate_transition(post_id: str, from_state: str, to_state: str) -> None:
    fs = PostState(from_state)
    ts = PostState(to_state)
    if ts not in ALLOWED_TRANSITIONS.get(fs, set()):
        raise InvalidStateTransition(post_id, from_state, to_state)


async def transition_post(
    post_id: str,
    from_state: str,
    to_state: str,
    **kwargs: Any,
) -> None:
    from app.db import get_pool

    validate_transition(post_id, from_state, to_state)

    updates: dict[str, Any] = {"state": to_state, **kwargs}

    ts = PostState(to_state)
    if ts == PostState.published and "published_at" not in updates:
        updates["published_at"] = datetime.now(timezone.utc)
    if ts == PostState.failed and "failed_at" not in updates:
        updates["failed_at"] = datetime.now(timezone.utc)

    set_clauses = ", ".join(f"{k} = ${i + 2}" for i, k in enumerate(updates))
    values = list(updates.values())

    pool = await get_pool()
    await pool.execute(
        f"UPDATE posts SET {set_clauses} WHERE id = $1",
        UUID(post_id),
        *values,
    )
