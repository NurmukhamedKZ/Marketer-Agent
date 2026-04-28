# Tech Stack (Locked)

| Layer | Choice | Notes |
|-------|--------|-------|
| Language | Python 3.12+ | |
| Agent framework | LangChain ≥ 1.2 | Use `langchain`, `langchain-anthropic`, `langchain-mcp-adapters` |
| LLM | Anthropic Claude | Model: `claude-sonnet-4-5`. Use `ChatAnthropic` from `langchain-anthropic` |
| MCP | FastMCP | One MCP server per logical tool group. Run as systemd services |
| Telegram bot | aiogram v3+ | Async, dispatcher-based |
| Database | PostgreSQL 18 | `asyncpg` for async access |
| Reddit API | praw | Free tier sufficient |
| X API | tweepy | OAuth 1.0a User Context for posting; v2 endpoints for analytics |
| Migrations | Plain SQL files in `migrations/` | Applied by a small runner script. Avoid alembic for simplicity |
| Config | pydantic-settings | Loaded from `.env` |
| Logging | structlog | JSON output in production |
| Cron | System cron | |
| Process supervision | systemd | For Telegram bot and all MCP servers |
| Package manager | uv | Fast, lockfile-based |
| Tests | pytest, pytest-asyncio | |

**Do not introduce:** LangGraph (unless required for a specific feature; basic LangChain agents are enough for MVP), Celery, Redis, FastAPI, Docker Compose orchestration, vector DBs, observability platforms.
