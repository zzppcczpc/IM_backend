import uuid
from datetime import datetime
from typing import List

from pydantic import BaseModel, Field


class KnowledgeBase(BaseModel):
    """知识库元数据；文件、向量和检索数据由后续需求扩展。"""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: str = ""
    owner_id: str
    member_ids: List[str] = Field(default_factory=list)
    file_count: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

