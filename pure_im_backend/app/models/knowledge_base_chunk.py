import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class KnowledgeBaseChunk(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    knowledge_base_id: str
    file_id: str
    chunk_index: int
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)

