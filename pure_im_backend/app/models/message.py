import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class Message(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: str
    content: str
    sender_id: str
    sender_avatar: Optional[str] = None
    sender_username: str
    group_id: str
    receiver: list = Field(default_factory=list)
    cite: Optional[dict] = None
    at_list: list = Field(default_factory=list)
    read_list: list = Field(default_factory=list)
    is_revoke: bool = False
    is_deleted: bool = False  # 新增：软删除标记
    created_at: datetime = Field(default_factory=lambda: datetime.now())
    duration: Optional[float] = None  # 语音时长
    sound_file_id: Optional[str] = None  # 语音文件ID
    revoke_at: Optional[datetime] = None  # 新增：撤回时间
    deleted_at: Optional[datetime] = None  # 新增：删除时间

    class Config:
        populate_by_name = True
        json_schema_extra = {
            "example": {
                "content": "消息内容",
                "sender_id": "user-123",
                "group_id": "group-456",
            }
        }

    def json(self, **kwargs):
        data = super().json(**kwargs)
        import json
        data_dict = json.loads(data)
        data_dict["created_at"] = self.created_at.strftime("%Y%m%d%H%M%S")
        if self.revoke_at:
            data_dict["revoke_at"] = self.revoke_at.strftime("%Y%m%d%H%M%S")
        return json.dumps(data_dict)
