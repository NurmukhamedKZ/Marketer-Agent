# Project Structure

```
marketer-agent/
├── pyproject.toml
├── uv.lock
├── .env.example
├── README.md
├── migrations/
│   └── 001_initial_schema.sql
├── app/
│   ├── __init__.py
│   ├── config.py                    # pydantic-settings
│   ├── db/                          # asyncpg pool, query helpers
│   │   ├── __init__.py
│   │   ├── pool.py
│   │   └── queries.py
│   ├── models/                      # pydantic models and state machine
│   │   ├── __init__.py
│   │   ├── product_kb.py
│   │   ├── signal.py
│   │   ├── post_idea.py
│   │   ├── post.py
│   │   └── state_machine.py         # post state transitions
│   ├── logging_setup.py             # structlog config
│   │
│   ├── signals/
│   │   └── reddit_collector.py      # PRAW-based scraper (called by cron)
│   │
│   ├── mcp/                         # FastMCP servers — each is its own process
│   │   ├── __init__.py
│   │   ├── product_kb_server.py
│   │   ├── signals_server.py
│   │   ├── posts_server.py
│   │   ├── web_search_server.py
│   │   └── utm_builder_server.py
│   │
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── cmo_agent.py             # LangChain agent: planning & delegation
│   │   ├── x_sub_agent.py           # LangChain agent: X-specific post crafting
│   │   ├── prompts.py               # system prompts for both agents
│   │   ├── schemas.py               # pydantic schemas for structured outputs
│   │   └── mcp_client.py            # helper to load MCP tools into LangChain
│   │
│   ├── approval/
│   │   ├── __init__.py
│   │   ├── bot.py                   # aiogram Dispatcher + main()
│   │   └── handlers.py              # message + callback handlers
│   │
│   ├── publisher/
│   │   ├── __init__.py
│   │   └── x_publisher.py           # tweepy-based publisher
│   │
│   └── analytics/
│       └── x_fetcher.py             # daily metrics fetch
├── tests/
│   ├── conftest.py
│   ├── test_db.py
│   ├── test_state_machine.py
│   ├── test_cmo_agent.py
│   ├── test_x_sub_agent.py
│   ├── test_publisher.py
│   ├── test_reddit_collector.py
│   └── test_mcp_servers/
│       ├── test_signals_server.py
│       ├── test_posts_server.py
│       └── test_utm_builder_server.py
└── deploy/
    ├── crontab.example
    └── systemd/
        ├── mktg-agent-bot.service
        ├── mktg-mcp-product-kb.service
        ├── mktg-mcp-signals.service
        ├── mktg-mcp-posts.service
        ├── mktg-mcp-web-search.service
        └── mktg-mcp-utm.service
```
