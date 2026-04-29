from contextvars import ContextVar
from uuid import UUID


current_product_kb_id: ContextVar[int] = ContextVar("current_product_kb_id")
current_signal_id: ContextVar[UUID | None] = ContextVar("current_signal_id", default=None)
current_post_idea_id: ContextVar[UUID | None] = ContextVar("current_post_idea_id", default=None)


def set_agent_context(
    product_kb_id: int,
    signal_id: UUID | None = None,
    post_idea_id: UUID | None = None,
) -> None:
    """Set context vars before invoking an agent. Call once per agent run."""
    current_product_kb_id.set(product_kb_id)
    current_signal_id.set(signal_id)
    current_post_idea_id.set(post_idea_id)
