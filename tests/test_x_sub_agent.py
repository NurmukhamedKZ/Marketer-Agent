from datetime import datetime

import pytest

from app.agents.prompts import build_x_sub_agent_prompt, build_x_subagent_message
from app.models.product_kb import ProductKB


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


def test_build_x_subagent_message_no_retry():
    msg = build_x_subagent_message(
        topic="SaaS pricing",
        angle="Year 1 mistakes",
        cmo_reasoning="High engagement topic",
        retry_context=None,
    )
    assert "Topic: SaaS pricing" in msg
    assert "Angle: Year 1 mistakes" in msg
    assert "CMO reasoning: High engagement topic" in msg
    assert "Previous attempt" not in msg


def test_build_x_subagent_message_with_retry_includes_context():
    msg = build_x_subagent_message(
        topic="SaaS pricing",
        angle="Year 1 mistakes",
        cmo_reasoning="High engagement topic",
        retry_context="post was too long, exceeded 270 chars",
    )
    assert "Previous attempt failed: post was too long, exceeded 270 chars" in msg
    assert "Try a different approach" in msg


from unittest.mock import AsyncMock, MagicMock


def test_make_invoke_x_sub_agent_tool_returns_tool_with_correct_name():
    from app.agents.x_sub_agent_service import make_invoke_x_sub_agent_tool

    mock_service = MagicMock()
    tool_fn = make_invoke_x_sub_agent_tool(mock_service)
    assert tool_fn.name == "invoke_x_sub_agent"


@pytest.mark.asyncio
async def test_make_invoke_x_sub_agent_tool_calls_service_run():
    from app.agents.x_sub_agent_service import make_invoke_x_sub_agent_tool
    from uuid import UUID

    mock_service = AsyncMock()
    mock_service.run.return_value = "Great post written"

    tool_fn = make_invoke_x_sub_agent_tool(mock_service)

    mock_runtime = MagicMock()
    mock_runtime.context.product_kb_id = 42

    # Call the underlying coroutine function directly, bypassing ToolRuntime injection
    post_idea_uuid = "12345678-1234-5678-1234-567812345678"
    result = await tool_fn.coroutine(
        post_idea_id=post_idea_uuid,
        topic="SaaS pricing",
        angle="Year 1 mistakes",
        cmo_reasoning="High engagement",
        retry_context=None,
        runtime=mock_runtime,
    )

    assert mock_service.run.called
    call_kwargs = mock_service.run.call_args
    # message arg (positional 0) contains topic
    assert "SaaS pricing" in call_kwargs.args[0]
    # product_kb_id matches runtime context
    assert call_kwargs.args[2] == 42
    # post_idea_id is UUID
    assert call_kwargs.args[3] == UUID(post_idea_uuid)
    assert result == {"result": "Great post written"}
