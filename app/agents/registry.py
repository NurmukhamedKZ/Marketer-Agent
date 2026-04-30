from __future__ import annotations

from app.agents.factory import SubAgentSpec
from app.agents.prompts import build_x_sub_agent_prompt
from app.tools.posts import create_post_draft, list_recent_posts
from app.tools.utm_builder import build_utm_url

SUBAGENTS: list[SubAgentSpec] = [
    SubAgentSpec(
        name="write_x_post",
        description=(
            "Delegate writing a single X (Twitter) post to the X copywriter sub-agent. "
            "Input `query`: a free-form brief with topic, angle, and CMO reasoning. "
            "Input `post_idea_id`: the UUID returned by create_post_idea. "
            "The sub-agent saves the draft and returns a confirmation."
        ),
        system_prompt=build_x_sub_agent_prompt(),
        tools=[build_utm_url, create_post_draft, list_recent_posts],
    ),
]
