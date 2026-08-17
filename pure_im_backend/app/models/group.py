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
    # Admins are a subset of member_ids. owner_id is still the only owner.
    admin_ids: List[str] = Field(default_factory=list)

    # 群公告直接嵌在群文档里：一个群对应一个公告列表，适合当前“公告数量不大”的场景。
    # 每条公告是 dict：id/content/created_by/created_at/updated_by/updated_at。
    announcements: List[dict] = Field(default_factory=list)

    # 预留扩展字段：以后如果要让群管理员也能发公告，把用户 ID 放到这里即可。
    # 当前页面主要还是用 owner_id 判断群主权限。
    announcement_editor_ids: List[str] = Field(default_factory=list)

    # 单人禁言列表：每条记录存 user_id、muted_by、muted_at、muted_until。
    # 全员禁言只需要存截止时间；为空或已过期就表示没有开启。
    muted_members: List[dict] = Field(default_factory=list)
    all_muted_until: Optional[datetime] = None
    all_muted_by: Optional[str] = None
    all_muted_at: Optional[datetime] = None

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
