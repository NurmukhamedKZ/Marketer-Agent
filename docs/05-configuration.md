# Configuration

File: `.env.example`

```bash
# Database
DATABASE_URL=postgresql://mktg:password@localhost:5432/mktg_agent
DATABASE_POOL_MIN=2
DATABASE_POOL_MAX=10

# Anthropic
ANTHROPIC_API_KEY=sk-ant-...
CLAUDE_MODEL=claude-sonnet-4-5
LLM_TEMPERATURE=0.7
LLM_MAX_TOKENS=2000

# MCP servers (each runs on a different port; agents connect via stdio or HTTP)
# We use stdio transport for simplicity in MVP.
MCP_SERVER_PRODUCT_KB_CMD=python -m mktg_agent.mcp_servers.product_kb_server
MCP_SERVER_SIGNALS_CMD=python -m mktg_agent.mcp_servers.signals_server
MCP_SERVER_POSTS_CMD=python -m mktg_agent.mcp_servers.posts_server
MCP_SERVER_WEB_SEARCH_CMD=python -m mktg_agent.mcp_servers.web_search_server
MCP_SERVER_UTM_CMD=python -m mktg_agent.mcp_servers.utm_builder_server

# Reddit
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_USER_AGENT=mktg-agent/0.1 by /u/yourusername
REDDIT_SUBREDDITS=SaaS,startups,Entrepreneur,smallbusiness
REDDIT_KEYWORDS=how do I,alternative to,anyone using,looking for,recommend,struggling with
REDDIT_MAX_AGE_HOURS=48
REDDIT_MIN_SCORE=2

# X (Twitter)
X_API_KEY=
X_API_SECRET=
X_ACCESS_TOKEN=
X_ACCESS_TOKEN_SECRET=
X_BEARER_TOKEN=

# Telegram
TELEGRAM_BOT_TOKEN=
TELEGRAM_OWNER_CHAT_ID=

# Web search (for X Sub-Agent — Tavily recommended)
TAVILY_API_KEY=

# Behavior
CMO_IDEAS_PER_RUN=3
CMO_SIGNAL_CANDIDATES=15
POST_MAX_CHARS=270
SUB_AGENT_MAX_ITERATIONS=8

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json
```

`config.py` provides a cached `get_settings() -> Settings` using `pydantic-settings.BaseSettings`.
