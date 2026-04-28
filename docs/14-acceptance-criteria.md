# Acceptance Criteria

The MVP is done when:

- [ ] The schema migration applies cleanly to a fresh Postgres 18 instance
- [ ] Running the product KB setup populates `product_kb` interactively
- [ ] The Reddit collector inserts new rows into `signals` from configured subreddits, with dedup
- [ ] Running the CMO cycle:
  - Starts the CMO Agent
  - CMO connects to MCP servers, reads signals, creates up to `CMO_IDEAS_PER_RUN` post_ideas
  - For each idea, the X Sub-Agent runs, produces a draft, persists to `posts`, and a Telegram message arrives in the owner's chat with three working buttons
- [ ] ✅ **Approve** publishes within 30s and `posts.state` becomes `published` with `platform_post_id` set
- [ ] ❌ **Reject** prompts for a reason (or `/skip`); reason is stored; state becomes `rejected`
- [ ] ✏️ **Edit** accepts a free-text reply, updates `final_text`, re-renders the message with new text and buttons, and ✅ then publishes the edited version
- [ ] The analytics fetcher updates metrics on published posts
- [ ] All components log structured JSON with `component`, `operation`, `duration`, and IDs
- [ ] `pytest` passes with the required tests
- [ ] The state machine rejects invalid transitions in tests
- [ ] Running cron for one full day produces at least one published post (assuming Reddit yields suitable signals)
