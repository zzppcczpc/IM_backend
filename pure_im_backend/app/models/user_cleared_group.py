"""
用户清空会话消息记录模型

用于记录用户清空某个会话消息的时间点。
清空操作只影响当前用户视角，不影响其他用户。

存储位置：MongoDB 中的 user_cleared_groups 集合

设计说明：
- 使用独立集合存储，原因是：
  1. 符合"用户维度设置"的语义 —— 一个用户可以清空多个会话
  2. 查询时通过 user_id + group_id 快速定位，性能好
  3. 清空记录与消息表分离，不影响原始消息数据
  4. 支持多次清空（更新清空时间点）

工作原理：
- 用户清空会话时，插入/更新一条记录：{user_id, group_id, cleared_at}
- 查询消息时，过滤 created_at > cleared_at 的消息
- 其他用户没有这条记录，所以不受影响
"""
import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class UserClearedGroup(BaseModel):
    """
    用户清空会话消息记录模型

    Attributes:
        id: 主键ID，唯一标识这条清空记录
        user_id: 用户ID，表示谁清空了这个会话
        group_id: 群组ID，表示被清空的会话
        cleared_at: 清空时间点，查询消息时过滤此时间之前的消息
        created_at: 记录创建时间
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str  # 用户ID，谁清空了这个会话
    group_id: str  # 群组/会话ID
    cleared_at: datetime = Field(default_factory=lambda: datetime.now())  # 清空时间点
    created_at: datetime = Field(default_factory=lambda: datetime.now())  # 记录创建时间

    class Config:
        populate_by_name = True
        json_schema_extra = {
            "example": {
                "user_id": "user-123",
                "group_id": "group-456",
                "cleared_at": "2026-08-12T10:30:00",
                "created_at": "2026-08-12T10:30:00"
            }
        }