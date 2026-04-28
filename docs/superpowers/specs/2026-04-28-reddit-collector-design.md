---
title: Reddit Signal Collector — Design Spec
date: 2026-04-28
status: approved
---

# Reddit Signal Collector

## Purpose

Cron-triggered script that scrapes Reddit for relevant posts and stores them as signals in the DB. No AI involved — pure data collection.

## Flow

```
cron → python -m app.signals.reddit_collector
         ↓
      get_product_kb(pool)          # one product_kb for MVP
         ↓
      for subreddit in subreddits:
          fetch hot(50) + new(50)   # PRAW sync
          deduplicate by source_id  # in-memory set
          filter by age ≤ 48h       # submission.created_utc
          filter by score ≥ 2
          filter by keyword match   # title + selftext
         ↓
      upsert signals to DB          # ON CONFLICT DO NOTHING
         ↓
      structlog summary
```

## Components

Single file: `app/signals/reddit_collector.py`

### Functions

- `_fetch_posts(reddit, subreddit_name, limit) -> list[Submission]`
  Fetches `hot(limit)` + `new(limit)`, deduplicates by `submission.id` in memory.

- `_filter_posts(posts, keywords, max_age_hours, min_score) -> list[Submission]`
  Filters locally:
  - `time.time() - submission.created_utc <= max_age_hours * 3600`
  - `submission.score >= min_score`
  - any keyword (case-insensitive) found in `submission.title + submission.selftext`

- `collect(pool: asyncpg.Pool) -> int`
  Public entry point. Initialises PRAW from settings, fetches product_kb, iterates subreddits, upserts results. Returns count of rows saved.

- `if __name__ == "__main__"` block
  Creates DB pool, calls `asyncio.run(collect(pool))`, exits.

### PRAW → Signal mapping

| Signal field    | PRAW source                        |
|-----------------|------------------------------------|
| source          | `'reddit'` (literal)               |
| source_id       | `submission.id`                    |
| subreddit       | `submission.subreddit.display_name`|
| title           | `submission.title`                 |
| body            | `submission.selftext or None`      |
| url             | `submission.url`                   |
| author          | `str(submission.author) or None`   |
| score           | `submission.score`                 |
| raw_json        | dict of selected submission fields |

### Upsert

```sql
INSERT INTO signals (product_kb_id, source, source_id, subreddit, title, body,
                     url, author, score, raw_json)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
ON CONFLICT (product_kb_id, source, source_id) DO NOTHING
```

## Config used

From `Settings` (already defined in `app/config.py`):

| Setting                | Default                            |
|------------------------|------------------------------------|
| `reddit_client_id`     | —                                  |
| `reddit_client_secret` | —                                  |
| `reddit_user_agent`    | `mktg-agent/0.1 by /u/yourusername`|
| `reddit_subreddits`    | `SaaS,startups,Entrepreneur,smallbusiness` |
| `reddit_keywords`      | `how do I,alternative to,...`      |
| `reddit_max_age_hours` | `48`                               |
| `reddit_min_score`     | `2`                                |

## Error handling

- `prawcore.exceptions.*` per subreddit → log warning, skip subreddit, continue
- DB errors per row → log warning, continue
- No retry — cron reruns on next schedule

## Logging (structlog)

- Start: subreddits list, product_kb_id
- Per subreddit: posts fetched, posts after filter
- End: total saved to DB

## Tests

`tests/test_reddit_collector.py`

1. **`test_filter_posts`** — unit, no DB, no PRAW. Creates mock Submission objects, verifies `_filter_posts` correctly applies age/score/keyword filters.

2. **`test_collect_upsert`** — integration, real DB pool from `conftest.py`, PRAW monkeypatched. Verifies `collect()` returns correct count and signal rows exist in DB.
