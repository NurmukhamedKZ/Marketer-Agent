# Notes for the Coding Agent

When implementing this spec:

1. **Read the entire spec first**, then ask clarifying questions before writing any code. Do not start implementing immediately.

2. **Verify the LangChain ≥ 1.2 agent API** before you start. The exact API for `create_tool_calling_agent` / `AgentExecutor` may have shifted in 1.2; check `langchain.__version__` and the current docs. If 1.2 has migrated to LangGraph-based agents, use the LangGraph prebuilt ReAct agent instead. Do not guess.

3. **Verify `langchain-mcp-adapters`** is the correct package name and stdio transport works as described. If the integration package has changed, surface this and propose the alternative.

4. **Use stdio MCP transport for MVP.** Do not set up HTTP servers for MCP unless the LangChain MCP adapter requires it.

5. **Do not introduce LangGraph** for the agent loops unless LangChain ≥ 1.2 has deprecated `AgentExecutor`. If it has, use LangGraph's prebuilt ReAct agent rather than building a custom graph.

6. **Type hints throughout.** `mypy --strict` should pass on `src/`.

7. **All external data goes through pydantic models** (LLM outputs, API responses, MCP tool returns where structured).

8. **Async throughout.** Do not mix sync DB calls into async paths.

9. **One public function per module.** Implementation details private.

10. **Constants come from config**, not hardcoded.
