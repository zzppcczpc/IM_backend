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
    admin_ids: List[str] = Field(default_factory=list)
    # 群列表里先带上公告字段，前端刷新群列表时不会丢失已知公告状态。
    announcements: List[dict] = Field(default_factory=list)
    announcement_editor_ids: List[str] = Field(default_factory=list)
    muted_members: List[dict] = Field(default_factory=list)
    all_muted_until: Optional[datetime] = None
    all_muted_by: Optional[str] = None
    all_muted_at: Optional[datetime] = None


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
    admin_ids: List[str] = Field(default_factory=list)
    # 群详情会返回公告列表，打开群时前端可以直接拿到当前公告状态。
    announcements: List[dict] = Field(default_factory=list)
    announcement_editor_ids: List[str] = Field(default_factory=list)
    muted_members: List[dict] = Field(default_factory=list)
    all_muted_until: Optional[datetime] = None
    all_muted_by: Optional[str] = None
    all_muted_at: Optional[datetime] = None


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


class ForwardToGroupRequest(BaseModel):
    """转发消息到其他群的请求"""
    source_group_id: str  # 源群组ID
    target_group_id: str  # 目标群组ID
    message_ids: List[str]  # 要转发的消息ID列表


class ForwardToGroupResponse(BaseModel):
    """转发消息到其他群的响应"""
    source_group_id: str
    target_group_id: str
    forwarded_count: int
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


class GroupAnnouncementCreate(BaseModel):
    """发布群公告的请求体。只收公告内容，创建人和时间由后端根据登录用户生成。"""
    content: str = Field(min_length=1, max_length=2000)


class GroupAnnouncementUpdate(BaseModel):
    """修改群公告的请求体。公告 ID 从 URL 里取，避免请求体重复传。"""
    content: str = Field(min_length=1, max_length=2000)


class GroupAnnouncementResponse(BaseModel):
    """返回给前端的一条公告。除了用户 ID，也补充用户名，方便页面直接展示。"""
    id: str
    group_id: str
    content: str
    created_by: str
    created_by_username: Optional[str] = None
    created_at: datetime
    updated_by: str
    updated_by_username: Optional[str] = None
    updated_at: datetime


class GroupMemberRoleResponse(BaseModel):
    id: str
    user_id: str
    username: str
    avatar: Optional[str] = None
    role: str
    is_friend: bool = False


class GroupMembersWithRoleResponse(BaseModel):
    group_id: str
    members: List[GroupMemberRoleResponse] = Field(default_factory=list)


class GroupAdminUpdateResponse(BaseModel):
    group_id: str
    user_id: str
    role: str


# 新增：置顶设置请求模型
class MuteMemberRequest(BaseModel):
    minutes: int = Field(gt=0, le=43200)


class MuteMemberResponse(BaseModel):
    group_id: str
    user_id: str
    muted_by: str
    muted_at: datetime
    muted_until: datetime


class UnmuteMemberResponse(BaseModel):
    group_id: str
    user_id: str


class MuteAllRequest(BaseModel):
    minutes: int = Field(gt=0, le=43200)


class MuteAllResponse(BaseModel):
    group_id: str
    muted_by: str
    muted_at: datetime
    muted_until: datetime


class PinSetting(BaseModel):
    """置顶设置请求"""
    is_pinned: bool  # True=置顶, False=取消置顶


# 新增：置顶设置响应模型
class PinResponse(BaseModel):
    """置顶设置响应"""
    group_id: str
    is_pinned: bool
    pinned_at: Optional[datetime] = None  # 取消置顶时为 None
