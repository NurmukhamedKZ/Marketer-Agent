# Agents (LangChain)

## Loading MCP Tools into LangChain

Use `langchain-mcp-adapters` (the official adapter package).

```python
# agents/mcp_client.py
from langchain_mcp_adapters.client import MultiServerMCPClient

async def get_mcp_tools(server_names: list[str]) -> list:
    """
    Connect to the configured MCP servers and return LangChain Tool objects.
    """
    settings = get_settings()
    server_config = {
        name: {
            "command": settings.mcp_command_for(name).split()[0],
            "args": settings.mcp_command_for(name).split()[1:],
            "transport": "stdio",
        }
        for name in server_names
    }
    client = MultiServerMCPClient(server_config)
    return await client.get_tools()
```

## CMO Agent (`agents/cmo_agent.py`)

**Responsibility:** Read recent unused signals, pick the best `CMO_IDEAS_PER_RUN` ones, write a `post_idea` for each, then invoke the X Sub-Agent for each idea.

**Tools loaded via MCP:**
- `product_kb.get_product_kb`
- `signals.list_unused_signals`, `signals.mark_signal_used`
- `posts.create_post_idea`

```python
# agents/cmo_agent.py
from langchain_anthropic import ChatAnthropic
from langchain.agents import create_tool_calling_agent, AgentExecutor
from mktg_agent.agents.mcp_client import get_mcp_tools
from mktg_agent.agents.prompts import CMO_PROMPT
from mktg_agent.agents.x_sub_agent import run_x_sub_agent
from mktg_agent.config import get_settings
from mktg_agent.db import get_pool
import structlog

log = structlog.get_logger()

async def run_cmo_cycle() -> list[str]:
    settings = get_settings()
    
    tools = await get_mcp_tools(["product_kb", "signals", "posts"])
    
    llm = ChatAnthropic(
        model=settings.claude_model,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        api_key=settings.anthropic_api_key,
    )
    
    agent = create_tool_calling_agent(llm, tools, CMO_PROMPT)
    executor = AgentExecutor(
        agent=agent,
        tools=tools,
        max_iterations=8,
        return_intermediate_steps=True,
        verbose=False,
    )
    
    result = await executor.ainvoke({
        "input": (
            f"Run a CMO cycle. Pick up to {settings.cmo_ideas_per_run} most "
            f"relevant signals from the available pool and create a post_idea "
            f"for each, targeting platform 'x'. After creating each post_idea, "
            f"return its id. Mark each used signal as used."
        ),
    })
    
    # Extract created post_idea ids from intermediate steps
    idea_ids = _extract_idea_ids(result["intermediate_steps"])
    log.info("cmo_cycle_ideas_created", count=len(idea_ids), ids=idea_ids)
    
    # Hand off to X Sub-Agent for each idea
    post_ids = []
    for idea_id in idea_ids:
        try:
            post_id = await run_x_sub_agent(idea_id)
            post_ids.append(post_id)
        except Exception as e:
            log.exception("x_sub_agent_failed", idea_id=idea_id, error=str(e))
    
    return post_ids
```

## X Post Sub-Agent (`agents/x_sub_agent.py`)

**Responsibility:** Given a `post_idea_id`, produce a single high-quality X post draft. May search the web for current context, may look at recent posts to avoid repetition, builds a UTM-tagged URL, persists the draft, and pushes it to Telegram for approval.

**Tools loaded via MCP:**
- `product_kb.get_product_kb`
- `posts.create_post_draft`, `posts.list_recent_posts`
- `web_search.search`
- `utm_builder.build_utm_url`

The `post_idea` payload (topic, angle, signal context, etc.) is loaded by the orchestration code and injected into the prompt rather than fetched via a tool. This keeps the sub-agent focused on writing.

```python
# agents/x_sub_agent.py
from langchain_anthropic import ChatAnthropic
from langchain.agents import create_tool_calling_agent, AgentExecutor
from mktg_agent.agents.mcp_client import get_mcp_tools
from mktg_agent.agents.prompts import X_SUB_AGENT_PROMPT
from mktg_agent.config import get_settings
from mktg_agent.db import get_pool
from mktg_agent.approval.bot import send_for_approval
from mktg_agent.state_machine import transition_post
import structlog

log = structlog.get_logger()

async def run_x_sub_agent(post_idea_id: str) -> str:
    """
    Given a post_idea_id, generate an X post draft and send it for approval.
    Returns the new post_id.
    """
    settings = get_settings()
    pool = await get_pool()
    
    # Hydrate the post_idea + signal for the prompt.
    idea_row = await pool.fetchrow("""
        SELECT pi.*, s.title AS signal_title, s.body AS signal_body, 
               s.url AS signal_url, s.subreddit
        FROM post_ideas pi
        LEFT JOIN signals s ON s.id = pi.signal_id
        WHERE pi.id = $1
    """, post_idea_id)
    if idea_row is None:
        raise ValueError(f"post_idea {post_idea_id} not found")
    
    tools = await get_mcp_tools(["product_kb", "posts", "web_search", "utm_builder"])
    
    llm = ChatAnthropic(
        model=settings.claude_model,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        api_key=settings.anthropic_api_key,
    )
    
    agent = create_tool_calling_agent(llm, tools, X_SUB_AGENT_PROMPT)
    executor = AgentExecutor(
        agent=agent,
        tools=tools,
        max_iterations=settings.sub_agent_max_iterations,
        return_intermediate_steps=True,
        verbose=False,
    )
    
    user_input = f"""
You are crafting a single X post for this post_idea (id: {post_idea_id}).

Topic: {idea_row['topic']}
Angle: {idea_row['angle']}
CMO reasoning: {idea_row['cmo_reasoning']}

Source signal:
  Subreddit: r/{idea_row['subreddit']}
  Title: {idea_row['signal_title']}
  Body: {idea_row['signal_body']}
  URL: {idea_row['signal_url']}

Steps you should take:
1. Call product_kb.get_product_kb to load product context.
2. Optionally call web_search.search if the topic involves recent events or 
   facts you should verify.
3. Call posts.list_recent_posts(platform='x', limit=10) to avoid repeating 
   recent angles.
4. Call utm_builder.build_utm_url with source='x', medium='social', 
   campaign='cmo_agent', content=<a short slug>.
5. Compose the post (max {settings.post_max_chars} characters).
6. Call posts.create_post_draft to persist your draft.
7. Return ONLY the new post_id.
"""
    
    result = await executor.ainvoke({"input": user_input})
    post_id = _extract_post_id(result)
    
    # Transition draft -> pending and notify Telegram
    message_id = await send_for_approval(post_id)
    await transition_post(
        post_id,
        from_state="draft",
        to_state="pending",
        approval_message_id=message_id,
    )
    
    log.info("x_sub_agent_draft_created", post_id=post_id)
    return post_id
```

## Prompts (`agents/prompts.py`)

```python
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder

CMO_SYSTEM = """You are the CMO of a SaaS product. Your job is to decide, each day, 
which Reddit questions to act on and what angle each post should take.

You have tools to:
- read product context
- list available signals (Reddit questions)
- mark signals as used
- create post_ideas

Workflow:
1. Read product context.
2. List available signals.
3. Pick the {n_ideas} signals where the product is genuinely useful to the asker.
4. For each, create a post_idea with: signal_id, target_platform='x', topic, 
   angle, cmo_reasoning. The angle should be a specific, sharp claim (not generic).
5. Mark each chosen signal as used.

Rules:
- Do NOT pick signals where the product is only tangentially related.
- The angle should be specific enough that a writer could craft a single tweet from it.
- Avoid topics in the product's banned_topics list.
- Skip signals already used.

Return a brief summary at the end with the post_idea ids you created."""

CMO_PROMPT = ChatPromptTemplate.from_messages([
    ("system", CMO_SYSTEM),
    ("human", "{input}"),
    MessagesPlaceholder("agent_scratchpad"),
])

X_SUB_AGENT_SYSTEM = """You are an expert X (Twitter) copywriter for a SaaS product.

Your job: given a post_idea (topic + angle), write ONE X post that:
- Opens with a sharp, specific hook in the first line. No "Just thinking about..." 
  or "Let's talk about..." openers.
- Speaks to the underlying pain in the source signal — paraphrase, do NOT quote 
  the user verbatim.
- Mentions the product naturally only if it genuinely fits the angle. Skip the 
  mention if it would feel forced.
- Ends with a CTA, an open question, or a sharp closing line.
- Stays under the maximum character limit.
- Matches the brand voice from product_kb.
- Does NOT include hashtags or emojis unless the brand voice explicitly allows them.
- If you include the product link, use the UTM URL from utm_builder.

Process:
1. Always start by calling product_kb.get_product_kb.
2. Optionally use web_search.search if facts in the topic need verification.
3. Always call posts.list_recent_posts(platform='x') to avoid repeating recent angles.
4. Call utm_builder.build_utm_url before composing.
5. Compose, then call posts.create_post_draft with your final text and reasoning.
6. Return the new post_id.

Never write more than one draft. Pick your best version and persist it."""

X_SUB_AGENT_PROMPT = ChatPromptTemplate.from_messages([
    ("system", X_SUB_AGENT_SYSTEM),
    ("human", "{input}"),
    MessagesPlaceholder("agent_scratchpad"),
])
```

## Schemas (`agents/schemas.py`)

Pydantic models for any structured outputs. For MVP, parsing of the agent's final answer is best-effort with regex over the intermediate steps to extract the created `post_idea_id` / `post_id` (since we want them returned as tool-call results, not as parsed text).
