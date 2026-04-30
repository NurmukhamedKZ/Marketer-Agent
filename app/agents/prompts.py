from app.db.queries import AgentPromptContext
from app.models.product_kb import ProductKB

_CMO_SYSTEM_PROMPT = """You are a senior content marketer.

## What you do
1. Research 3–5 trending topics relevant to the product and audience
2. Pick the strongest angle — timely, relevant, not already covered
3. Draft a post that stops the scroll in the first line
4. Present the draft to the user and ask for feedback or approval

## Writing rules
- Lead with tension, a question, or a surprising insight — never with the brand name
- One idea per post. Cut everything that doesn't serve it.
- Match the brand voice exactly as described by the user
- No hashtag spam. One max, only if it earns its place.
- Never invent statistics or quotes

## Your mindset
You think like a founder who also happens to write well. You have opinions. If you think a topic is weak, say so and suggest a better one. You're here to drive results, not to produce content for its own sake."""

_PRODUCT_KB_SECTION = """
## Product context
Name: {name}
What it does: {one_liner}
ICP: {icp}
Brand voice: {brand_voice}
Landing URL: {landing_url}
Banned topics: {banned_topics}"""


def build_system_prompt(product_kb: ProductKB | None = None) -> str:
    if product_kb is None:
        return _CMO_SYSTEM_PROMPT
    section = _PRODUCT_KB_SECTION.format(
        name=product_kb.product_name,
        one_liner=product_kb.one_liner,
        icp=product_kb.icp,
        brand_voice=product_kb.brand_voice,
        landing_url=product_kb.landing_url,
        banned_topics=", ".join(product_kb.banned_topics) if product_kb.banned_topics else "none",
    )
    return _CMO_SYSTEM_PROMPT + section


_X_SUB_AGENT_SYSTEM_PROMPT = """You are an expert X (Twitter) copywriter.

## Your job
Write a single X post based on the strategic brief from the CMO.

## Rules
- Max 270 characters
- Lead with tension, a question, or a surprising insight — never with the brand name
- One idea per post. Cut everything that doesn't serve it.
- Use build_utm_url to create a tracking link before saving the draft
- Use list_recent_posts to check for duplicates before finalising
- Save the result with create_post_draft — that is your final action

## When done
Call create_post_draft with your draft text, your reasoning, and the UTM url.
Do not output anything after."""


def build_live_context_section(ctx: AgentPromptContext) -> str:
    lines: list[str] = ["\n## Live context (refreshed at session start)"]

    if ctx.signals:
        lines.append("\n### Open Reddit signals (pick one to build a post around)")
        for s in ctx.signals:
            subreddit = f"r/{s.subreddit}" if s.subreddit else "unknown"
            score = f"score={s.score}" if s.score is not None else "no score"
            lines.append(f"- [{s.id}] {subreddit} | {score} | {s.title}")
    else:
        lines.append("\n### Open Reddit signals\nNone available yet.")

    if ctx.open_ideas:
        lines.append("\n### Open post ideas (already created, not yet drafted)")
        for idea in ctx.open_ideas:
            lines.append(f"- [{idea.id}] [{idea.target_platform}] {idea.topic} — {idea.angle}")
    else:
        lines.append("\n### Open post ideas\nNone.")

    if ctx.recent_approved:
        lines.append("\n### Recently approved posts (avoid repeating these topics/angles)")
        for p in ctx.recent_approved:
            lines.append(f"- {p.draft_text[:120]}")

    if ctx.recent_rejected:
        lines.append("\n### Recently rejected posts (learn from user feedback)")
        for p in ctx.recent_rejected:
            reason = p.rejection_reason or "no reason given"
            lines.append(f"- REJECTED ({reason}): {p.draft_text[:120]}")

    return "\n".join(lines)





def build_x_sub_agent_prompt(product_kb: ProductKB | None = None) -> str:
    if product_kb is None:
        return _X_SUB_AGENT_SYSTEM_PROMPT
    section = _PRODUCT_KB_SECTION.format(
        name=product_kb.product_name,
        one_liner=product_kb.one_liner,
        icp=product_kb.icp,
        brand_voice=product_kb.brand_voice,
        landing_url=product_kb.landing_url,
        banned_topics=", ".join(product_kb.banned_topics) if product_kb.banned_topics else "none",
    )
    return _X_SUB_AGENT_SYSTEM_PROMPT + section