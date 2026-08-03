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
    created_at: datetime = Field(default_factory=lambda: datetime.now())

    class Config:
        populate_by_name = True
