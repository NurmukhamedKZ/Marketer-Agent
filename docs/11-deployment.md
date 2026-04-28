# Deployment

## systemd Units (`deploy/systemd/`)

One unit for the Telegram bot, one per MCP server.

> **Note on MCP transport:** In MVP, agents connect to MCP servers via stdio spawned per-invocation, not persistent HTTP. That means for the agents (CMO, X Sub-Agent), the MCP servers do **NOT** need to run as systemd units — `langchain-mcp-adapters` will spawn them as subprocesses each time. The systemd units are optional, only useful if you switch to HTTP transport later.
>
> The **Telegram bot** does need a systemd unit since it runs continuously.

Example MCP server unit:

```ini
# mktg-mcp-signals.service
[Unit]
Description=Marketing Agent — signals MCP server
After=network.target postgresql.service

[Service]
Type=simple
User=mktg
WorkingDirectory=/opt/mktg-agent
EnvironmentFile=/opt/mktg-agent/.env
ExecStart=/opt/mktg-agent/.venv/bin/python -m mktg_agent.mcp_servers.signals_server
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## Cron (`deploy/crontab.example`)

```cron
# Reddit signal collection — every 6 hours
0 */6 * * * cd /opt/mktg-agent && .venv/bin/python -m mktg_agent.signals.reddit_collector >> /var/log/mktg-agent/collect.log 2>&1

# CMO cycle — daily at 08:00
0 8 * * * cd /opt/mktg-agent && .venv/bin/python -m mktg_agent.agents.cmo_agent >> /var/log/mktg-agent/cmo.log 2>&1

# Analytics — daily at 09:00
0 9 * * * cd /opt/mktg-agent && .venv/bin/python -m mktg_agent.analytics.x_fetcher >> /var/log/mktg-agent/analytics.log 2>&1
```
