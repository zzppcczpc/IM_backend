import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, EmailStr


class User(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    username: str
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    hashed_password: str
    is_active: bool = False
    avatar: Optional[str] = None
    verification_code: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now())
    last_offline_time: Optional[datetime] = None  # 上次离线时间，用于查询离线消息
    department_id: Optional[str] = None
    friends: List[str] = Field(default_factory=list)
    friend_requests: List[dict] = Field(default_factory=list)
    is_temp_user: bool = False

    class Config:
        populate_by_name = True
        json_schema_extra = {
            "example": {
                "username": "johndoe",
                "email": "johndoe@example.com",
                "is_active": True,
            }
        }

    def __getattribute__(self, name: str):
        value = super().__getattribute__(name)
        if isinstance(value, datetime):
            return datetime.strftime(value, "%Y-%m-%d %H:%M:%S")
        return value
