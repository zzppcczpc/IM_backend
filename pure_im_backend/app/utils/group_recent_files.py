import json
import os
from datetime import datetime
from typing import Any

from .log import logger


RECENT_FILES_LIMIT = 10


def _message_content_dict(message: Any) -> dict:
    content = (
        message.get("content")
        if isinstance(message, dict)
        else getattr(message, "content", None)
    )
    if isinstance(content, dict):
        return content
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def get_message_file_id(message: Any) -> str | None:
    """从文件消息的结构化 content 中取出文件 ID。"""
    content = _message_content_dict(message)
    file_id = content.get("file_id")
    return file_id if isinstance(file_id, str) and file_id.strip() else None


def _file_extension(file_record: dict) -> str:
    filename = file_record.get("file_name") or ""
    extension = os.path.splitext(filename)[1].lower()
    if extension:
        return extension
    raw_type = str(file_record.get("file_type") or "").lower()
    return {
        "text/plain": ".txt",
        "text/markdown": ".md",
        "text/csv": ".csv",
        "application/pdf": ".pdf",
    }.get(raw_type, "")


def _recent_file_record(
    file_record: dict,
    message: Any,
    uploaded_by_username: str = "",
) -> dict:
    message_id = (
        message.get("id")
        if isinstance(message, dict)
        else getattr(message, "id", "")
    )
    uploaded_by = (
        message.get("sender_id")
        if isinstance(message, dict)
        else getattr(message, "sender_id", "")
    )
    uploaded_at = (
        message.get("created_at")
        if isinstance(message, dict)
        else getattr(message, "created_at", None)
    )
    filename = (
        file_record.get("file_name")
        or _message_content_dict(message).get("filename")
        or "未命名文件"
    )
    extension = _file_extension(file_record)

    return {
        "file_id": file_record.get("id", ""),
        "message_id": message_id or "",
        "filename": filename,
        "file_type": extension.lstrip(".") or file_record.get("file_type", ""),
        "storage_path": file_record.get("local_file_path", ""),
        "uploaded_by": uploaded_by or file_record.get("owner_id", ""),
        "uploaded_by_username": uploaded_by_username,
        "uploaded_at": uploaded_at or file_record.get("created_at") or datetime.now(),
        "parse_status": file_record.get("parse_status", "pending"),
        "chunk_count": file_record.get("chunk_count", 0),
        "extraction_type": file_record.get("extraction_type"),
        "extraction_status": file_record.get(
            "extraction_status",
            "not_required",
        ),
        "extraction_error": file_record.get("extraction_error"),
    }


async def record_recent_file(manage_db, message: Any) -> list[dict] | None:
    """更新群聊最近文件列表；该列表只负责展示，不负责 AI 检索。"""
    group_id = (
        message.get("group_id")
        if isinstance(message, dict)
        else getattr(message, "group_id", "")
    )
    file_id = get_message_file_id(message)
    if not group_id or not file_id:
        return None
    message_type = (
        message.get("type")
        if isinstance(message, dict)
        else getattr(message, "type", "")
    )
    # 录音消息属于聊天内容，不作为群文件，也不进入群文件 RAG。
    if message_type == "audio" and "filename" not in _message_content_dict(message):
        return None

    file_record = await manage_db.files.find_one({
        "id": file_id,
        "is_deleted": False,
    })
    if not file_record:
        logger.warning(f"群文件记录不存在，无法加入最近文件列表: {file_id}")
        return None

    uploaded_by = (
        message.get("sender_id")
        if isinstance(message, dict)
        else getattr(message, "sender_id", "")
    )
    user = await manage_db.users.find_one({"id": uploaded_by}) if uploaded_by else None
    record = _recent_file_record(
        file_record,
        message,
        uploaded_by_username=(user or {}).get("username", ""),
    )

    await manage_db.groups.update_one(
        {"id": group_id},
        {"$pull": {"recent_files": {"file_id": file_id}}},
    )
    await manage_db.groups.update_one(
        {"id": group_id},
        {
            "$push": {
                "recent_files": {
                    "$each": [record],
                    "$slice": -RECENT_FILES_LIMIT,
                },
            },
        },
    )
    group = await manage_db.groups.find_one({"id": group_id}, {"recent_files": 1})
    return (group or {}).get("recent_files", [])


async def update_recent_file_status(
    manage_db,
    group_id: str,
    file_id: str,
    *,
    status: str,
    chunk_count: int | None = None,
    extraction_type: str | None = None,
    extraction_error: str | None = None,
):
    update = {"recent_files.$.parse_status": status}
    if chunk_count is not None:
        update["recent_files.$.chunk_count"] = chunk_count
    if extraction_type is not None:
        update["recent_files.$.extraction_type"] = extraction_type
    if extraction_error is not None:
        update["recent_files.$.extraction_error"] = extraction_error
    await manage_db.groups.update_one(
        {"id": group_id, "recent_files.file_id": file_id},
        {"$set": update},
    )
