import json
from datetime import datetime
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..database import get_chat_database, get_database
from ..models.group import Group, GroupForward
from ..models.user import User
from ..models.user_pinned_group import UserPinnedGroup  # 用户置顶群组模型
from ..models.user_cleared_group import UserClearedGroup  # 用户清空会话消息模型
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
    PinSetting,  # 置顶设置请求模型
    PinResponse,  # 置顶设置响应模型
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

        # 通知所有群成员刷新群列表（创建者前端已自行刷新，这里通知其他成员）
        await connection_dic.broadcast(
            group_data.member_ids,
            json.dumps({"type": "groups_updated"})
        )

        # 私聊设置对方名字为群名
        if group_data.type == "private":
            new_group_data = to_client_data(new_group_data)
            new_group_data["member_ids"].remove(current_user.id)
            user = await db.users.find_one(
                {"id": new_group_data["member_ids"][0]}
            )
            new_group_data["name"] = user["username"]

            # 新增：通知被邀请方自动打开私聊窗口（解决"第一次聊天要点一下私聊才能继续对话"的问题）
            other_member_id = new_group_data["member_ids"][0]
            await connection_dic.broadcast(
                [other_member_id],
                json.dumps({
                    "type": "private_chat_opened",
                    "group_id": new_group_data["id"],
                    "inviter_id": current_user.id,
                    "inviter_name": current_user.username
                })
            )

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

        # 通知被添加的用户刷新群列表（否则他们不知道被拉进了新群，发消息会报"你不在该群组中"）
        await connection_dic.broadcast(
            post_data.user_ids,
            json.dumps({"type": "groups_updated"})
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

        # 新增：如果是私聊，退出后只剩一个人，直接解散该私聊群
        if group.get("type") == "private":
            await db.groups.update_one(
                {"id": group_id},
                {"$set": {"is_dissolved": True}},
            )
            # 通知对方私聊已解散
            other_member_ids = [mid for mid in group["member_ids"] if mid != current_user.id]
            await connection_dic.broadcast(
                other_member_ids,
                json.dumps({"type": "group_dissolved", "group_id": group_id})
            )
            return success(message="已删除聊天")

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

        # 通知所有群成员群已解散，前端收到后自动移除该群
        member_ids = group.get("member_ids", [])
        await connection_dic.broadcast(
            member_ids,
            json.dumps({"type": "group_dissolved", "group_id": group_uuid})
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
    """
    查询用户的群组列表（支持置顶排序）

    排序规则：
    1. 置顶的群组排在最前面，按置顶时间降序（最近置顶的在前）
    2. 非置顶的群组按最新消息时间降序（原有逻辑）
    3. 置顶群组和普通群组分别分页，合并后返回

    数据流：
    1. 查询用户所有置顶的群组ID和置顶时间
    2. 分页获取群组数据
    3. 为每个群组添加 is_pinned 和 pinned_at 字段
    4. 按"置顶时间降序 + 最新消息时间降序"排序
    """
    try:
        total_unread = 0
        query = {
            "member_ids": current_user.id,
            "is_dissolved": False,
        }

        # 查询用户所有置顶的群组 {group_id: pinned_at}
        pinned_groups_cursor = manage_db.user_pinned_groups.find({
            "user_id": current_user.id,
        })
        pinned_groups_list = await pinned_groups_cursor.to_list(None)
        pinned_groups_map = {
            item["group_id"]: item["pinned_at"]
            for item in pinned_groups_list
        }

        # 计算总未读数
        from app.utils.message_query import count_unread_messages

        all_groups = await manage_db.groups.find(query).to_list(None)
        for group in all_groups:
            chat_collection = getattr(chat_db, group["id"])
            group_unread = await count_unread_messages(
                user_id=current_user.id,
                group_id=group["id"],
                chat_collection=chat_collection,
                manage_db=manage_db,
            )
            total_unread += group_unread

        # 分页参数
        page_size = inquiry.page_size
        skip = (inquiry.page - 1) * page_size

        # 查询群组列表（按最新消息时间降序，后续会重新排序）
        total = await manage_db.groups.count_documents(query)

        groups = (
            await manage_db.groups.find(query)
            .sort([("last_message.created_at", -1)])
            .skip(skip)
            .limit(page_size)
            .to_list(None)
        )

        # 为每个群组添加置顶信息和未读数
        for group in groups:
            # 添加置顶信息
            group_id = group["id"]
            if group_id in pinned_groups_map:
                group["is_pinned"] = True
                group["pinned_at"] = pinned_groups_map[group_id]
            else:
                group["is_pinned"] = False
                group["pinned_at"] = None

            # 计算未读数
            chat_collection = getattr(chat_db, group["id"])
            group_unread = await count_unread_messages(
                user_id=current_user.id,
                group_id=group["id"],
                chat_collection=chat_collection,
                manage_db=manage_db,
            )
            group["unread_count"] = group_unread

            # 私聊处理：显示对方用户名
            if group.get("type") == "private":
                group["member_ids"].remove(current_user.id)
                if not group["member_ids"]:
                    continue  # 私聊群成员为空时跳过
                user = await manage_db.users.find_one(
                    {"id": group["member_ids"][0]}
                )
                group["name"] = user["username"]

        # 排序：置顶群组在前，按置顶时间降序；普通群组在后，按最新消息时间降序
        # 注意：这里在内存中排序，如果群组数量很大，建议改用MongoDB聚合查询
        def get_sort_key(g):
            """
            排序键生成函数

            排序规则：
            1. 第一优先级：是否置顶（置顶的排前面）
            2. 第二优先级（置顶群组）：置顶时间降序（最近置顶的在前）
            3. 第三优先级（普通群组）：最新消息时间降序（最近发的在上面）

            Returns:
                tuple: (是否置顶, 置顶时间戳的负值, 最新消息时间戳的负值)
            """
            is_pinned = g.get("is_pinned", False)

            # 获取置顶时间戳
            pinned_at = g.get("pinned_at")
            pinned_ts = 0
            if pinned_at:
                if isinstance(pinned_at, datetime):
                    pinned_ts = pinned_at.timestamp()
                elif isinstance(pinned_at, str):
                    # 字符串格式的日期，解析为时间戳
                    pinned_ts = datetime.fromisoformat(pinned_at.replace("Z", "+00:00")).timestamp()

            # 获取最新消息时间戳
            last_msg_time = g.get("last_message", {}).get("created_at")
            last_msg_ts = 0
            if last_msg_time:
                if isinstance(last_msg_time, datetime):
                    last_msg_ts = last_msg_time.timestamp()
                elif isinstance(last_msg_time, str):
                    last_msg_ts = datetime.fromisoformat(last_msg_time.replace("Z", "+00:00")).timestamp()

            # 返回排序键：
            # - 第一个元素：not is_pinned（False排在前，True排在后，取反后置顶的为False）
            # - 第二个元素：-pinned_ts（置顶时间降序，时间戳取负值）
            # - 第三个元素：-last_msg_ts（最新消息时间降序）
            return (not is_pinned, -pinned_ts if is_pinned else 0, -last_msg_ts)

        groups.sort(key=get_sort_key)

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
        from app.utils.message_query import count_unread_messages
        chat_collection = getattr(chat_db, group_uuid)
        total_unread = await count_unread_messages(
            user_id=current_user.id,
            group_id=group_uuid,
            chat_collection=chat_collection,
            manage_db=manage_db,
        )

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
#    search_data: GroupMessageSearch 就是一个 请求参数的数据容器，它：
#     接收前端传来的查询参数（群组ID、分页、起始时间）
#       自动验证参数类型和必填字段
#       简化后端代码，让逻辑更清晰
    current_user: User = Depends(get_current_user),
    manage_db=Depends(get_database),
    chat_db=Depends(get_chat_database),
):
    """
    查询聊天记录（支持清空时间过滤）

    数据流：
    1. 验证群组存在且用户是成员
    2. 查询用户对该群组的清空记录
    3. 构建查询条件，过滤清空时间之前的消息
    4. 分页查询并返回结果
    """
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

        # 使用公共函数构建查询条件，统一过滤逻辑
        from app.utils.message_query import build_message_query
        query = await build_message_query(
            user_id=current_user.id,
            group_id=search_data.id,
            manage_db=manage_db,
            before_time=search_data.start_index,
        )
        query["group_id"] = search_data.id  # HTTP 接口需要额外加 group_id 条件

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

        # 修改：删除原来的 messages.reverse()。
        # 原因：上面 MongoDB 已经按 created_at 升序查询，反转后会变成新消息在上、旧消息在下，
        # 前端刷新历史或重新登录时就会看到消息顺序混乱。

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


# ==================== 会话置顶功能 ====================

@router.post("/{group_id}/pin", description="设置/取消会话置顶")
async def toggle_group_pin(
    group_id: str,
    pin_data: PinSetting,
    current_user: User = Depends(get_current_user),
    db=Depends(get_database),
):
    """
    设置或取消会话置顶

    业务逻辑：
    1. 验证群组存在且未解散
    2. 验证用户是该群组成员（只能置顶自己所在的群）
    3. 如果 is_pinned=True，创建或更新置顶记录
    4. 如果 is_pinned=False，删除置顶记录

    Args:
        group_id: 群组ID
        pin_data: 置顶设置请求，包含 is_pinned 字段
        current_user: 当前登录用户
        db: 数据库连接

    Returns:
        成功：返回置顶设置结果
        失败：返回错误信息
    """
    try:
        # 1. 验证群组存在且未解散
        group = await db.groups.find_one({
            "id": group_id,
            "is_dissolved": False,
        })

        if not group:
            return error(code=404, message="群组不存在或已解散")

        # 2. 验证用户是该群组成员（只能置顶自己所在的群）
        if current_user.id not in group["member_ids"]:
            return error(code=403, message="只能置顶自己所在的会话")

        # 3. 根据请求进行置顶或取消置顶操作
        if pin_data.is_pinned:
            # 置顶：查找是否已有置顶记录
            existing_pin = await db.user_pinned_groups.find_one({
                "user_id": current_user.id,
                "group_id": group_id,
            })

            if existing_pin:
                # 已存在置顶记录，更新置顶时间（相当于重新置顶）
                await db.user_pinned_groups.update_one(
                    {"id": existing_pin["id"]},
                    {"$set": {"pinned_at": datetime.now()}},
                )
                pinned_at = datetime.now()
            else:
                # 创建新的置顶记录
                new_pin = UserPinnedGroup(
                    user_id=current_user.id,
                    group_id=group_id,
                    pinned_at=datetime.now(),
                )
                await db.user_pinned_groups.insert_one(new_pin.model_dump())
                pinned_at = new_pin.pinned_at

            return success(
                message="置顶设置成功",
                data=PinResponse(
                    group_id=group_id,
                    is_pinned=True,
                    pinned_at=pinned_at,
                ).model_dump()
            )
        else:
            # 取消置顶：删除置顶记录
            result = await db.user_pinned_groups.delete_one({
                "user_id": current_user.id,
                "group_id": group_id,
            })

            if result.deleted_count == 0:
                # 本来就没有置顶记录，返回成功（幂等性）
                return success(
                    message="该会话未置顶",
                    data=PinResponse(
                        group_id=group_id,
                        is_pinned=False,
                        pinned_at=None,
                    ).model_dump()
                )

            return success(
                message="取消置顶成功",
                data=PinResponse(
                    group_id=group_id,
                    is_pinned=False,
                    pinned_at=None,
                ).model_dump()
            )

    except Exception as e:
        logger.error(f"置顶设置出错: {e}")
        return error(code=500, message="置顶设置出错")


# ==================== 会话清空功能 ====================

@router.post("/{group_id}/clear", description="清空会话消息")
async def clear_group_messages(
    group_id: str,
    current_user: User = Depends(get_current_user),
    db=Depends(get_database),
):
    """
    清空会话消息（只影响当前用户视角）

    业务逻辑：
    1. 验证群组存在且未解散
    2. 验证用户是该群组成员（只能清空自己所在的会话）
    3. 查找是否已有清空记录
       - 有：更新清空时间（重新清空）
       - 无：插入新清空记录
    4. 返回清空结果

    数据流：
    1. 查询群组 → 验证群组存在且未解散
    2. 检查成员 → 确保用户在该群组中
    3. 写入清空记录 → 记录 user_id + group_id + cleared_at
    4. 返回结果 → 告诉前端清空成功

    注意：
    - 清空操作不删除实际消息，只记录清空时间点
    - 查询消息时会过滤 created_at < cleared_at 的消息
    - 其他用户的聊天记录不受影响

    Args:
        group_id: 群组/会话ID
        current_user: 当前登录用户
        db: 数据库连接

    Returns:
        成功：返回清空时间点
        失败：返回错误信息
    """
    try:
        # 1. 验证群组存在且未解散
        group = await db.groups.find_one({
            "id": group_id,
            "is_dissolved": False,
        })

        if not group:
            return error(code=404, message="群组不存在或已解散")

        # 2. 验证用户是该群组成员（只能清空自己所在的会话）
        if current_user.id not in group["member_ids"]:
            return error(code=403, message="你不在该群组中，无法清空")

        # 3. 查找是否已有清空记录
        cleared_at = datetime.now()

        existing_clear = await db.user_cleared_groups.find_one({
            "user_id": current_user.id,
            "group_id": group_id,
        })

        if existing_clear:
            # 已有记录，更新清空时间（重新清空）
            await db.user_cleared_groups.update_one(
                {"id": existing_clear["id"]},
                {"$set": {"cleared_at": cleared_at}}
            )
        else:
            # 没有记录，插入新记录
            clear_record = UserClearedGroup(
                user_id=current_user.id,
                group_id=group_id,
                cleared_at=cleared_at,
            )
            await db.user_cleared_groups.insert_one(clear_record.model_dump())

        # 4. 返回结果
        return success(
            message="会话已清空",
            data={
                "group_id": group_id,
                "cleared_at": cleared_at.isoformat(),
            }
        )

    except Exception as e:
        logger.error(f"清空会话消息出错: {e}")
        return error(code=500, message="清空会话消息出错")
