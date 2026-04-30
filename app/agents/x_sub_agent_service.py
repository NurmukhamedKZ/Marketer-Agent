from __future__ import annotations

import shlex
import time
from uuid import UUID, uuid4

import asyncpg
import structlog
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langchain.tools import ToolRuntime, tool
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.pregel import Pregel

from app.agents.context import AgentContext
from app.agents.prompts import build_x_sub_agent_prompt, build_x_subagent_message
from app.config import Settings
from app.db.queries import get_product_kb
from app.logging_setup import ToolCallLogger
from app.tools.posts import create_post_draft, list_recent_posts
from app.tools.utm_builder import build_utm_url

log = structlog.get_logger()

_X_SUB_AGENT_MCP_SERVERS = ("web_search",)


class XSubAgentService:
    def __init__(self, settings: Settings, pool: asyncpg.Pool) -> None:
        self._settings = settings
        self._pool = pool
        self._agent: Pregel | None = None

    async def __aenter__(self) -> XSubAgentService:
        product_kb = await get_product_kb(self._pool)
        system_prompt = build_x_sub_agent_prompt(product_kb)
        mcp_tools = await self._build_mcp_client().get_tools()
        tools = mcp_tools + [build_utm_url, create_post_draft, list_recent_posts]
        self._agent = self._build_agent(tools, system_prompt)
        log.info("x_sub_agent_service_started", tools=[t.name for t in tools])
        return self

    async def __aexit__(self, *args: object) -> None:
        self._agent = None
        log.info("x_sub_agent_service_stopped")

    async def run(
        self,
        message: str,
        thread_id: str,
        product_kb_id: int,
        post_idea_id: UUID,
    ) -> str:
        assert self._agent is not None, "Call __aenter__ before run()"
        run_log = log.bind(
            component="x_sub_agent",
            run_id=str(uuid4()),
            thread_id=thread_id,
        )
        run_log.info("run_start")
        t0 = time.monotonic()

        tokens: list[str] = []
        async for event in self._agent.astream_events(
            {"messages": [{"role": "user", "content": message}]},
            config=self._agent_config(thread_id),
            context=AgentContext(product_kb_id=product_kb_id, post_idea_id=post_idea_id),
            version="v2",
        ):
            if event["event"] == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if chunk.content:
                    tokens.append(chunk.content)

        run_log.info("run_end", duration_ms=round((time.monotonic() - t0) * 1000))
        return "".join(tokens)

    def _build_mcp_client(self) -> MultiServerMCPClient:
        connections = {}
        for name in _X_SUB_AGENT_MCP_SERVERS:
            cmd = self._settings.mcp_command_for(name)
            parts = shlex.split(cmd)
            connections[name] = {
                "command": parts[0],
                "args": parts[1:],
                "transport": "stdio",
            }
        return MultiServerMCPClient(connections)

    def _build_agent(self, tools: list, system_prompt: str) -> Pregel:
        model = ChatOpenAI(
            model=self._settings.openai_model,
            api_key=self._settings.openai_api_key,
            temperature=self._settings.llm_temperature,
            max_tokens=self._settings.llm_max_tokens,
        )
        return create_agent(
            model,
            tools,
            system_prompt=system_prompt,
            checkpointer=InMemorySaver(),
            context_schema=AgentContext,
        )

    def _agent_config(self, thread_id: str) -> dict:
        return {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": self._settings.sub_agent_max_iterations,
            "callbacks": [ToolCallLogger("x_sub_agent")],
        }


def make_invoke_x_sub_agent_tool(service: XSubAgentService) -> BaseTool:
    @tool
    async def invoke_x_sub_agent(
        post_idea_id: str,
        topic: str,
        angle: str,
        cmo_reasoning: str,
        retry_context: str | None,
        runtime: ToolRuntime[AgentContext],
    ) -> dict:
        """Delegate X post writing to X Sub-Agent. Returns the agent's final response."""
        thread_id = str(uuid4())
        message = build_x_subagent_message(topic, angle, cmo_reasoning, retry_context)
        result = await service.run(
            message,
            thread_id,
            runtime.context.product_kb_id,
            UUID(post_idea_id),
        )
        return {"result": result}

    return invoke_x_sub_agent
