from datetime import datetime
from uuid import UUID
from pydantic import BaseModel


class PostIdea(BaseModel):
    id: UUID
    signal_id: UUID | None
    target_platform: str
    topic: str
    angle: str
    cmo_reasoning: str
    state: str
    created_at: datetime
    consumed_at: datetime | None
