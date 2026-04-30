# Agent Refactor Design
_2026-04-30_

## Goal

Replace two monolithic service classes (`CMOAgentService`, `XSubAgentService`) with a
generic factory + registry pattern so that adding a new sub-agent requires one entry in
a list, not a new class + file + DI wiring.

## Files

### Deleted
- `app/agents/cmo_agent_service.py`
- `app/agents/x_sub_agent_service.py`
- `app/agents/mcp_client.py`

### Created
| File | Responsibility |
|---|---|
| `app/agents/factory.py` | `SubAgentSpec`, `build_agent()`, `as_tool()`, `_load_web_search()` |
| `app/agents/registry.py` | `SUBAGENTS: list[SubAgentSpec]` — one entry per sub-agent |
| `app/agents/runtime.py` | `AgentRuntime`: lifecycle (`__aenter__`/`__aexit__`) + `run()` for CMO streaming |

### Modified
| File | Change |
|---|---|
| `app/agents/context.py` | Remove `signal_id`, `post_idea_id`; keep only `product_kb_id: int` |
| `app/agents/prompts.py` | Remove `build_x_subagent_message`; keep both prompt builders |
| `app/approval/bot.py` | Use `AgentRuntime` instead of both service classes |
| `tests/test_x_sub_agent.py` | Rewrite for new API; remove tests tied to deleted code |

## Component Design

### `factory.py`

```python
@dataclass(frozen=True)
class SubAgentSpec:
    name: str           # tool name CMO LLM sees
    description: str    # tool description
    system_prompt: str
    tools: list[BaseTool]

def build_agent(model, tools, system_prompt) -> Pregel:
    return create_agent(model, tools, system_prompt=system_prompt,
                        context_schema=AgentContext, checkpointer=InMemorySaver())

def as_tool(agent: Pregel, spec: SubAgentSpec, product_kb_id: int) -> BaseTool:
    @tool(spec.name, description=spec.description)
    async def _call(query: str) -> str:
        thread_id = str(uuid4())   # fresh thread per call → isolated memory
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": query}]},
            config={"configurable": {"thread_id": thread_id}},
            context=AgentContext(product_kb_id=product_kb_id),
        )
        return result["messages"][-1].content
    return _call

async def _load_web_search(settings) -> list[BaseTool]:
    # single shared loader; called once in AgentRuntime.__aenter__
```

### `registry.py`

```python
SUBAGENTS: list[SubAgentSpec] = [
    SubAgentSpec(
        name="write_x_post",
        description="Write one X (Twitter) post. Input: brief with topic, angle, reasoning.",
        system_prompt=X_SUB_AGENT_PROMPT,  # from prompts.py
        tools=[build_utm_url, create_post_draft, list_recent_posts],
    ),
    # Adding a new sub-agent = one more entry here
]
```

### `runtime.py`

```python
class AgentRuntime:
    def __init__(self, settings, pool): ...  # no I/O

    async def __aenter__(self) -> AgentRuntime:
        kb = await get_product_kb(pool)
        model = ChatOpenAI(...)
        web_search = await _load_web_search(settings)

        subagent_tools = [
            as_tool(build_agent(model, [*spec.tools, *web_search], spec.system_prompt), spec, kb.id)
            for spec in SUBAGENTS
        ]
        self._agent = build_agent(
            model,
            [create_post_idea, list_recent_posts, *web_search, *subagent_tools],
            build_system_prompt(kb),
        )
        self._kb_id = kb.id
        return self

    async def __aexit__(self, *a): self._agent = None

    async def run(self, thread_id: str, message: str) -> AsyncIterator[str]:
        async for event in self._agent.astream_events(..., context=AgentContext(product_kb_id=self._kb_id), version="v2"):
            if event["event"] == "on_chat_model_stream" and (c := event["data"]["chunk"].content):
                yield c
```

## Memory Isolation

| Boundary | Mechanism |
|---|---|
| Between sub-agents | Separate `Pregel` instances → separate `InMemorySaver` |
| Between calls to same sub-agent | Fresh `uuid4()` thread_id per `as_tool()` call |
| Sub-agent vs CMO | CMO sees only `messages[-1].content`, not sub-agent internals |
| Parallel calls | `InMemorySaver` keyed by `thread_id` — no collision |

## Sub-agent tool interface

CMO LLM calls each sub-agent tool with a single `query: str` — a free-form brief it composes
itself. No structured fields (topic/angle/reasoning) enforced at the tool level. CMO prompt
guides what to include in the brief.

`post_idea_id` is passed as an explicit argument to `create_post_draft` tool (already done),
not through `AgentContext`. It appears only at run time after CMO calls `create_post_idea`.

## Tests

- `test_x_sub_agent.py`: rewritten. Tests `as_tool()` name, and that `agent.ainvoke` is called
  with the query and returns `messages[-1].content`. Prompt builder tests unchanged.
- `test_telegram_bot.py`: no changes — mocks `cmo.run()` which has the same signature.

## What does NOT change

- `app/approval/handlers.py` — `handle_message` calls `cmo.run(thread_id, text)`, same interface
- `app/approval/session_store.py` — untouched
- `app/tools/` — untouched
- `app/approval/bot.py` — only DI wiring changes: one `async with AgentRuntime(...)` instead of two nested
