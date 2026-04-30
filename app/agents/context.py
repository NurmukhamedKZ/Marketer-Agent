from dataclasses import dataclass, field
from uuid import UUID


@dataclass
class AgentContext:
    """
    Context injected into every tool call via LangChain ToolRuntime.
    Fields are hidden from the LLM schema — passed at agent invocation time.
    """
    product_kb_id: int
    signal_id: UUID | None = field(default=None)
    post_idea_id: UUID | None = field(default=None)
