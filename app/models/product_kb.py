from datetime import datetime
from pydantic import BaseModel


class ProductKB(BaseModel):
    id: int
    user_id: int
    product_name: str
    one_liner: str
    description: str
    icp: str
    brand_voice: str
    banned_topics: list[str]
    landing_url: str
    created_at: datetime
    updated_at: datetime
