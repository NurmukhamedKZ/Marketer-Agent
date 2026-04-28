# Overview & Architecture

## Project Overview

**Project name:** mktg-agent

**Goal:** Build an AI-powered marketing system with two agents:
- **CMO Agent** — plans what to post and delegates to a platform sub-agent
- **X Post Sub-Agent** — crafts the actual X (Twitter) post

The system collects question-style signals from Reddit, generates drafts, gets human approval via Telegram, publishes to X, and tracks performance.

**Core hypothesis:** A two-tier agent system (strategic + platform-specialized) given (a) product context and (b) real Reddit questions matching our ICP can generate X posts that drive traffic to the product, when reviewed and approved by a human.

**Out of scope for MVP:** Other platforms (TikTok, IG, LinkedIn, Reddit posting), image/video generation, vector RAG, separate validators service, scheduler, A/B testing, web UI, tiered approval, automated insight extraction, multi-tenancy.

## High-Level Architecture

```
                ┌──────────────────┐
                │   Reddit API     │
                └────────┬─────────┘
                         │
                         ▼ (Hermes/cron, every 6h)
                ┌──────────────────┐
                │  signals table   │
                └────────┬─────────┘
                         │
                         ▼ (cron, daily 08:00)
                ┌──────────────────┐         ┌─────────────────────┐
                │   CMO Agent      │────────▶│ MCP: signals_read   │
                │  (LangChain)     │◀────────│ MCP: product_kb     │
                │                  │         │ MCP: posts_write    │
                │  Picks signals,  │         └─────────────────────┘
                │  delegates to    │
                │  X Sub-Agent     │
                └────────┬─────────┘
                         │ delegates (post_idea)
                         ▼
                ┌──────────────────┐         ┌─────────────────────┐
                │  X Post          │────────▶│ MCP: web_search     │
                │  Sub-Agent       │◀────────│ MCP: utm_builder    │
                │  (LangChain)     │         │ MCP: posts_write    │
                │                  │         └─────────────────────┘
                │  Crafts the      │
                │  actual X post   │
                └────────┬─────────┘
                         │ writes draft
                         ▼
                ┌──────────────────┐
                │   posts table    │  state=pending
                └────────┬─────────┘
                         │
                         ▼
                ┌──────────────────┐
                │  Telegram Bot    │  aiogram, long-running
                │  (approve/edit/  │
                │   reject)        │
                └────────┬─────────┘
                         │ on approval
                         ▼
                ┌──────────────────┐
                │  X Publisher     │  immediate post via X API
                └────────┬─────────┘
                         │
                         ▼
                ┌──────────────────┐
                │  posts table     │  state=published
                └────────┬─────────┘
                         │ daily 09:00
                         ▼
                ┌──────────────────┐
                │ Analytics Fetcher│  pulls X metrics → posts table
                └──────────────────┘
```

## Key Design Decisions

1. **Two-agent system, not one.** CMO Agent decides what topic and which signal. X Sub-Agent decides how to write the post for X specifically. Each has its own prompt, its own toolset, its own LangChain agent executor.

2. **Tools = MCP servers, not Python functions.** Every tool the agents use is exposed via FastMCP. This means the same tools can be reused later by other sub-agents (LinkedIn, Reddit) without refactoring.

3. **MCP servers run as separate processes.** Each MCP server is an independent FastMCP app, run via systemd. Agents connect to them as MCP clients.

4. **LangChain orchestrates the agent loop.** Use LangChain's `create_tool_calling_agent` or LangGraph's prebuilt ReAct agent (whichever is current in LangChain ≥ 1.2). MCP tools are loaded into the agent via `langchain-mcp-adapters`.

5. **No shared in-process state between agents.** CMO Agent runs, finishes, persists to DB. Sub-Agent reads from DB, runs, finishes, persists. Both are short-lived processes invoked by cron or by the CMO. This keeps things debuggable.
