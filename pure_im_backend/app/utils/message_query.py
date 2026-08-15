"""
消息查询公共逻辑

统一 HTTP 和 WebSocket 两个入口的消息过滤条件，确保一致性。
"""
from datetime import datetime
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase


async def build_message_query(
    user_id: str,
    group_id: str,
    manage_db: AsyncIOMotorDatabase,
    before_time: Optional[datetime] = None,
) -> dict:
    """
    构建消息查询条件，统一过滤逻辑。

    Args:
        user_id: 当前用户ID
        group_id: 群组ID
        manage_db: 管理数据库连接（用于查询清空记录）
        before_time: 分页锚点时间，查询该时间之前的消息（可选）

    Returns:
        query: MongoDB 查询条件字典
    """
    query = {
        "is_revoke": False,
        "deleted_by_users": {"$ne": user_id},
    }

    # 查询用户对该群组的清空记录
    clear_record = await manage_db.user_cleared_groups.find_one({
        "user_id": user_id,
        "group_id": group_id,
    })

    # 构建时间过滤条件
    time_filter = {}

    # 清空时间：只查清空时间之后的消息
    if clear_record:
        time_filter["$gt"] = clear_record["cleared_at"]

    # 分页锚点：查该时间之前的消息
    if before_time:
        time_filter["$lt"] = before_time

    if time_filter:
        query["created_at"] = time_filter

    return query


async def count_unread_messages(
    user_id: str,
    group_id: str,
    chat_collection,
    manage_db: AsyncIOMotorDatabase,
) -> int:
    """
    统计群组未读消息数，统一过滤逻辑。

    Args:
        user_id: 当前用户ID
        group_id: 群组ID
        chat_collection: 聊天集合
        manage_db: 管理数据库连接

    Returns:
        未读消息数量
    """
    # 使用公共函数构建查询条件
    query = await build_message_query(
        user_id=user_id,
        group_id=group_id,
        manage_db=manage_db,
    )
    # 未读条件：不在已读列表中
    query["read_list"] = {"$ne": user_id}

    return await chat_collection.count_documents(query)