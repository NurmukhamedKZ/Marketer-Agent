from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql://mktg:password@localhost:5432/mktg_agent"
    database_pool_min: int = 2
    database_pool_max: int = 10

    # Anthropic
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-5"
    llm_temperature: float = 0.7
    llm_max_tokens: int = 2000

    # MCP server commands
    mcp_server_product_kb_cmd: str = "python -m app.mcp.product_kb_server"
    mcp_server_signals_cmd: str = "python -m app.mcp.signals_server"
    mcp_server_posts_cmd: str = "python -m app.mcp.posts_server"
    mcp_server_web_search_cmd: str = "python -m app.mcp.web_search_server"
    mcp_server_utm_cmd: str = "python -m app.mcp.utm_builder_server"

    # Reddit
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "mktg-agent/0.1 by /u/yourusername"
    reddit_subreddits: str = "SaaS,startups,Entrepreneur,smallbusiness"
    reddit_keywords: str = "how do I,alternative to,anyone using,looking for,recommend,struggling with"
    reddit_max_age_hours: int = 48
    reddit_min_score: int = 2

    # X (Twitter)
    x_api_key: str = ""
    x_api_secret: str = ""
    x_access_token: str = ""
    x_access_token_secret: str = ""
    x_bearer_token: str = ""

    # Telegram
    telegram_bot_token: str = ""
    telegram_owner_chat_id: int = 0

    # Web search
    tavily_api_key: str = ""

    # Behavior
    cmo_ideas_per_run: int = 3
    cmo_signal_candidates: int = 15
    post_max_chars: int = 270
    sub_agent_max_iterations: int = 8

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"

    def mcp_command_for(self, name: str) -> str:
        mapping = {
            "product_kb": self.mcp_server_product_kb_cmd,
            "signals": self.mcp_server_signals_cmd,
            "posts": self.mcp_server_posts_cmd,
            "web_search": self.mcp_server_web_search_cmd,
            "utm_builder": self.mcp_server_utm_cmd,
        }
        return mapping[name]


@lru_cache
def get_settings() -> Settings:
    return Settings()
