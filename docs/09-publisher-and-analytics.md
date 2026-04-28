# Publisher & Analytics

## X Publisher (`publisher/x_publisher.py`)

Triggered by the Telegram bot on approval. Posts via tweepy with 3 retries and exponential backoff. Transitions state to `published` or `failed`, notifies Telegram.

```python
async def publish_post(post_id: str) -> bool:
    pool = await get_pool()
    post = await pool.fetchrow("SELECT * FROM posts WHERE id = $1", post_id)
    if post["state"] != "approved":
        raise InvalidStateTransition(post_id, post["state"], "published")
    
    text_to_post = post["final_text"] or post["draft_text"]
    
    last_error = None
    for attempt in range(3):
        try:
            client = tweepy.Client(...)
            response = client.create_tweet(text=text_to_post)
            tweet_id = response.data["id"]
            await transition_post(
                post_id, from_state="approved", to_state="published",
                platform_post_id=tweet_id,
                platform_post_url=f"https://x.com/i/web/status/{tweet_id}",
                published_at=datetime.now(timezone.utc),
            )
            await notify_telegram_published(post_id, tweet_id)
            return True
        except tweepy.TweepyException as e:
            last_error = e
            log.error("publish_failed", attempt=attempt, error=str(e))
            await asyncio.sleep(2 ** attempt)
    
    await transition_post(
        post_id, from_state="approved", to_state="failed",
        fail_reason=str(last_error),
        failed_at=datetime.now(timezone.utc),
    )
    await notify_telegram_failed(post_id, str(last_error))
    return False
```

## Analytics Fetcher (`analytics/x_fetcher.py`)

Daily cron job. Selects published posts whose `last_metrics_at` is null or older than 12h, limit 100. Fetches `public_metrics` from X API v2 for each. Updates `impressions`, `likes`, `reposts`, `replies`, `last_metrics_at`.

> **MVP limitation:** `clicks` stays at 0 — click tracking is only via UTM parameters, not X API.
