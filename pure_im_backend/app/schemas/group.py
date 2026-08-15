from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field


class GroupCreate(BaseModel):
    name: str
    member_ids: List[str] = Field(default_factory=list)
    owner_id: Optional[str] = None
    type: str = "group"  # group 或 private


class GroupResponse(BaseModel):
    id: str
    name: str
    owner_id: str
    member_ids: List[str] = Field(default_factory=list)
    last_message: Optional[dict] = None
    is_dissolved: bool = False
    created_at: datetime
    type: str = "group"
    unread_count: int = 0
    was_at: bool = False
    # 新增：用户维度的置顶设置
    is_pinned: bool = False  # 是否置顶
    pinned_at: Optional[datetime] = None  # 置顶时间


class GroupCreateResponse(BaseModel):
    id: str
    name: str
    owner_id: str
    member_ids: List[str] = Field(default_factory=list)
    last_message: Optional[dict] = None
    is_dissolved: bool = False
    created_at: datetime
    type: str = "group"


class GroupDetailResponse(BaseModel):
    id: str
    name: str
    owner_id: str
    member_ids: List[str] = Field(default_factory=list)
    last_message: Optional[dict] = None
    is_dissolved: bool = False
    created_at: datetime
    type: str = "group"
    members: List[dict] = Field(default_factory=list)
    total_unread: int = 0


class GroupInquiry(BaseModel):
    name: Optional[str] = None
    page: int = 1
    page_size: int = 10
    is_owner: bool = False
    list_share: bool = False


class GroupMemberManage(BaseModel):
    group_id: str
    user_ids: List[str]


#    search_data: GroupMessageSearch 就是一个 请求参数的数据容器，它：
#     接收前端传来的查询参数（群组ID、分页、起始时间）
#       自动验证参数类型和必填字段
#       简化后端代码，让逻辑更清晰
class GroupMessageSearch(BaseModel):
    id: str
    page: int = 1
    page_size: int = 20
    start_index: Optional[str] = None


class GroupReadUpdate(BaseModel):
    group_id: str
    message_ids: List[str]


class GroupForwardMessage(BaseModel):
    group_id: str
    message_ids: List[str]


class ForwardMessage(BaseModel):
    id: str
    group_id: str
    messages: List[dict]
    forward_user_id: str
    created_at: datetime


class MessageSearch(BaseModel):
    group_id: str
    message_content: str
    page: int = 1
    page_size: int = 20


# 新增：置顶设置请求模型
class PinSetting(BaseModel):
    """置顶设置请求"""
    is_pinned: bool  # True=置顶, False=取消置顶


# 新增：置顶设置响应模型
class PinResponse(BaseModel):
    """置顶设置响应"""
    group_id: str
    is_pinned: bool
    pinned_at: Optional[datetime] = None  # 取消置顶时为 None
