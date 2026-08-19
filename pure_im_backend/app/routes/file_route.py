import os
import uuid
from typing import Annotated, Optional
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse

from ..config import settings
from ..database import get_chat_database, get_database
from ..models.user import User
from ..models.file import File as FileModel
from ..schemas.response import error, success
from ..utils.auth import get_current_user
from ..utils.log import logger
from ..utils.file_handler import save_file, validate_file
from ..utils.group_mute import can_send_group_message
from ..utils.file_permission import check_file_download_permission
from ..utils.message_type import get_message_type

router = APIRouter()


@router.post("/group/upload/media", description="群上传多媒体")
async def group_upload_media(
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(...)],
    group_id: Annotated[str, Form(...)],
    duration: Annotated[Optional[float], Form(...)] = None,
    current_user: User = Depends(get_current_user),
    manage_db=Depends(get_database),
    chat_db=Depends(get_chat_database),
):
    try:
        # 1. 先验证文件后缀和大小，语音文件本质上也是一个上传文件。
        await validate_file(file, settings.ALLOWED_EXTENSIONS, settings.MAX_FILE_SIZE)

        # 2. 给这次上传的文件生成一个唯一 ID。
        # 语音消息不会把音频二进制直接存进消息表，而是在消息 content 里存这个文件 ID。
        doc_uuid = str(uuid.uuid4())
        group_collection = getattr(chat_db, group_id)

        # 3. 校验群是否存在、当前用户是否在群里。
        group = await manage_db.groups.find_one({"id": group_id, "is_dissolved": False})
        if not group:
            return error(code=404, message="群组不存在")

        if current_user.id not in group["member_ids"]:
            return error(code=403, message="无权限访问该群聊")

        # 4. 上传语音也等于发消息，所以这里同样要检查禁言，避免被禁言用户绕过输入框发语音。
        can_send, reason = can_send_group_message(group, current_user.id)
        if not can_send:
            return error(code=403, message=reason)

        # 5. 清理文件名，避免文件名里有奇怪字符影响本地保存路径。
        safe_filename = "".join(
            c for c in file.filename if c.isalnum() or c in "._- "
        )
        file.filename = safe_filename
        # 6. 读取真实音频二进制内容，后面 save_file 会把它写入 uploads 目录。
        content = await file.read()

        file_header = {
            "filename": file.filename,
            "content_type": file.content_type,
            "size": file.size,
        }

        # 7. 先创建并广播一条聊天消息。
        # 使用统一消息类型：image/audio/file
        from ..routes.chat import broadcast_and_save_msg
        message_type = get_message_type(file_header["content_type"])

        # 构造结构化 content
        if message_type == "audio":
            message_content = {
                "file_id": doc_uuid,
                "duration": duration,
            }
        else:
            message_content = {
                "file_id": doc_uuid,
                "filename": file.filename,
                "size": file.size,
                "mime_type": file.content_type,
            }

        await broadcast_and_save_msg(
            group_collection=group_collection,
            manage_db=manage_db,
            content=message_content,
            type=message_type,
            group_id=group_id,
            sender_id=current_user.id,
            duration=duration,
        )

        # 8. 把真实音频文件保存到本地 uploads，并在 files 表里记录文件 ID、路径、类型等信息。
        await save_file(
            content,
            current_user,
            doc_uuid,
            manage_db,
            file_header,
            None,
            group_id,
        )

        return success(message="上传成功")
    except ValueError as e:
        return error(code=400, message=str(e))
    except Exception as e:
        logger.error(f"上传多媒体出错: {e}")
        return error(code=500, message="上传出错")


@router.post("/group/upload/file", description="群上传文件")
async def upload_file_to_group(
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(...)],
    group_id: Annotated[str, Form(...)],
    current_user: User = Depends(get_current_user),
    manage_db=Depends(get_database),
    chat_db=Depends(get_chat_database),
):
    try:
        await validate_file(file, settings.ALLOWED_EXTENSIONS, settings.MAX_FILE_SIZE)

        doc_uuid = str(uuid.uuid4())
        group_collection = getattr(chat_db, group_id)

        group = await manage_db.groups.find_one({"id": group_id, "is_dissolved": False})
        if not group:
            return error(code=404, message="群组不存在")

        if current_user.id not in group["member_ids"]:
            return error(code=403, message="无权限访问该群聊")

        # 上传文件也会生成一条群消息，所以这里同样要检查禁言。
        can_send, reason = can_send_group_message(group, current_user.id)
        if not can_send:
            return error(code=403, message=reason)

        safe_filename = "".join(
            c for c in file.filename if c.isalnum() or c in "._- "
        )
        file.filename = safe_filename
        content = await file.read()

        file_header = {
            "filename": file.filename,
            "content_type": file.content_type,
            "size": file.size,
        }

        await save_file(content, current_user, doc_uuid, manage_db, file_header, None, group_id)

        # 广播消息
        from ..routes.chat import broadcast_and_save_msg
        message_type = get_message_type(file.content_type)

        await broadcast_and_save_msg(
            group_collection=group_collection,
            manage_db=manage_db,
            content={
                "file_id": doc_uuid,
                "filename": file.filename,
                "size": file.size,
                "mime_type": file.content_type,
            },
            type=message_type,
            group_id=group_id,
            sender_id=current_user.id,
        )

        return success(message="上传成功")
    except ValueError as e:
        return error(code=400, message=str(e))
    except Exception as e:
        logger.error(f"上传文件出错: {e}")
        return error(code=500, message="上传出错")


@router.post("/head/upload", description="上传头像")
async def upload_head(
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(...)],
    current_user: User = Depends(get_current_user),
    db=Depends(get_database),
):
    try:
        doc_uuid = str(uuid.uuid4())

        await validate_file(file, [".png", ".jpg", ".jpeg"], settings.MAX_FILE_SIZE)

        safe_filename = "".join(
            c for c in file.filename if c.isalnum() or c in "._- "
        )
        file.filename = safe_filename
        content = await file.read()

        file_header = {
            "filename": file.filename,
            "content_type": file.content_type,
            "size": file.size,
        }

        background_tasks.add_task(
            save_file,
            content,
            current_user,
            doc_uuid,
            db,
            file_header,
            None,
            None,
        )

        await db.users.update_one(
            {"id": current_user.id},
            {"$set": {"avatar": doc_uuid}},
        )

        return success(
            data={
                "file_id": doc_uuid,
                "avatar": doc_uuid,
                "file_path": f"/api/files/head/{current_user.id}",
            },
            message="上传成功",
        )
    except ValueError as e:
        return error(code=400, message=str(e))
    except Exception as e:
        logger.error(f"上传头像出错: {e}")
        return error(code=500, message="上传出错")


@router.get("/download/{file_id}/{token}", description="下载文件")
async def download_file_route(
    file_id: str,
    token: str,
    db=Depends(get_database),
):
    try:
        from ..utils.auth import get_current_user
        current_user = await get_current_user(token=token)

        file_record = await db.files.find_one({"id": file_id, "is_deleted": False})
        if not file_record:
            return error(code=404, message="文件不存在")

        # 使用新的权限校验函数
        permission = await check_file_download_permission(file_record, current_user, db)
        if not permission.can_access:
            return error(code=permission.error_code, message=permission.error_message)

        if not os.path.exists(file_record["local_file_path"]):
            return error(code=404, message="文件不存在")

        return FileResponse(
            path=file_record["local_file_path"],
            filename=file_record["file_name"],
            media_type=file_record["file_type"],
        )
    except Exception as e:
        logger.error(f"下载文件出错: {e}")
        return error(code=500, message="下载失败")


@router.get("/head/{user_id}", description="获取头像")
async def download_head(user_id: str, db=Depends(get_database)):
    try:
        user = await db.users.find_one({"id": user_id, "is_active": True})
        if not user or not user.get("avatar"):
            return FileResponse(path="static/default_avatar.png")

        head_file = await db.files.find_one({"id": user["avatar"], "is_deleted": False})
        if not head_file:
            return FileResponse(path="static/default_avatar.png")

        if not os.path.exists(head_file["local_file_path"]):
            return FileResponse(path="static/default_avatar.png")

        return FileResponse(path=head_file["local_file_path"])
    except Exception as e:
        logger.error(f"获取头像出错: {e}")
        return FileResponse(path="static/default_avatar.png")
