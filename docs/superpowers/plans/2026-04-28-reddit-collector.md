# Reddit Signal Collector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a cron-triggered Reddit scraper that collects relevant posts and stores them as signals in the DB.

**Architecture:** Single module `app/signals/reddit_collector.py` with two private helpers (`_fetch_posts`, `_filter_posts`) and one public `collect(pool)` function. PRAW runs sync; asyncio.run() is used only in the `__main__` entry point. Deduplication is handled by `ON CONFLICT DO NOTHING` at the DB layer.

**Tech Stack:** `praw` (Reddit API), `asyncpg` (DB), `structlog` (logging), `pytest` + `pytest-asyncio` (tests)

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `pyproject.toml` | Modify | Add `praw` dependency |
| `app/signals/reddit_collector.py` | Create | Full collector: fetch, filter, upsert, `__main__` |
| `tests/test_reddit_collector.py` | Create | Unit tests for `_filter_posts`, integration test for `collect` |

---

### Task 0: Add `praw` dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add praw to project dependencies**

```bash
cd /Users/nurma/vscode_projects/Marketer-Agent
uv add praw
```

Expected: `pyproject.toml` updated, `uv.lock` updated, `praw` and `prawcore` installed in `.venv`.

- [ ] **Step 2: Verify import works**

```bash
uv run python -c "import praw; import prawcore; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add praw dependency"
```

---

### Task 1: Unit tests for `_filter_posts` + implementation

**Files:**
- Create: `app/signals/reddit_collector.py`
- Create: `tests/test_reddit_collector.py`

- [ ] **Step 1: Write the failing tests for `_filter_posts`**

Create `tests/test_reddit_collector.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/nurma/vscode_projects/Marketer-Agent
uv run pytest tests/test_reddit_collector.py -v
```

Expected: `ImportError: cannot import name '_filter_posts' from 'app.signals.reddit_collector'`

- [ ] **Step 3: Implement `_filter_posts` (and `_fetch_posts`) in the collector module**

Create `app/signals/reddit_collector.py`:

```python
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
```

- [ ] **Step 4: Run the unit tests to verify they pass**

```bash
uv run pytest tests/test_reddit_collector.py -v -k "not collect"
```

Expected: 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/signals/reddit_collector.py tests/test_reddit_collector.py
git commit -m "feat: implement reddit signal collector with unit tests"
```

---

### Task 2: Integration test for `collect`

**Files:**
- Modify: `tests/test_reddit_collector.py` (append integration tests)

- [ ] **Step 1: Write the failing integration tests**

Append to `tests/test_reddit_collector.py`:

```python
import asyncpg
import pytest


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
    # same post appears in both hot and new
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_reddit_collector.py::test_collect_saves_signals tests/test_reddit_collector.py::test_collect_deduplicates -v
```

Expected: FAIL — `collect` not yet imported in test file (need to add to import line at top).

- [ ] **Step 3: Add `collect` to the import at the top of the test file**

Change line 9 in `tests/test_reddit_collector.py`:

```python
from app.signals.reddit_collector import _filter_posts, collect
```

- [ ] **Step 4: Run integration tests to verify they pass**

```bash
uv run pytest tests/test_reddit_collector.py::test_collect_saves_signals tests/test_reddit_collector.py::test_collect_deduplicates -v
```

Expected: 2 tests PASS

- [ ] **Step 5: Run all collector tests**

```bash
uv run pytest tests/test_reddit_collector.py -v
```

Expected: 8 tests PASS

- [ ] **Step 6: Commit**

```bash
git add tests/test_reddit_collector.py
git commit -m "test: add integration tests for reddit collect upsert and deduplication"
```
