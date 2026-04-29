from __future__ import annotations

import shlex
import time
from collections.abc import AsyncIterator
from uuid import uuid4

import asyncpg
import structlog
from langchain.agents import create_agent
from langchain_anthropic import ChatAnthropic
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.pregel import Pregel

from app.agents.prompts import build_system_prompt
from app.config import Settings
from app.db.queries import get_product_kb
from app.logging_setup import ToolCallLogger

log = structlog.get_logger()

# MCP servers the CMO agent needs
_CMO_MCP_SERVERS = ("signals", "posts", "web_search")


class CMOAgentService:
    def __init__(self, settings: Settings, pool: asyncpg.Pool) -> None:
        self._settings = settings
        self._pool = pool
        self._agent: Pregel | None = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def __aenter__(self) -> CMOAgentService:
        product_kb = await get_product_kb(self._pool)
        system_prompt = build_system_prompt(product_kb)
        tools = await self._build_mcp_client().get_tools()
        self._agent = self._build_agent(tools, system_prompt)
        log.info("cmo_agent_service_started", tools=[t.name for t in tools])
        return self

    async def __aexit__(self, *args: object) -> None:
        self._agent = None
        log.info("cmo_agent_service_stopped")

    # ── Public interface ──────────────────────────────────────────────────────

    async def run(self, thread_id: str, message: str) -> AsyncIterator[str]:
        """Stream agent response tokens. One call = one conversation turn."""
        assert self._agent is not None, "Call __aenter__ before run()"
        run_log = log.bind(component="cmo_agent", run_id=str(uuid4()), thread_id=thread_id)
        run_log.info("run_start")
        t0 = time.monotonic()

        async for event in self._agent.astream_events(
            {"messages": [{"role": "user", "content": message}]},
            config=self._agent_config(thread_id),
            version="v2",
        ):
            if event["event"] == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if chunk.content:
                    yield chunk.content

        run_log.info("run_end", duration_ms=round((time.monotonic() - t0) * 1000))

    # ── Private builders ──────────────────────────────────────────────────────

    def _build_mcp_client(self) -> MultiServerMCPClient:
        connections = {}
        for name in _CMO_MCP_SERVERS:
            cmd = self._settings.mcp_command_for(name)
            parts = shlex.split(cmd)
            connections[name] = {
                "command": parts[0],
                "args": parts[1:],
                "transport": "stdio",
            }
        return MultiServerMCPClient(connections)

    def _build_agent(self, tools: list, system_prompt: str) -> Pregel:
        model = ChatAnthropic(
            model=self._settings.claude_model,
            api_key=self._settings.anthropic_api_key,
            temperature=self._settings.llm_temperature,
            max_tokens=self._settings.llm_max_tokens,
        )
        return create_agent(
            model,
            tools,
            system_prompt=system_prompt,
            checkpointer=InMemorySaver(),
        )

    def _agent_config(self, thread_id: str) -> dict:
        return {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": 100,
            "callbacks": [ToolCallLogger("cmo_agent")],
        }
