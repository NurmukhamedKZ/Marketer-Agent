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
            "Call this AFTER create_post_idea has returned a post_idea_id.\n\n"
            "Args:\n"
            "  query: Free-form brief, 3-8 sentences. Must include: the topic, the "
            "angle (the thesis the post will defend), the CMO reasoning (why this "
            "angle now), and any constraints (tone, must-include link, banned phrases). "
            "Do NOT pre-write the post — that is the sub-agent's job.\n"
            "  post_idea_id: UUID string returned by create_post_idea, exactly as given.\n\n"
            "Returns: A confirmation string from the sub-agent including the saved "
            "post_id and the draft text. The draft is already persisted in the DB "
            "with state='draft' — you do not need to save it again.\n\n"
            "Edge cases:\n"
            "  - Call once per post_idea_id. Re-calling will create duplicate drafts.\n"
            "  - If the returned draft is unsatisfactory, do NOT call again with the "
            "    same id; create a new post_idea with a sharper angle instead."
        ),
        system_prompt=build_x_sub_agent_prompt(),
        tools=[build_utm_url, create_post_draft, list_recent_posts],
    ),
]
