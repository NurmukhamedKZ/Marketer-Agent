from datetime import datetime

import pytest

from app.agents.prompts import build_x_sub_agent_prompt
from app.models.product_kb import ProductKB


def test_agent_context_has_no_signal_id():
    from app.agents.context import AgentContext
    import dataclasses
    fields = {f.name for f in dataclasses.fields(AgentContext)}
    assert "signal_id" not in fields
    assert "product_kb_id" in fields
    assert "post_idea_id" in fields


def _make_kb(**overrides) -> ProductKB:
    defaults = dict(
        id=1,
        user_id=1,
        product_name="TestProduct",
        one_liner="A test product",
        description="desc",
        icp="developers",
        brand_voice="friendly",
        banned_topics=["politics"],
        landing_url="https://example.com",
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )
    defaults.update(overrides)
    return ProductKB(**defaults)


def test_build_x_sub_agent_prompt_no_kb_contains_role():
    prompt = build_x_sub_agent_prompt(None)
    assert "X (Twitter) copywriter" in prompt


def test_build_x_sub_agent_prompt_no_kb_contains_tool_instructions():
    prompt = build_x_sub_agent_prompt(None)
    assert "create_post_draft" in prompt
    assert "build_utm_url" in prompt
    assert "list_recent_posts" in prompt


def test_build_x_sub_agent_prompt_with_kb_contains_product_name():
    prompt = build_x_sub_agent_prompt(_make_kb())
    assert "TestProduct" in prompt


def test_build_x_sub_agent_prompt_with_kb_contains_icp():
    prompt = build_x_sub_agent_prompt(_make_kb())
    assert "developers" in prompt


def test_build_x_sub_agent_prompt_with_kb_contains_banned_topics():
    prompt = build_x_sub_agent_prompt(_make_kb())
    assert "politics" in prompt


def test_subagent_spec_is_frozen_dataclass():
    import dataclasses
    from app.agents.factory import SubAgentSpec

    spec = SubAgentSpec(name="test", description="desc", system_prompt="prompt", tools=[])
    assert dataclasses.is_dataclass(spec)
    # frozen — mutation raises FrozenInstanceError
    try:
        spec.name = "other"  # type: ignore[misc]
        assert False, "should have raised"
    except dataclasses.FrozenInstanceError:
        pass


def test_as_tool_returns_tool_with_spec_name():
    from unittest.mock import MagicMock
    from app.agents.factory import SubAgentSpec, as_tool

    spec = SubAgentSpec(name="write_x_post", description="Write an X post.", system_prompt="", tools=[])
    mock_agent = MagicMock()
    tool_fn = as_tool(mock_agent, spec, product_kb_id=1)
    assert tool_fn.name == "write_x_post"


@pytest.mark.asyncio
async def test_as_tool_calls_ainvoke_and_returns_last_message():
    from unittest.mock import MagicMock, AsyncMock
    from langchain_core.messages import AIMessage
    from app.agents.factory import SubAgentSpec, as_tool

    spec = SubAgentSpec(name="write_x_post", description="Write an X post.", system_prompt="", tools=[])

    mock_agent = MagicMock()
    mock_agent.ainvoke = AsyncMock(return_value={
        "messages": [AIMessage(content="ignored"), AIMessage(content="Final post text")]
    })

    tool_fn = as_tool(mock_agent, spec, product_kb_id=42)

    result = await tool_fn.coroutine(
        query="Write a post about SaaS pricing",
        post_idea_id="12345678-1234-5678-1234-567812345678",
    )

    assert result == "Final post text"
    mock_agent.ainvoke.assert_called_once()
    call_args = mock_agent.ainvoke.call_args
    assert "Write a post about SaaS pricing" in call_args[0][0]["messages"][0]["content"]
    assert call_args.kwargs["context"].product_kb_id == 42


@pytest.mark.asyncio
async def test_agent_runtime_run_streams_tokens():
    from unittest.mock import MagicMock, AsyncMock, patch
    from app.agents.runtime import AgentRuntime

    # Build a runtime with a pre-built mock agent (bypass __aenter__)
    runtime = object.__new__(AgentRuntime)
    runtime._kb_id = 1

    async def fake_astream_events(*args, **kwargs):
        for content in ["Hello", " world"]:
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": MagicMock(content=content)},
            }

    mock_agent = MagicMock()
    mock_agent.astream_events = fake_astream_events
    runtime._agent = mock_agent

    tokens = []
    async for token in runtime.run("thread-1", "test message"):
        tokens.append(token)

    assert "".join(tokens) == "Hello world"