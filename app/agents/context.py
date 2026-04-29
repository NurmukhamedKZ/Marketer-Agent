from dataclasses import dataclass, field
from uuid import UUID


@dataclass
class AgentContext:
    """Runtime context injected into agent tools via LangChain ToolRuntime.

    These fields are NOT exposed in the tool schema to the LLM.
    They are read inside @tool functions from runtime.context.
    """
    product_kb_id: int
    signal_id: UUID | None = field(default=None)
    post_idea_id: UUID | None = field(default=None)
