"""
频率限制工具

防止验证码接口被滥用
"""

from datetime import datetime, timedelta
from typing import Optional

from ..models.rate_limit import RateLimit


async def check_rate_limit(
    db,
    limit_type: str,
    identifier: str,
    max_requests: int = 1,
    window_seconds: int = 60,
) -> tuple[bool, Optional[str]]:
    """
    检查频率限制

    Args:
        db: 数据库连接
        limit_type: 限制类型（email_code / phone_code / password_reset）
        identifier: 标识符（邮箱/手机号/IP地址）
        max_requests: 时间窗口内最大请求数，默认1次
        window_seconds: 时间窗口（秒），默认60秒

    Returns:
        tuple[bool, Optional[str]]: (是否允许, 错误消息)
    """
    # 计算时间窗口起始时间
    window_start = datetime.now() - timedelta(seconds=window_seconds)

    # 查询时间窗口内的请求次数
    count = await db.rate_limits.count_documents({
        "limit_type": limit_type,
        "identifier": identifier,
        "created_at": {"$gt": window_start},
    })

    if count >= max_requests:
        # 计算剩余等待时间
        oldest = await db.rate_limits.find_one({
            "limit_type": limit_type,
            "identifier": identifier,
            "created_at": {"$gt": window_start},
        }, sort=[("created_at", 1)])

        if oldest:
            wait_seconds = window_seconds - int((datetime.now() - oldest["created_at"]).total_seconds())
            return False, f"请求过于频繁，请{wait_seconds}秒后再试"

        return False, "请求过于频繁，请稍后再试"

    return True, None


async def record_rate_limit(
    db,
    limit_type: str,
    identifier: str,
    ttl_seconds: int = 300,
) -> None:
    """
    记录频率限制

    Args:
        db: 数据库连接
        limit_type: 限制类型
        identifier: 标识符
        ttl_seconds: 记录保留时间（秒），用于自动清理，默认5分钟
    """
    rate_limit = RateLimit(
        limit_type=limit_type,
        identifier=identifier,
        expires_at=datetime.now() + timedelta(seconds=ttl_seconds),
    )

    await db.rate_limits.insert_one(rate_limit.model_dump())


async def cleanup_expired_rate_limits(db) -> int:
    """
    清理过期的频率限制记录

    Args:
        db: 数据库连接

    Returns:
        int: 清理的记录数
    """
    result = await db.rate_limits.delete_many({
        "expires_at": {"$lt": datetime.now()},
    })
    return result.deleted_count