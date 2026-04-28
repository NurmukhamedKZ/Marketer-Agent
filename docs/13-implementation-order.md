# Implementation Order

Build in this order — each step independently runnable and testable:

1. Project skeleton: `pyproject.toml` (uv), config, structlog, DB pool, migration runner
2. Schema migration + `state_machine.py` + tests
3. `product_kb` setup + minimal `product_kb` MCP server + test
4. Reddit collector + `signals` MCP server + test
5. `posts` MCP server + `utm_builder` MCP server + tests
6. `web_search` MCP server (Tavily wrapper)
7. Smoke test the MCP layer: write a tiny script that connects via `langchain-mcp-adapters` and lists all tools
8. X Sub-Agent (without CMO) — invoke it directly with a manually-created post_idea. Verify it produces a `posts` row
9. Telegram bot (aiogram) — wire `send_for_approval` and the three button handlers
10. X Publisher — wire to the approve callback
11. CMO Agent — runs, creates post_ideas, invokes X Sub-Agent for each
12. Analytics fetcher
13. Tests for agents (with mocked LLM + MCP)
14. systemd units, cron, deployment scripts
15. README
