import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.signals.reddit_collector import _filter_posts


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
