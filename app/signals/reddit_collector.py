"""Reddit signal collector — runs as a cron job."""
import asyncio
import json
import time
from typing import Any

import asyncpg
import praw
import prawcore
import structlog

from app.config import get_settings
from app.db.queries import get_product_kb

logger = structlog.get_logger()


def _fetch_posts(
    reddit: praw.Reddit,
    subreddit_name: str,
    limit: int,
) -> list[Any]:
    sub = reddit.subreddit(subreddit_name)
    seen: set[str] = set()
    posts: list[Any] = []
    for submission in list(sub.hot(limit=limit)) + list(sub.new(limit=limit)):
        if submission.id not in seen:
            seen.add(submission.id)
            posts.append(submission)
    return posts


def _filter_posts(
    posts: list[Any],
    keywords: list[str],
    max_age_hours: int,
    min_score: int,
) -> list[Any]:
    now = time.time()
    result = []
    for post in posts:
        if now - post.created_utc > max_age_hours * 3600:
            continue
        if post.score < min_score:
            continue
        text = (post.title + " " + (post.selftext or "")).lower()
        if not any(kw.lower() in text for kw in keywords):
            continue
        result.append(post)
    return result


async def collect(pool: asyncpg.Pool) -> int:
    settings = get_settings()
    product_kb = await get_product_kb(pool)
    if product_kb is None:
        logger.error("reddit_collector.no_product_kb")
        return 0

    reddit = praw.Reddit(
        client_id=settings.reddit_client_id,
        client_secret=settings.reddit_client_secret,
        user_agent=settings.reddit_user_agent,
    )

    subreddits = [s.strip() for s in settings.reddit_subreddits.split(",")]
    keywords = [k.strip() for k in settings.reddit_keywords.split(",")]

    logger.info("reddit_collector.start", subreddits=subreddits, product_kb_id=product_kb.id)

    total_saved = 0

    for subreddit_name in subreddits:
        try:
            posts = _fetch_posts(reddit, subreddit_name, limit=50)
            filtered = _filter_posts(
                posts, keywords, settings.reddit_max_age_hours, settings.reddit_min_score
            )
            logger.info(
                "reddit_collector.subreddit",
                subreddit=subreddit_name,
                fetched=len(posts),
                filtered=len(filtered),
            )
        except prawcore.exceptions.PrawcoreException as exc:
            logger.warning(
                "reddit_collector.subreddit_error",
                subreddit=subreddit_name,
                error=str(exc),
            )
            continue

        for post in filtered:
            try:
                author = str(post.author) if post.author else None
                raw_json = {
                    "id": post.id,
                    "title": post.title,
                    "selftext": post.selftext,
                    "score": post.score,
                    "url": post.url,
                    "author": author,
                    "created_utc": post.created_utc,
                    "subreddit": subreddit_name,
                }
                result = await pool.execute(
                    """
                    INSERT INTO signals
                        (product_kb_id, source, source_id, subreddit, title, body,
                         url, author, score, raw_json)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    ON CONFLICT (product_kb_id, source, source_id) DO NOTHING
                    """,
                    product_kb.id,
                    "reddit",
                    post.id,
                    subreddit_name,
                    post.title,
                    post.selftext or None,
                    post.url,
                    author,
                    post.score,
                    json.dumps(raw_json),
                )
                if result == "INSERT 0 1":
                    total_saved += 1
            except asyncpg.PostgresError as exc:
                logger.warning(
                    "reddit_collector.insert_error", post_id=post.id, error=str(exc)
                )

    logger.info("reddit_collector.done", total_saved=total_saved)
    return total_saved


if __name__ == "__main__":
    from app.db.pool import close_pool, get_pool

    async def _main() -> None:
        pool = await get_pool()
        count = await collect(pool)
        await close_pool()
        print(f"Saved {count} signals")

    asyncio.run(_main())
