from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_core.tools import BaseTool
import shlex

# MCP server commands
mcp_server_signals_cmd: str = "python -m app.mcp.signals_server"
mcp_server_posts_cmd: str = "python -m app.mcp.posts_server"
mcp_server_web_search_cmd: str = "python -m app.mcp.web_search"
mcp_server_utm_cmd: str = "python -m app.mcp.utm_builder_server"

def get_mcp(name: str):
    mapping = {
        "signals": mcp_server_signals_cmd,
        "posts": mcp_server_posts_cmd,
        "web_search": mcp_server_web_search_cmd,
        "utm_builder": mcp_server_utm_cmd,
    }
    return mapping[name]


async def load_web_search_tools() -> list[BaseTool]:
    """Load web_search MCP tools once at agent startup. Not for repeated calls."""
    cmd = get_mcp("web_search")
    parts = shlex.split(cmd)
    client = MultiServerMCPClient(
        {"web_search": {"command": parts[0], "args": parts[1:], "transport": "stdio"}}
    )
    return await client.get_tools()