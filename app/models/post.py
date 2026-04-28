from datetime import datetime
from enum import Enum
from uuid import UUID
from pydantic import BaseModel


class PostState(str, Enum):
    draft = "draft"
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    published = "published"
    failed = "failed"


class Post(BaseModel):
    id: UUID
    product_kb_id: int
    platform: str
    post_idea_id: UUID | None
    signal_id: UUID | None
    draft_text: str
    final_text: str | None
    sub_agent_reasoning: str | None
    state: PostState
    rejection_reason: str | None
    platform_post_id: str | None
    platform_post_url: str | None
    utm_url: str | None
    impressions: int
    likes: int
    reposts: int
    replies: int
    clicks: int
    last_metrics_at: datetime | None
    approval_message_id: int | None
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None
    failed_at: datetime | None
    fail_reason: str | None
