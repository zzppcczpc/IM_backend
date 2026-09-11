from datetime import datetime

from fastapi import APIRouter, Depends

from ..database import get_database
from ..models.knowledge_base import KnowledgeBase
from ..models.user import User
from ..schemas.knowledge_base import (
    KnowledgeBaseCreate,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdate,
)
from ..schemas.response import error, success
from ..utils.auth import get_current_user
from ..utils.log import logger

router = APIRouter()


def _to_response(document: dict) -> dict:
    document.pop("_id", None)
    return KnowledgeBaseResponse(**document).model_dump()


def _can_access(document: dict, user_id: str) -> bool:
    return user_id == document.get("owner_id") or user_id in document.get("member_ids", [])


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

    # 当前阶段还没有知识库文件和向量实体；后续需求接入后在这里先清理关联数据。
    await db.knowledge_base_files.delete_many({"knowledge_base_id": knowledge_base_id})
    await db.knowledge_base_chunks.delete_many({"knowledge_base_id": knowledge_base_id})
    await db.knowledge_bases.delete_one({"id": knowledge_base_id})
    return success(
        message="知识库删除成功",
        data={"knowledge_base_id": knowledge_base_id},
    )

