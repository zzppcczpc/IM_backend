import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


KNOWLEDGE_BASE_FILE_STATUSES = {
    "uploaded",
    "parsing",
    "chunking",
    "vectorizing",
    "success",
    "failed",
}


class KnowledgeBaseFile(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    knowledge_base_id: str
    owner_id: str
    file_name: str
    file_type: str
    file_extension: str
    file_size: int
    local_file_path: str
    status: str = "uploaded"
    error_message: Optional[str] = None
    parsed_text: Optional[str] = None
    parse_metadata: dict[str, Any] = Field(default_factory=dict)
    chunk_count: int = 0
    vector_error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

