from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)


class KnowledgeBaseUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=2000)


class KnowledgeBaseResponse(BaseModel):
    id: str
    name: str
    description: str = ""
    owner_id: str
    member_ids: list[str] = Field(default_factory=list)
    file_count: int = 0
    created_at: datetime
    updated_at: datetime

