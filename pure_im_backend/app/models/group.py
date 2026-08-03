import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class Group(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    owner_id: str
    last_message: dict = Field(default_factory=dict)
    is_dissolved: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now())
    organization_id: Optional[str] = None
    member_ids: List[str] = Field(default_factory=list)
    type: str = "group"  # group 或 private

    class Config:
        populate_by_name = True
        json_schema_extra = {
            "example": {
                "name": "技术讨论组",
                "owner_id": "user-123",
                "member_ids": ["user-123", "user-456"],
            }
        }


class GroupForward(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    group_id: str
    message_ids: List[str]
    forward_user_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now())

    class Config:
        populate_by_name = True
