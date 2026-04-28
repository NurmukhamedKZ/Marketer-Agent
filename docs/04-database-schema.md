# Database Schema

File: `migrations/001_initial_schema.sql`

```sql
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- =========================================
-- product_kb: single-row knowledge base
-- =========================================
CREATE TABLE product_kb (
    id              SERIAL PRIMARY KEY,
    product_name    TEXT NOT NULL,
    one_liner       TEXT NOT NULL,
    description     TEXT NOT NULL,
    icp             TEXT NOT NULL,
    brand_voice     TEXT NOT NULL,
    banned_topics   TEXT[] NOT NULL DEFAULT '{}',
    landing_url     TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Enforce singleton row in application code.

-- =========================================
-- signals: Reddit questions/posts
-- =========================================
CREATE TABLE signals (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source          TEXT NOT NULL,            -- 'reddit'
    source_id       TEXT NOT NULL,
    subreddit       TEXT,
    title           TEXT NOT NULL,
    body            TEXT,
    url             TEXT NOT NULL,
    author          TEXT,
    score           INT,
    raw_json        JSONB NOT NULL,
    used            BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '7 days'),
    UNIQUE (source, source_id)
);

CREATE INDEX idx_signals_unused_active
    ON signals (created_at DESC)
    WHERE used = FALSE AND expires_at > NOW();

-- =========================================
-- post_ideas: CMO Agent's strategic decisions
-- =========================================
-- The CMO writes a post_idea (topic + angle + target signal),
-- then delegates to a platform sub-agent which produces the final post.
CREATE TABLE post_ideas (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_id       UUID REFERENCES signals(id) ON DELETE SET NULL,
    target_platform TEXT NOT NULL,            -- 'x' for MVP
    topic           TEXT NOT NULL,            -- e.g. "leading indicators of churn"
    angle           TEXT NOT NULL,            -- e.g. "reactive dashboards are too late"
    cmo_reasoning   TEXT NOT NULL,            -- why the CMO picked this signal/angle
    state           TEXT NOT NULL DEFAULT 'open',  -- open | consumed | dropped
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    consumed_at     TIMESTAMPTZ
);

CREATE INDEX idx_post_ideas_open ON post_ideas (created_at DESC) WHERE state = 'open';

-- =========================================
-- posts: drafts → published, with state machine
-- =========================================
CREATE TYPE post_state AS ENUM (
    'draft',
    'pending',
    'approved',
    'rejected',
    'published',
    'failed'
);

CREATE TABLE posts (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform            TEXT NOT NULL,
    post_idea_id        UUID REFERENCES post_ideas(id) ON DELETE SET NULL,
    signal_id           UUID REFERENCES signals(id) ON DELETE SET NULL,

    draft_text          TEXT NOT NULL,
    final_text          TEXT,
    sub_agent_reasoning TEXT,

    state               post_state NOT NULL DEFAULT 'draft',
    rejection_reason    TEXT,

    platform_post_id    TEXT,
    platform_post_url   TEXT,
    utm_url             TEXT,

    impressions         INT NOT NULL DEFAULT 0,
    likes               INT NOT NULL DEFAULT 0,
    reposts             INT NOT NULL DEFAULT 0,
    replies             INT NOT NULL DEFAULT 0,
    clicks              INT NOT NULL DEFAULT 0,
    last_metrics_at     TIMESTAMPTZ,

    approval_message_id BIGINT,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at        TIMESTAMPTZ,
    failed_at           TIMESTAMPTZ,
    fail_reason         TEXT
);

CREATE INDEX idx_posts_state ON posts (state, created_at DESC);
CREATE INDEX idx_posts_platform_published
    ON posts (platform, published_at DESC)
    WHERE state = 'published';

-- updated_at triggers
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_posts_updated_at BEFORE UPDATE ON posts
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_product_kb_updated_at BEFORE UPDATE ON product_kb
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
```

## Post State Machine (`state_machine.py`)

Allowed transitions:

- `draft` → `pending`
- `pending` → `approved`
- `pending` → `rejected`
- `pending` → `pending` (edit; updates `final_text`)
- `approved` → `published`
- `approved` → `failed`
- `failed` → `approved` (manual retry)

Every other transition raises `InvalidStateTransition(post_id, from_state, to_state)`.
