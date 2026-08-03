import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class TokenBlacklist(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    token: str
    user_id: str
    expired_at: datetime

    class Config:
        populate_by_name = True