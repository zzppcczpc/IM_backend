import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class AICallLog(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    model_id: Optional[str] = None
    model_name: Optional[str] = None
    success: bool = False
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    error_message: Optional[str] = None
    started_at: datetime = Field(default_factory=lambda: datetime.now())
    finished_at: datetime = Field(default_factory=lambda: datetime.now())

