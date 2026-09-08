from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field


class MessageData(BaseModel):
    id: str
    type: str
    content: str
    sender_id: str
    sender_username: str
    sender_avatar: Optional[str] = None
    group_id: str
    cite: Optional[dict] = None
    at_list: List[str] = Field(default_factory=list)
    read_list: List[str] = Field(default_factory=list)
    is_revoke: bool = False
    is_deleted: bool = False
    is_AI: bool = False
    is_streaming: bool = False
    stop: bool = False
    model_id: Optional[str] = None
    model_name: Optional[str] = None
    ai_parent_message_id: Optional[str] = None
    created_at: datetime
    duration: Optional[float] = None
    revoke_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    deleted_by_users: List[str] = Field(default_factory=list)  # 删除该消息的用户ID列表
    recommend_questions: List[str] = Field(default_factory=list)
    citations: List[dict] = Field(default_factory=list)
    error_message: Optional[str] = None


class MessageResponse(BaseModel):
    id: str
    type: str
    content: str
    sender_id: str
    sender_username: str
    sender_avatar: Optional[str] = None
    group_id: str
    cite: Optional[dict] = None
    at_list: List[str] = Field(default_factory=list)
    read_list: List[str] = Field(default_factory=list)
    is_revoke: bool = False
    is_deleted: bool = False
    is_AI: bool = False
    is_streaming: bool = False
    stop: bool = False
    model_id: Optional[str] = None
    model_name: Optional[str] = None
    ai_parent_message_id: Optional[str] = None
    created_at: datetime
    duration: Optional[float] = None
    revoke_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    is_read: bool = False
    deleted_by_users: List[str] = Field(default_factory=list)  # 删除该消息的用户ID列表
    recommend_questions: List[str] = Field(default_factory=list)
    citations: List[dict] = Field(default_factory=list)
    error_message: Optional[str] = None


class StopMessage(BaseModel):
    group_id: str
    message_id: str


class SendMessage(BaseModel):
    group_id: str
    content: str
    type: str = "text"
    cite: Optional[str] = None
    at_list: List[str] = Field(default_factory=list)


class HistoryRequest(BaseModel):
    group_id: str
    limit: int = 20
    before_id: Optional[str] = None


class OfflineRequest(BaseModel):
    group_id: str
    last_message_id: Optional[str] = None


class MarkReadRequest(BaseModel):
    group_id: str
    message_ids: List[str] = Field(default_factory=list)
