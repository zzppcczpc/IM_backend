import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class GroupFileChunk(BaseModel):
    """群文件的 Chunk 业务记录，向量副本存放在 Milvus。"""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    group_id: str
    file_id: str
    chunk_index: int
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)
