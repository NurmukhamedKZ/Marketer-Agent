from __future__ import annotations

import time
from collections.abc import AsyncIterator
from uuid import uuid4

import asyncpg
import structlog
from langchain_openai import ChatOpenAI
from langgraph.pregel import Pregel

from app.agents.context import AgentContext
from app.agents.factory import SubAgentSpec, as_tool, build_agent
from app.mcp.all_mcp import load_web_search_tools
from app.agents.prompts import build_system_prompt
from app.agents.registry import SUBAGENTS
from app.config import Settings
from app.db.queries import get_product_kb
from app.logging_setup import ToolCallLogger
from app.tools.posts import create_post_idea, list_recent_posts

log = structlog.get_logger()


class AgentRuntime:
    def __init__(self, settings: Settings, pool: asyncpg.Pool) -> None:
        self._settings = settings
        self._pool = pool
        self._agent: Pregel | None = None
        self._kb_id: int | None = None

    async def __aenter__(self) -> AgentRuntime:
        kb = await get_product_kb(self._pool)
        self._kb_id = kb.id

        model = ChatOpenAI(
            model=self._settings.openai_model,
            api_key=self._settings.openai_api_key,
            temperature=self._settings.llm_temperature,
            max_tokens=self._settings.llm_max_tokens,
        )
        web_search = await load_web_search_tools()

        subagent_tools = [
            as_tool(
                build_agent(model, [*spec.tools, *web_search], spec.system_prompt),
                spec,
                kb.id,
            )
            for spec in SUBAGENTS
        ]

        self._agent = build_agent(
            model,
            [create_post_idea, list_recent_posts, *web_search, *subagent_tools],
            build_system_prompt(kb),
        )
        log.info("agent_runtime_started", subagents=[s.name for s in SUBAGENTS])
        return self

    async def __aexit__(self, *args: object) -> None:
        self._agent = None
        log.info("agent_runtime_stopped")

    async def run(self, thread_id: str, message: str) -> AsyncIterator[str]:
        assert self._agent is not None, "Call __aenter__ before run()"
        run_log = log.bind(component="cmo_agent", run_id=str(uuid4()), thread_id=thread_id)
        run_log.info("run_start")
        t0 = time.monotonic()

        async for event in self._agent.astream_events(
            {"messages": [{"role": "user", "content": message}]},
            config={
                "configurable": {"thread_id": thread_id},
                "recursion_limit": 100,
                "callbacks": [ToolCallLogger("cmo_agent")],
            },
            context=AgentContext(product_kb_id=self._kb_id),
            version="v2",
        ):
            if event["event"] == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if chunk.content:
                    yield chunk.content

        run_log.info("run_end", duration_ms=round((time.monotonic() - t0) * 1000))