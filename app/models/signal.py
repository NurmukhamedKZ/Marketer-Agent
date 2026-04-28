from datetime import datetime
from uuid import UUID
from pydantic import BaseModel


class Signal(BaseModel):
    id: UUID
    source: str
    source_id: str
    subreddit: str | None
    title: str
    body: str | None
    url: str
    author: str | None
    score: int | None
    raw_json: dict
    used: bool
    created_at: datetime
    expires_at: datetime
