from datetime import datetime
from typing import Optional, Tuple


def get_member_role(group: dict, user_id: str) -> str:
    """Return the user's role in this group: owner/admin/member."""
    if user_id == group.get("owner_id"):
        return "owner"
    if user_id in group.get("admin_ids", []):
        return "admin"
    return "member"


def can_mute_member(group: dict, operator_id: str, target_id: str) -> bool:
    """Owner can mute admins/members; admin can mute normal members only."""
    operator_role = get_member_role(group, operator_id)
    target_role = get_member_role(group, target_id)

    if target_role == "owner":
        return False
    if operator_role == "owner":
        return True
    if operator_role == "admin" and target_role == "member":
        return True
    return False


def get_active_member_mute(group: dict, user_id: str, now: Optional[datetime] = None) -> Optional[dict]:
    """Find this user's active single-member mute record, if any."""
    now = now or datetime.now()
    for mute in group.get("muted_members", []):
        muted_until = mute.get("muted_until")
        if mute.get("user_id") == user_id and muted_until and muted_until > now:
            return mute
    return None


def is_all_mute_active(group: dict, now: Optional[datetime] = None) -> bool:
    """Check whether group-wide mute is still active."""
    now = now or datetime.now()
    muted_until = group.get("all_muted_until")
    return bool(muted_until and muted_until > now)


def can_send_group_message(group: dict, user_id: str, now: Optional[datetime] = None) -> Tuple[bool, str]:
    """Return whether a user can send a group message and the reason if blocked."""
    now = now or datetime.now()

    member_mute = get_active_member_mute(group, user_id, now)
    if member_mute:
        return False, "你已被禁言，暂时不能发送消息"

    # 全员禁言只限制普通成员，群主和管理员仍然可以发言。
    if is_all_mute_active(group, now) and get_member_role(group, user_id) == "member":
        return False, "当前群聊已开启全员禁言"

    return True, ""
