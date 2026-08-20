"""
消息类型映射工具

将 MIME 类型映射为统一的消息类型（text、image、video、audio、file）
"""


def get_message_type(mime_type: str) -> str:
    """
    将 MIME 类型映射为统一消息类型

    Args:
        mime_type: MIME 类型字符串，如 "image/png", "audio/webm", "video/mp4", "application/pdf"

    Returns:
        统一消息类型: "text" | "image" | "video" | "audio" | "file"
    """
    if not mime_type:
        return "text"

    mime_type = mime_type.lower()

    if mime_type.startswith("image/"):
        return "image"
    elif mime_type.startswith("video/"):
        return "video"
    elif mime_type.startswith("audio/"):
        return "audio"
    else:
        # 其他所有类型（application/*, text/* 等）归为 file
        return "file"