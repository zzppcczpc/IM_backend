"""
频率限制模型

用于记录验证码发送频率，防止滥用
"""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class RateLimit(BaseModel):
    """频率限制记录"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    # 限制类型：email_code / phone_code / password_reset
    limit_type: str
    # 标识符：邮箱/手机号/IP地址
    identifier: str
    # 创建时间
    created_at: datetime = Field(default_factory=lambda: datetime.now())
    # 过期时间（用于自动清理）
    expires_at: Optional[datetime] = None

    class Config:
        populate_by_name = True
        json_schema_extra = {
            "example": {
                "limit_type": "email_code",
                "identifier": "user@example.com",
            }
        }