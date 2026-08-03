import json
from datetime import datetime
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..database import get_chat_database, get_database
from ..models.group import Group, GroupForward
from ..models.user import User
from ..schemas.group import (
    ForwardMessage,
    GroupCreate,
    GroupCreateResponse,
    GroupDetailResponse,
    GroupInquiry,
    GroupMemberManage,
    GroupMessageSearch,
    GroupReadUpdate,
    GroupForwardMessage,
    GroupResponse,
    MessageSearch,
)
from ..schemas.message import MessageData, MessageResponse
from ..schemas.response import PaginationModel, error, success
from ..schemas.user import UserResponse
from ..utils.auth import get_current_user
from ..utils.log import logger
from ..utils.websocket_manager import connection_dic

router = APIRouter()
templates = Jinja2Templates(directory="templates")


def to_client_data(value):
    if isinstance(value, list):
        return [to_client_data(item) for item in value]
    if isinstance(value, dict):
        return {
            key: to_client_data(item)
            for key, item in value.items()
            if key != "_id"
        }
    if isinstance(value, datetime):
        return value.isoformat()
    if value.__class__.__name__ == "ObjectId":
        return str(value)
    return value


@router.post("/create", description="创建群聊")
async def create_group(
    group_data: GroupCreate,
    current_user: User = Depends(get_current_user),
    db=Depends(get_database),
):
    try:
        if current_user.id not in group_data.member_ids:
            group_data.member_ids.append(current_user.id)

        # 私聊检查是否已存在
        if len(group_data.member_ids) == 2 and group_data.type == "private":
            exist_private_group = await db.groups.find_one({
                "$and": [
                    {"member_ids": group_data.member_ids[0]},
                    {"member_ids": group_data.member_ids[1]},
                ],
                "type": "private",
                "is_dissolved": False,
            })
            if exist_private_group:
                exist_private_group = to_client_data(exist_private_group)
                member_ids = list(exist_private_group["member_ids"])
                member_ids.remove(current_user.id)
                user = await db.users.find_one(
                    {"id": member_ids[0]}
                )
                exist_private_group["name"] = user["username"]
                exist_private_group["member_ids"] = member_ids
                return success(
                    code=308,
                    data=GroupCreateResponse(**exist_private_group).model_dump(),
                )

        # 创建新群组
        new_group = Group(
            name="" if group_data.type == "private" else group_data.name,
            owner_id=current_user.id,
            member_ids=group_data.member_ids,
            type=group_data.type,
        )
        new_group_data = new_group.model_dump()

        # 设置默认最新消息
        new_group_data["last_message"] = {
            "created_at": new_group.created_at,
            "id": "",
            "type": "",
            "content": "",
            "sender_id": "",
            "sender_username": "",
            "group_id": "",
        }

        await db.groups.insert_one(new_group_data)

        # 私聊设置对方名字为群名
        if group_data.type == "private":
            new_group_data = to_client_data(new_group_data)
            new_group_data["member_ids"].remove(current_user.id)
            user = await db.users.find_one(
                {"id": new_group_data["member_ids"][0]}
            )
            new_group_data["name"] = user["username"]

        return success(
            data=GroupCreateResponse(**to_client_data(new_group_data)).model_dump(),
            message="创建成功"
        )
    except Exception as e:
        logger.error(f"创建群组出错: {e}")
        return error(code=500, message="创建群组出错")


@router.post("/add_user_to_group", description="添加用户到群聊")
async def add_member_to_group(
    post_data: GroupMemberManage,
    current_user: User = Depends(get_current_user),
    db=Depends(get_database),
):
    try:
        group = await db.groups.find_one({
            "id": post_data.group_id,
            "is_dissolved": False,
        })

        if not group:
            return error(code=404, message="群组不存在")

        if group["owner_id"] != current_user.id:
            return error(code=403, message="非群主不能添加用户")

        for user_id in post_data.user_ids:
            user = await db.users.find_one({"id": user_id, "is_active": True})
            if user_id in group["member_ids"]:
                return error(code=409, message=f"用户{user['username']}已在群聊中")
            if not user:
                return error(code=404, message=f"用户{user_id}不存在")

        await db.groups.update_one(
            {"id": post_data.group_id},
            {"$push": {"member_ids": {"$each": post_data.user_ids}}},
        )

        return success(message="添加成功")
    except Exception as e:
        logger.error(f"添加用户出错: {e}")
        return error(code=500, message="添加用户出错")


@router.post("/dele_user_from_group", description="将用户移出群聊")
async def del_member_from_group(
    post_data: GroupMemberManage,
    current_user: User = Depends(get_current_user),
    db=Depends(get_database),
):
    try:
        group = await db.groups.find_one({
            "id": post_data.group_id,
            "is_dissolved": False,
        })

        if not group:
            return error(code=404, message="群组不存在")

        if group["owner_id"] != current_user.id:
            return error(code=403, message="非群主不能移出用户")

        if current_user.id in post_data.user_ids:
            return error(code=403, message="不能移出群主")

        await db.groups.update_one(
            {"id": post_data.group_id},
            {"$pull": {"member_ids": {"$in": post_data.user_ids}}},
        )

        return success(message="移除成功")
    except Exception as e:
        logger.error(f"移出用户出错: {e}")
        return error(code=500, message="移出用户出错")


@router.post("/{group_id}/leave", description="退出群聊")
async def leave_group(
    group_id: str,
    current_user: User = Depends(get_current_user),
    db=Depends(get_database),
):
    try:
        group = await db.groups.find_one({
            "id": group_id,
            "is_dissolved": False,
        })

        if not group:
            return error(code=404, message="群组不存在")

        if group["owner_id"] == current_user.id:
            return error(code=403, message="群主不能退出")

        if current_user.id not in group["member_ids"]:
            return error(code=403, message="你不在该群组中")

        await db.groups.update_one(
            {"id": group_id},
            {"$pull": {"member_ids": current_user.id}},
        )

        return success(message="退出成功")
    except Exception as e:
        logger.error(f"退出群组出错: {e}")
        return error(code=500, message="退出群组出错")


@router.delete("/{group_uuid}", description="解散群聊")
async def dissolve_group(
    group_uuid: str,
    current_user: User = Depends(get_current_user),
    db=Depends(get_database),
):
    try:
        group = await db.groups.find_one({
            "id": group_uuid,
            "is_dissolved": False,
        })

        if not group:
            return error(code=404, message="群组不存在")

        if group["owner_id"] != current_user.id:
            return error(code=403, message="无权限解散该群组")

        await db.groups.update_one(
            {"id": group_uuid},
            {"$set": {"is_dissolved": True}},
        )

        if group.get("type") == "private":
            return success(message="已删除聊天")
        return success(message="解散成功")
    except Exception as e:
        logger.error(f"解散群组出错: {e}")
        return error(code=500, message="解散群组出错")


@router.post("/list", description="查询群列表")
async def get_groups(
    inquiry: GroupInquiry,
    current_user: User = Depends(get_current_user),
    manage_db=Depends(get_database),
    chat_db=Depends(get_chat_database),
):
    try:
        total_unread = 0
        query = {
            "member_ids": current_user.id,
            "is_dissolved": False,
        }

        all_groups = await manage_db.groups.find(query).to_list(None)

        for group in all_groups:
            chat_collection = getattr(chat_db, group["id"])
            group_unread = await chat_collection.count_documents({
                "group_id": group["id"],
                "is_revoke": False,
                "read_list": {"$ne": current_user.id},
            })
            total_unread += group_unread

        page_size = inquiry.page_size
        skip = (inquiry.page - 1) * page_size

        total = await manage_db.groups.count_documents(query)

        groups = (
            await manage_db.groups.find(query)
            .sort([("last_message.created_at", -1)])
            .skip(skip)
            .limit(page_size)
            .to_list(None)
        )

        for group in groups:
            chat_collection = getattr(chat_db, group["id"])
            group_unread = await chat_collection.count_documents({
                "group_id": group["id"],
                "is_revoke": False,
                "read_list": {"$ne": current_user.id},
            })
            group["unread_count"] = group_unread

            # 私聊处理
            if group.get("type") == "private":
                group["member_ids"].remove(current_user.id)
                user = await manage_db.users.find_one(
                    {"id": group["member_ids"][0]}
                )
                group["name"] = user["username"]

        response_data = PaginationModel(
            total=total,
            page=inquiry.page,
            page_size=inquiry.page_size,
            items=[
                GroupResponse(**to_client_data(group)).model_dump()
                for group in groups
            ],
        ).dict()
        response_data["total_unread"] = total_unread

        return success(data=response_data)
    except Exception as e:
        logger.error(f"获取群列表出错: {e}")
        return error(code=500, message="获取群列表出错")


@router.get("/all_read/{group_id}", description="一键已读")
async def read_all_message(
    group_id: str,
    current_user: User = Depends(get_current_user),
    db=Depends(get_database),
    chat_db=Depends(get_chat_database),
):
    try:
        group = await db.groups.find_one({
            "id": group_id,
            "is_dissolved": False,
        })

        if not group:
            return error(code=404, message="群组不存在")

        if current_user.id not in group["member_ids"]:
            return error(code=403, message="你不在该群组中")

        chat_collection = getattr(chat_db, group_id)
        await chat_collection.update_many(
            {},
            {"$addToSet": {"read_list": current_user.id}}
        )

        await connection_dic.broadcast(
            [current_user.id],
            json.dumps({"type": "refresh_group_list", "group_id": group_id})
        )

        return success(message="已全部标记已读")
    except Exception as e:
        logger.error(f"一键已读出错: {e}")
        return error(code=500, message="一键已读出错")


@router.post("/read", description="标记已读")
async def read_message(
    update_data: GroupReadUpdate,
    current_user: User = Depends(get_current_user),
    db=Depends(get_database),
    chat_db=Depends(get_chat_database),
):
    try:
        group = await db.groups.find_one({
            "id": update_data.group_id,
            "is_dissolved": False,
        })

        if not group:
            return error(code=404, message="群组不存在")

        if current_user.id not in group["member_ids"]:
            return error(code=403, message="你不在该群组中")

        chat_collection = getattr(chat_db, update_data.group_id)
        result = await chat_collection.update_many(
            {"id": {"$in": update_data.message_ids}},
            {"$addToSet": {"read_list": current_user.id}},
        )

        if result.modified_count == 0:
            return error(code=404, message="消息已标记或不存在")

        return success(message="标记成功")
    except Exception as e:
        logger.error(f"标记已读出错: {e}")
        return error(code=500, message="标记已读出错")


@router.get("/{group_uuid}", description="查询群详情")
async def get_group_by_uuid(
    group_uuid: str,
    current_user: User = Depends(get_current_user),
    db=Depends(get_database),
    chat_db=Depends(get_chat_database),
):
    try:
        group = await db.groups.find_one({"id": group_uuid})

        if not group or group["is_dissolved"]:
            return error(code=404, message="群组不存在或已解散")

        if current_user.id not in group["member_ids"]:
            return error(code=403, message="你不在该群组中")

        # 查询未读数
        chat_collection = getattr(chat_db, group_uuid)
        total_unread = await chat_collection.count_documents({
            "group_id": group_uuid,
            "is_revoke": False,
            "read_list": {"$ne": current_user.id},
        })

        # 获取成员信息
        members = []
        for member_id in group["member_ids"]:
            if group.get("type") == "private":
                if member_id == current_user.id:
                    continue
                user = await db.users.find_one({"id": member_id})
                if user:
                    members.append(UserResponse(**user).model_dump())
                    group["name"] = user["username"]
            else:
                user = await db.users.find_one(
                    {"id": member_id, "is_active": True}
                )
                if user:
                    user["is_friend"] = member_id in current_user.friends
                    members.append(UserResponse(**user).model_dump())

        group["members"] = members
        group["total_unread"] = total_unread

        return success(data=GroupDetailResponse(**to_client_data(group)).model_dump())
    except Exception as e:
        logger.error(f"获取群详情出错: {e}")
        return error(code=500, message="获取群详情出错")


@router.put("/{group_uuid}", description="修改群信息")
async def update_group(
    group_uuid: str,
    group_data: GroupCreate,
    current_user: User = Depends(get_current_user),
    db=Depends(get_database),
):
    try:
        group = await db.groups.find_one({
            "id": group_uuid,
            "is_dissolved": False,
        })

        if not group:
            return error(code=404, message="群组不存在")

        if group["owner_id"] != current_user.id:
            return error(code=403, message="只有群主能修改")

        if len(group_data.member_ids) == 0:
            return error(code=403, message="成员不能为空")

        update_data = {
            "name": group_data.name,
            "member_ids": group_data.member_ids,
        }

        # 移交群主
        if group_data.owner_id and group_data.owner_id != group["owner_id"]:
            if group_data.owner_id not in group_data.member_ids:
                return error(code=403, message="新群主必须是群成员")
            update_data["owner_id"] = group_data.owner_id

        await db.groups.update_one(
            {"id": group_uuid},
            {"$set": update_data}
        )

        return success(message="修改成功")
    except Exception as e:
        logger.error(f"修改群信息出错: {e}")
        return error(code=500, message="修改群信息出错")


@router.post("/messages", description="查询聊天记录")
async def get_group_messages(
    search_data: GroupMessageSearch,
    current_user: User = Depends(get_current_user),
    manage_db=Depends(get_database),
    chat_db=Depends(get_chat_database),
):
    try:
        group = await manage_db.groups.find_one({
            "id": search_data.id,
            "is_dissolved": False,
        })

        if not group:
            return error(code=404, message="群组不存在")

        if current_user.id not in group["member_ids"]:
            return error(code=403, message="你不在该群组中")

        chat_collection = getattr(chat_db, search_data.id)
        query = {"group_id": search_data.id, "is_revoke": False}

        if search_data.start_index:
            query["created_at"] = {"$lte": search_data.start_index}

        total = await chat_collection.count_documents(query)
        skip = max(0, total - (search_data.page * search_data.page_size))
        actual_limit = min(
            search_data.page_size,
            total - (search_data.page - 1) * search_data.page_size,
        )

        if (search_data.page - 1) * search_data.page_size >= total:
            messages = []
        else:
            messages = (
                await chat_collection.find(query)
                .sort("created_at", 1)
                .skip(skip)
                .limit(actual_limit)
                .to_list(None)
            )

        messages.reverse()

        for message in messages:
            message["is_read"] = current_user.id in message.get("read_list", [])

        start_index = (
            search_data.start_index
            if search_data.start_index
            else messages[0]["created_at"] if messages else None
        )

        data = PaginationModel(
            start_index=to_client_data(start_index),
            total=total,
            page=search_data.page,
            page_size=search_data.page_size,
            items=[
                MessageResponse(**to_client_data(m)).model_dump()
                for m in messages
            ],
        ).dict()

        data["group_name"] = group["name"]

        return success(data=data)
    except Exception as e:
        logger.error(f"获取聊天记录出错: {e}")
        return error(code=500, message="获取聊天记录失败")


@router.post("/messages/forward", description="转存聊天记录")
async def forward_messages(
    message_data: GroupForwardMessage,
    current_user: User = Depends(get_current_user),
    db=Depends(get_database),
):
    try:
        if not message_data.message_ids:
            return error(code=400, message="请选择要转存的消息")

        group_forward = GroupForward(
            group_id=message_data.group_id,
            message_ids=message_data.message_ids,
            forward_user_id=current_user.id,
        )

        await db.group_forwards.insert_one(group_forward.model_dump())

        return success(data={
            "forward_url": f"/group/messages/get_forward/page/{group_forward.id}"
        })
    except Exception as e:
        logger.error(f"转存出错: {e}")
        return error(code=500, message="转存出错")


@router.get("/messages/get_forward/{forward_id}", description="获取转存记录")
async def get_forwarded_message(
    forward_id: str,
    manage_db=Depends(get_database),
    chat_db=Depends(get_chat_database),
):
    try:
        document = await manage_db.group_forwards.find_one({"id": forward_id})
        if not document:
            return error(code=404, message="分享记录不存在")

        chat_collection = getattr(chat_db, document["group_id"])
        messages = await chat_collection.find({
            "id": {"$in": document["message_ids"]}
        }).to_list(None)

        forward = ForwardMessage(
            id=document["id"],
            group_id=document["group_id"],
            messages=[MessageData(**m) for m in messages],
            forward_user_id=document["forward_user_id"],
            created_at=document["created_at"],
        )

        return success(data=forward.model_dump())
    except Exception as e:
        logger.error(f"获取转存记录出错: {e}")
        return error(code=500, message="获取转存记录出错")


@router.get(
    "/messages/get_forward/page/{forward_id}",
    response_class=HTMLResponse,
    description="渲染分享页面",
)
async def get_forwarded_message_page(
    forward_id: str,
    request: Request,
    manage_db=Depends(get_database),
    chat_db=Depends(get_chat_database),
):
    try:
        document = await manage_db.group_forwards.find_one({"id": forward_id})
        if not document:
            return HTMLResponse(content="分享记录不存在", status_code=404)

        chat_collection = getattr(chat_db, document["group_id"])
        messages = await chat_collection.find({
            "id": {"$in": document["message_ids"]},
            "is_revoke": False,
        }).to_list(None)

        forward_user = await manage_db.users.find_one({
            "id": document["forward_user_id"],
            "is_active": True,
        })

        return templates.TemplateResponse(
            "forward_messages.html",
            {
                "request": request,
                "messages": messages,
                "forward_user_id": forward_user["id"],
                "forward_user": forward_user["username"],
                "forward_user_avatar": forward_user["avatar"],
                "forward_time": document["created_at"].strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
    except Exception as e:
        logger.error(f"渲染分享页面出错: {e}")
        return HTMLResponse(content="获取记录失败", status_code=500)


@router.get(
    "/user_unread_at_messages/{group_id}",
    description="获取未读@消息",
)
async def get_user_unread_at_messages(
    group_id: str,
    current_user: User = Depends(get_current_user),
    chat_db=Depends(get_chat_database),
):
    try:
        chat_data = (
            await getattr(chat_db, group_id)
            .find({
                "at_list": current_user.id,
                "is_revoke": False,
                "read_list": {"$not": {"$elemMatch": {"$eq": current_user.id}}},
            })
            .sort("created_at", 1)
            .to_list(None)
        )

        return success(data=[MessageResponse(**m) for m in chat_data])
    except Exception as e:
        logger.error(f"获取未读@消息出错: {e}")
        return error(code=500, message="获取未读@消息失败")
