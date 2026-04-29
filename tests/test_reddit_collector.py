import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import asyncpg
from app.signals.reddit_collector import _filter_posts, collect


def _make_post(
    id: str = "abc123",
    title: str = "How do I deploy this?",
    selftext: str = "",
    score: int = 5,
    created_utc: float | None = None,
    author: str = "user1",
    url: str = "https://reddit.com/r/SaaS/comments/abc123",
    subreddit: str = "SaaS",
) -> SimpleNamespace:
    if created_utc is None:
        created_utc = time.time() - 3600  # 1 hour ago
    mock_sub = MagicMock()
    mock_sub.display_name = subreddit
    return SimpleNamespace(
        id=id,
        title=title,
        selftext=selftext,
        score=score,
        created_utc=created_utc,
        author=author,
        url=url,
        subreddit=mock_sub,
    )


def test_filter_keeps_matching_post():
    posts = [_make_post(title="How do I scale my SaaS?", score=5)]
    result = _filter_posts(posts, keywords=["how do i"], max_age_hours=48, min_score=2)
    assert len(result) == 1


def test_filter_excludes_old_post():
    old_post = _make_post(created_utc=time.time() - 49 * 3600)
    result = _filter_posts([old_post], keywords=["how do i"], max_age_hours=48, min_score=2)
    assert result == []


def test_filter_excludes_low_score():
    post = _make_post(score=1)
    result = _filter_posts([post], keywords=["how do i"], max_age_hours=48, min_score=2)
    assert result == []


def test_filter_excludes_no_keyword_match():
    post = _make_post(title="Random unrelated post")
    result = _filter_posts(
        [post], keywords=["how do i", "alternative to"], max_age_hours=48, min_score=2
    )
    assert result == []


def test_filter_keyword_match_in_selftext():
    post = _make_post(title="Advice needed", selftext="struggling with deployment")
    result = _filter_posts([post], keywords=["struggling with"], max_age_hours=48, min_score=2)
    assert len(result) == 1


def test_filter_keyword_match_case_insensitive():
    post = _make_post(title="HOW DO I deploy?")
    result = _filter_posts([post], keywords=["how do i"], max_age_hours=48, min_score=2)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_collect_saves_signals(
    db_pool: asyncpg.Pool,
    seed_ids: tuple[int, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, product_kb_id = seed_ids

    await db_pool.execute("DELETE FROM signals WHERE product_kb_id = $1", product_kb_id)

    hot_post = _make_post(id="hot1", title="How do I scale SaaS?", score=10)
    new_post = _make_post(id="new1", title="Looking for CRM alternative to Salesforce", score=3)

    mock_subreddit = MagicMock()
    mock_subreddit.hot.return_value = [hot_post]
    mock_subreddit.new.return_value = [new_post]

    mock_reddit_instance = MagicMock()
    mock_reddit_instance.subreddit.return_value = mock_subreddit

    monkeypatch.setattr(
        "app.signals.reddit_collector.praw.Reddit",
        MagicMock(return_value=mock_reddit_instance),
    )

    from app.config import Settings

    fake_settings = Settings.model_construct(
        reddit_client_id="x",
        reddit_client_secret="x",
        reddit_user_agent="test",
        reddit_subreddits="SaaS",
        reddit_keywords="how do i,alternative to",
        reddit_max_age_hours=48,
        reddit_min_score=2,
    )
    monkeypatch.setattr("app.signals.reddit_collector.get_settings", lambda: fake_settings)

    count = await collect(db_pool)

    assert count == 2
    rows = await db_pool.fetch(
        "SELECT source_id FROM signals WHERE product_kb_id = $1", product_kb_id
    )
    source_ids = {r["source_id"] for r in rows}
    assert "hot1" in source_ids
    assert "new1" in source_ids


@pytest.mark.asyncio
async def test_collect_deduplicates(
    db_pool: asyncpg.Pool,
    seed_ids: tuple[int, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, product_kb_id = seed_ids

    await db_pool.execute("DELETE FROM signals WHERE product_kb_id = $1", product_kb_id)

    same_post = _make_post(id="dup1", title="How do I scale SaaS?", score=10)

    mock_subreddit = MagicMock()
    mock_subreddit.hot.return_value = [same_post]
    mock_subreddit.new.return_value = [same_post]

    mock_reddit_instance = MagicMock()
    mock_reddit_instance.subreddit.return_value = mock_subreddit

    monkeypatch.setattr(
        "app.signals.reddit_collector.praw.Reddit",
        MagicMock(return_value=mock_reddit_instance),
    )

    from app.config import Settings

    fake_settings = Settings.model_construct(
        reddit_client_id="x",
        reddit_client_secret="x",
        reddit_user_agent="test",
        reddit_subreddits="SaaS",
        reddit_keywords="how do i",
        reddit_max_age_hours=48,
        reddit_min_score=2,
    )
    monkeypatch.setattr("app.signals.reddit_collector.get_settings", lambda: fake_settings)

    count = await collect(db_pool)

    assert count == 1  # deduplicated in _fetch_posts, saved once
