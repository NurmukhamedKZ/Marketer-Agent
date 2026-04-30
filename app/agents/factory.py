from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from langchain.agents import create_agent
from langchain.tools import tool
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.pregel import Pregel

from app.agents.context import AgentContext
from app.config import Settings
from app.logging_setup import ToolCallLogger


@dataclass(frozen=True)
class SubAgentSpec:
    name: str
    description: str
    system_prompt: str
    tools: list[BaseTool]


def build_agent(
    model: BaseChatModel,
    tools: list,
    system_prompt: str,
    checkpointer: InMemorySaver | None = None,
) -> Pregel:
    return create_agent(
        model,
        tools,
        system_prompt=system_prompt,
        context_schema=AgentContext,
        checkpointer=checkpointer or InMemorySaver(),
    )


def as_tool(agent: Pregel, spec: SubAgentSpec, product_kb_id: int) -> BaseTool:
    @tool(spec.name, description=spec.description)
    async def _call(query: str, post_idea_id: str) -> str:
        thread_id = str(uuid4())
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": query}]},
            config={"configurable": {"thread_id": thread_id}, "callbacks": [ToolCallLogger(spec.name)]},
            context=AgentContext(product_kb_id=product_kb_id, post_idea_id=UUID(post_idea_id)),
        )
        return result["messages"][-1].content

    return _call

