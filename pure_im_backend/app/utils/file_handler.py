import os
import uuid
from fastapi import UploadFile

from ..config import settings
from ..models.file import File as FileModel
from ..utils.log import logger


async def validate_file(file: UploadFile, allowed_extensions: list, max_size: int):
    """验证文件类型和大小"""
    # 检查文件扩展名
    filename = file.filename.lower()
    ext = os.path.splitext(filename)[1]
    if ext not in allowed_extensions:
        raise ValueError(f"不支持的文件类型: {ext}")

    # 检查文件大小
    if file.size and file.size > max_size:
        raise ValueError(f"文件大小超出限制: {max_size / 1024 / 1024}MB")


async def save_file(
    content: bytes,
    user,
    doc_uuid: str,
    db,
    file_header: dict,
    database_id: str = None,
    group_id: str = None,
    url: str = None,
):
    """保存文件到本地和数据库"""
    # 创建存储目录
    upload_dir = "uploads"
    if not os.path.exists(upload_dir):
        os.makedirs(upload_dir)

    # 保存文件
    file_path = os.path.join(upload_dir, f"{doc_uuid}_{file_header['filename']}")
    with open(file_path, "wb") as f:
        f.write(content)

    # 创建文件记录
    file_record = FileModel(
        id=doc_uuid,
        file_name=file_header["filename"],
        file_type=file_header["content_type"],
        file_size=file_header["size"],
        local_file_path=file_path,
        owner_id=user.id,
        group_id=group_id,
    )

    await db.files.insert_one(file_record.model_dump())

    logger.info(f"文件 {doc_uuid} 已保存")

    return file_path