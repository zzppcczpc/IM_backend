"""
文件下载权限校验模块

根据文件类型（群文件、私聊文件、个人文件）进行细粒度权限校验：
- 群文件：仅群成员可下载
- 私聊文件：仅私聊双方可下载
- 用户头像：公开资源，任意用户可访问
- 其他个人文件：仅文件拥有者可下载
"""

from dataclasses import dataclass
from typing import Optional

from ..models.user import User


@dataclass
class FilePermissionResult:
    """权限校验结果"""
    can_access: bool
    error_code: Optional[int] = None
    error_message: Optional[str] = None

    @classmethod
    def allow(cls) -> 'FilePermissionResult':
        """允许访问"""
        return cls(can_access=True)

    @classmethod
    def deny(cls, code: int, message: str) -> 'FilePermissionResult':
        """拒绝访问"""
        return cls(can_access=False, error_code=code, error_message=message)


async def check_file_download_permission(
    file_record: dict,
    current_user: User,
    db
) -> FilePermissionResult:
    """
    检查文件下载权限

    Args:
        file_record: 文件记录字典
        current_user: 当前用户
        db: 数据库连接

    Returns:
        FilePermissionResult: 权限校验结果
    """
    # 1. 文件拥有者直接放行
    if file_record.get("owner_id") == current_user.id:
        return FilePermissionResult.allow()

    # 2. 判断文件类型
    group_id = file_record.get("group_id")

    if group_id is None:
        # 个人文件：检查是否为头像等公开资源
        return await _check_personal_file_permission(file_record, current_user, db)

    # 3. 群组文件：检查群成员身份
    return await _check_group_file_permission(file_record, group_id, current_user, db)


async def _check_personal_file_permission(
    file_record: dict,
    current_user: User,
    db
) -> FilePermissionResult:
    """
    检查个人文件（无 group_id）的访问权限

    个人文件分为两类：
    1. 用户头像：公开资源，任意用户可访问
    2. 其他个人文件：仅拥有者可访问
    """
    # 查询该文件是否被用作用户头像
    user_with_avatar = await db.users.find_one({
        "avatar": file_record["id"],
        "is_active": True,
    })

    if user_with_avatar:
        # 头像为公开资源，任何人可访问
        return FilePermissionResult.allow()

    # 其他个人文件：仅拥有者可访问
    return FilePermissionResult.deny(403, "无权限下载该文件")


async def _check_group_file_permission(
    file_record: dict,
    group_id: str,
    current_user: User,
    db
) -> FilePermissionResult:
    """
    检查群组文件的访问权限（群聊和私聊统一处理）

    群聊文件：群成员可下载
    私聊文件：私聊双方可下载
    """
    # 查询群组
    group = await db.groups.find_one({"id": group_id})

    if not group:
        return FilePermissionResult.deny(404, "群组不存在")

    if group.get("is_dissolved", False):
        # 群已解散：私聊返回"聊天已删除"，群聊返回"群组已解散"
        if group.get("type") == "private":
            return FilePermissionResult.deny(404, "聊天已删除")
        return FilePermissionResult.deny(404, "群组已解散")

    # 检查用户是否为群成员
    member_ids = group.get("member_ids", [])
    if current_user.id not in member_ids:
        return FilePermissionResult.deny(403, "无权限下载该文件")

    return FilePermissionResult.allow()