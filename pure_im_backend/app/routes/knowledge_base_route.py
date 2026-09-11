import os
import re
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile

from ..database import get_database
from ..models.knowledge_base import KnowledgeBase
from ..models.knowledge_base_file import KnowledgeBaseFile
from ..models.user import User
from ..schemas.knowledge_base import (
    KnowledgeBaseCreate,
    KnowledgeBaseFileResponse,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdate,
)
from ..config import settings
from ..schemas.response import error, success
from ..utils.auth import get_current_user
from ..utils.knowledge_base_parser import parse_knowledge_base_file
from ..utils.log import logger

router = APIRouter()


def _to_response(document: dict) -> dict:
    document.pop("_id", None)
    return KnowledgeBaseResponse(**document).model_dump()


def _can_access(document: dict, user_id: str) -> bool:
    return user_id == document.get("owner_id") or user_id in document.get("member_ids", [])

#只保留中文/英文/数字/点/下划线/空格/横杠，其他全变 _，去掉路径，空了就叫"未命名文件"
def _safe_filename(filename: str) -> str:
    filename = os.path.basename(filename or "未命名文件")
    cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._ -]", "_", filename).strip()
    return cleaned or "未命名文件"


def _knowledge_base_extensions() -> set[str]:
    return {".pdf", ".docx", ".pptx", ".xlsx", ".csv", ".txt", ".md"}


def _file_response(document: dict) -> dict:
    document.pop("_id", None)
    return KnowledgeBaseFileResponse(**document).model_dump()


async def _process_knowledge_base_file(file_id: str, db):
    """后台解析文件，并把结果和状态写回 MongoDB。"""
    file_record = await db.knowledge_base_files.find_one({"id": file_id})
    if not file_record:
        return

    now = datetime.now()
    await db.knowledge_base_files.update_one(
        {"id": file_id},
        {
            "$set": {
                "status": "parsing",
                "error_message": None,
                "updated_at": now,
            },
        },
    )
    try:
        text, metadata = parse_knowledge_base_file(
            file_record["local_file_path"],
            file_record["file_extension"],
        )
        await db.knowledge_base_files.update_one(
            {"id": file_id},
            {
                "$set": {
                    "status": "success",
                    "parsed_text": text,
                    "parse_metadata": metadata,
                    "error_message": None,
                    "updated_at": datetime.now(),
                },
            },
        )
    except Exception as exc:
        logger.error(f"知识库文件解析失败: {file_id}, {exc}", exc_info=True)
        await db.knowledge_base_files.update_one(
            {"id": file_id},
            {
                "$set": {
                    "status": "failed",
                    "error_message": str(exc)[:1000],
                    "updated_at": datetime.now(),
                },
            },
        )


@router.post("", description="创建知识库")
async def create_knowledge_base(
    data: KnowledgeBaseCreate,
    current_user: User = Depends(get_current_user),
    db=Depends(get_database),
):
    name = data.name.strip()
    if not name:
        return error(code=400, message="知识库名称不能为空")

    now = datetime.now()
    knowledge_base = KnowledgeBase(
        name=name,
        description=data.description.strip(),
        owner_id=current_user.id,
        member_ids=[current_user.id],
        created_at=now,
        updated_at=now,
    )
    await db.knowledge_bases.insert_one(knowledge_base.model_dump())
    return success(message="知识库创建成功", data=knowledge_base.model_dump())


@router.get("", description="查询当前用户有权限访问的知识库")
async def list_knowledge_bases(
    current_user: User = Depends(get_current_user),
    db=Depends(get_database),
):
    documents = await db.knowledge_bases.find({
        "$or": [
            {"owner_id": current_user.id},
            {"member_ids": current_user.id},
        ],
    }).sort("updated_at", -1).to_list(None)
    return success(
        message="知识库列表读取成功",
        data=[_to_response(document) for document in documents],
    )


@router.get("/{knowledge_base_id}", description="查看知识库详情")
async def get_knowledge_base(
    knowledge_base_id: str,
    current_user: User = Depends(get_current_user),
    db=Depends(get_database),
):
    document = await db.knowledge_bases.find_one({"id": knowledge_base_id})
    if not document:
        return error(code=404, message="知识库不存在")
    if not _can_access(document, current_user.id):
        return error(code=403, message="无权限访问该知识库")
    return success(message="知识库详情读取成功", data=_to_response(document))


@router.put("/{knowledge_base_id}", description="修改知识库")
async def update_knowledge_base(
    knowledge_base_id: str,
    data: KnowledgeBaseUpdate,
    current_user: User = Depends(get_current_user),
    db=Depends(get_database),
):
    document = await db.knowledge_bases.find_one({"id": knowledge_base_id})
    if not document:
        return error(code=404, message="知识库不存在")
    if document.get("owner_id") != current_user.id:
        return error(code=403, message="只有知识库创建者可以修改")

    update_data = {}
    if data.name is not None:
        name = data.name.strip()
        if not name:
            return error(code=400, message="知识库名称不能为空")
        update_data["name"] = name
    if data.description is not None:
        update_data["description"] = data.description.strip()
    if not update_data:
        return error(code=400, message="没有需要修改的内容")

    update_data["updated_at"] = datetime.now()
    await db.knowledge_bases.update_one(
        {"id": knowledge_base_id},
        {"$set": update_data},
    )
    updated = await db.knowledge_bases.find_one({"id": knowledge_base_id})
    return success(message="知识库修改成功", data=_to_response(updated))


@router.delete("/{knowledge_base_id}", description="删除知识库")
async def delete_knowledge_base(
    knowledge_base_id: str,
    current_user: User = Depends(get_current_user),
    db=Depends(get_database),
):
    document = await db.knowledge_bases.find_one({"id": knowledge_base_id})
    if not document:
        return error(code=404, message="知识库不存在")
    if document.get("owner_id") != current_user.id:
        return error(code=403, message="只有知识库创建者可以删除")

    # 清理当前阶段已经落盘的文件；后续向量集合也在这里继续清理。
    files = await db.knowledge_base_files.find(
        {"knowledge_base_id": knowledge_base_id}
    ).to_list(None)
    for file_record in files:
        path = file_record.get("local_file_path")
        if path and os.path.isfile(path):
            try:
                os.remove(path)
            except OSError as exc:
                logger.warning(f"知识库文件清理失败: {path}, {exc}")
    await db.knowledge_base_files.delete_many({"knowledge_base_id": knowledge_base_id})
    await db.knowledge_base_chunks.delete_many({"knowledge_base_id": knowledge_base_id})
    await db.knowledge_bases.delete_one({"id": knowledge_base_id})
    return success(
        message="知识库删除成功",
        data={"knowledge_base_id": knowledge_base_id},
    )


@router.post("/{knowledge_base_id}/files", description="上传知识库文件")
async def upload_knowledge_base_file(
    knowledge_base_id: str,
    file: Annotated[UploadFile, File(...)],
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db=Depends(get_database),
):
    document = await db.knowledge_bases.find_one({"id": knowledge_base_id})
    if not document:
        return error(code=404, message="知识库不存在")
    if not _can_access(document, current_user.id):
        return error(code=403, message="无权限向该知识库上传文件")

    filename = _safe_filename(file.filename or "")
    extension = os.path.splitext(filename)[1].lower()
    if extension not in _knowledge_base_extensions():
        return error(
            code=400,
            message="不支持的文件类型，仅支持 pdf、docx、pptx、xlsx、csv、txt、md",
        )

    content = await file.read()
    if len(content) > settings.MAX_FILE_SIZE:
        return error(
            code=400,
            message=f"文件不能超过 {settings.MAX_FILE_SIZE // 1024 // 1024}MB",
        )
    if not content:
        return error(code=400, message="不能上传空文件")

    file_id = str(uuid.uuid4())
    upload_dir = os.path.join("uploads", "knowledge_bases", knowledge_base_id)
    os.makedirs(upload_dir, exist_ok=True)
    local_file_path = os.path.join(upload_dir, f"{file_id}_{filename}")

    try:
        with open(local_file_path, "wb") as output:
            output.write(content)

        now = datetime.now()
        file_record = KnowledgeBaseFile(
            id=file_id,
            knowledge_base_id=knowledge_base_id,
            owner_id=current_user.id,
            file_name=filename,
            file_type=file.content_type or "application/octet-stream",
            file_extension=extension,
            file_size=len(content),
            local_file_path=local_file_path,
            status="uploaded",
            created_at=now,
            updated_at=now,
        )
        await db.knowledge_base_files.insert_one(file_record.model_dump())
        await db.knowledge_bases.update_one(
            {"id": knowledge_base_id},
            {
                "$inc": {"file_count": 1},
                "$set": {"updated_at": now},
            },
        )
        background_tasks.add_task(_process_knowledge_base_file, file_id, db)
        return success(
            message="文件上传成功",
            data=_file_response(file_record.model_dump()),
        )
    except Exception as exc:
        if os.path.isfile(local_file_path):
            os.remove(local_file_path)
        logger.error(f"知识库文件上传失败: {exc}", exc_info=True)
        return error(code=500, message="知识库文件保存失败")


@router.post(
    "/{knowledge_base_id}/files/{file_id}/parse",
    description="重新解析知识库文件",
)
async def parse_knowledge_base_file_route(
    knowledge_base_id: str,
    file_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db=Depends(get_database),
):
    document = await db.knowledge_bases.find_one({"id": knowledge_base_id})
    if not document:
        return error(code=404, message="知识库不存在")
    if not _can_access(document, current_user.id):
        return error(code=403, message="无权限访问该知识库")

    file_record = await db.knowledge_base_files.find_one({
        "id": file_id,
        "knowledge_base_id": knowledge_base_id,
    })
    if not file_record:
        return error(code=404, message="知识库文件不存在")

    background_tasks.add_task(_process_knowledge_base_file, file_id, db)
    return success(
        message="已提交文件解析任务",
        data={"file_id": file_id, "status": "parsing"},
    )


@router.get("/{knowledge_base_id}/files", description="查询知识库文件")
async def list_knowledge_base_files(
    knowledge_base_id: str,
    current_user: User = Depends(get_current_user),
    db=Depends(get_database),
):
    document = await db.knowledge_bases.find_one({"id": knowledge_base_id})
    if not document:
        return error(code=404, message="知识库不存在")
    if not _can_access(document, current_user.id):
        return error(code=403, message="无权限访问该知识库")

    files = await db.knowledge_base_files.find(
        {"knowledge_base_id": knowledge_base_id}
    ).sort("created_at", -1).to_list(None)
    return success(
        message="知识库文件列表读取成功",
        data=[_file_response(item) for item in files],
    )


@router.get("/{knowledge_base_id}/files/{file_id}", description="查询知识库文件状态")
async def get_knowledge_base_file(
    knowledge_base_id: str,
    file_id: str,
    current_user: User = Depends(get_current_user),
    db=Depends(get_database),
):
    document = await db.knowledge_bases.find_one({"id": knowledge_base_id})
    if not document:
        return error(code=404, message="知识库不存在")
    if not _can_access(document, current_user.id):
        return error(code=403, message="无权限访问该知识库")

    file_record = await db.knowledge_base_files.find_one({
        "id": file_id,
        "knowledge_base_id": knowledge_base_id,
    })
    if not file_record:
        return error(code=404, message="知识库文件不存在")
    return success(
        message="文件状态读取成功",
        data=_file_response(file_record),
    )

