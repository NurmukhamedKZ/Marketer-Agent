# Testing Requirements

Use `pytest-asyncio`. Use a separate test DB (`mktg_agent_test`), wiped and migrated per session.

## Required Tests

| File | What to test |
|------|-------------|
| `test_db.py` | Schema migration applies cleanly, pool returns connections |
| `test_state_machine.py` | Every valid transition succeeds; every invalid one raises `InvalidStateTransition` |
| `test_reddit_collector.py` | Mock praw, verify dedup via `ON CONFLICT`, keyword and age filtering |
| `test_mcp_servers/test_signals_server.py` | Call FastMCP tools directly against a test DB; verify correct shapes |
| `test_mcp_servers/test_posts_server.py` | Verify `create_post_idea` and `create_post_draft` produce correct rows; verify the transaction in `create_post_draft` (idea is marked consumed) |
| `test_mcp_servers/test_utm_builder_server.py` | UTM merging into URLs that already have query strings |
| `test_cmo_agent.py` | Mock LLM and MCP tool calls; verify CMO produces expected post_ideas and invokes X Sub-Agent for each |
| `test_x_sub_agent.py` | Mock LLM and MCP tools; verify the agent produces a draft, persists it, and triggers `send_for_approval` |
| `test_publisher.py` | Mock tweepy; verify state transitions on success/failure and retry logic |
