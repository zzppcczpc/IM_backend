import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class File(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    file_name: str
    file_type: str
    file_size: float
    local_file_path: Optional[str] = None
    cloud_file_path: Optional[str] = None
    owner_id: str
    group_id: Optional[str] = None
    is_deleted: bool = False
    # 群文件按需解析：第一次被 AI 使用时解析并缓存结果。
    parse_status: str = "pending"
    parsed_text: Optional[str] = None
    parse_metadata: dict = Field(default_factory=dict)
    parse_error: Optional[str] = None
    parsed_at: Optional[datetime] = None
    chunk_count: int = 0
    vector_error: Optional[str] = None
    extraction_type: Optional[str] = None
    extraction_status: str = "not_required"
    extraction_error: Optional[str] = None
    extraction_metadata: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now())

    class Config:
        populate_by_name = True
