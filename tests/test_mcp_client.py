"""
Smoke test for the MCP layer via langchain-mcp-adapters.

Spawns the web_search MCP server as a real subprocess over stdio and verifies
that MultiServerMCPClient loads the expected tools. No network calls are made.
"""
import pytest
from langchain_core.tools import BaseTool

from app.agents.mcp_client import get_web_search_tools


@pytest.mark.asyncio
async def test_mcp_client_loads_web_search_tools():
    """get_web_search_tools() spawns the subprocess and returns LangChain tools."""
    tools: list[BaseTool] = await get_web_search_tools()
    assert len(tools) >= 1, "Expected at least one tool from web_search MCP server"


@pytest.mark.asyncio
async def test_mcp_client_web_search_tool_present():
    tools = await get_web_search_tools()
    names = {t.name for t in tools}
    assert "web_search" in names, f"web_search tool missing; got: {names}"


@pytest.mark.asyncio
async def test_mcp_client_web_fetch_tool_present():
    tools = await get_web_search_tools()
    names = {t.name for t in tools}
    assert "web_fetch" in names, f"web_fetch tool missing; got: {names}"


@pytest.mark.asyncio
async def test_mcp_client_tools_are_langchain_base_tools():
    """Every loaded tool must be a LangChain BaseTool with name and description."""
    tools = await get_web_search_tools()
    for tool in tools:
        assert isinstance(tool, BaseTool)
        assert tool.name, f"Tool missing name: {tool}"
        assert tool.description, f"Tool missing description: {tool.name}"


@pytest.mark.asyncio
async def test_mcp_client_web_search_has_query_param():
    """web_search tool must expose a 'query' parameter in its schema."""
    tools = await get_web_search_tools()
    web_search_tool = next(t for t in tools if t.name == "web_search")
    # langchain-mcp-adapters returns args_schema as a plain dict (JSON Schema)
    schema = web_search_tool.args_schema
    props = schema.get("properties", {}) if isinstance(schema, dict) else {}
    assert "query" in props, f"'query' param not found in web_search schema: {schema}"


@pytest.mark.asyncio
async def test_mcp_client_web_fetch_has_url_param():
    """web_fetch tool must expose a 'url' parameter in its schema."""
    tools = await get_web_search_tools()
    web_fetch_tool = next(t for t in tools if t.name == "web_fetch")
    schema = web_fetch_tool.args_schema
    props = schema.get("properties", {}) if isinstance(schema, dict) else {}
    assert "url" in props, f"'url' param not found in web_fetch schema: {schema}"
