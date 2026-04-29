from __future__ import annotations

import shlex

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from app.config import get_settings


async def get_web_search_tools() -> list[BaseTool]:
    """Load web_search MCP tools via stdio. Requires web_search server to be implemented."""
    settings = get_settings()
    cmd = settings.mcp_command_for("web_search")
    parts = shlex.split(cmd)

    client = MultiServerMCPClient(
        {
            "web_search": {
                "command": parts[0],
                "args": parts[1:],
                "transport": "stdio",
            }
        }
    )
    return await client.get_tools()
