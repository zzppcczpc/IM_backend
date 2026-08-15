"""
用户置顶群组模型

用于存储用户维度的会话置顶设置。
每个用户可以对自己所在的群聊/私聊进行置顶操作，
置顶后该会话会显示在用户的会话列表顶部。

存储位置：MongoDB 中的 user_pinned_groups 集合

设计说明：
- 使用独立集合而非嵌入到 users 或 groups 中，原因是：
  1. 符合"用户维度设置"的语义 —— 一个用户可以对多个群置顶
  2. 查询时通过 user_id 索引快速定位，性能好
  3. 未来扩展性强（如支持置顶顺序拖拽调整）
"""
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class UserPinnedGroup(BaseModel):
    """
    用户置顶群组模型

    Attributes:
        id: 主键ID，用来唯一标识和操作这条记录。
        user_id: 用户ID，表示谁置顶了这个群
        group_id: 群组ID，表示被置顶的群
        pinned_at: 置顶时间，用于排序（最近置顶的排在前面）
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str  # 用户ID，谁置顶了这个群
    group_id: str  # 群组ID
    pinned_at: datetime = Field(default_factory=lambda: datetime.now())  # 置顶时间

    class Config:
        populate_by_name = True  # 允许通过字段名或别名来赋值。
        json_schema_extra = {  #示例
            "example": { 
                "user_id": "user-123",
                "group_id": "group-456",
                "pinned_at": "2026-08-14T10:00:00"
            }
        }