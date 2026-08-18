import asyncio
import json
from typing import Any
from datetime import datetime, timedelta
# timedelta 是 Python 标准库 datetime 模块中的时间差对象，用于表示两个时间点之间的差值。
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from ..database import get_chat_database, get_database
from ..models.user import User
from ..models.message import Message
from ..models.user_cleared_group import UserClearedGroup  # 用户清空会话消息模型
from ..utils.auth import get_current_user
from ..utils.group_mute import can_send_group_message
from ..utils.websocket_manager import connection_manager
from ..utils.log import logger
from ..utils.message_query import build_message_query
from ..schemas.response import error, success

router = APIRouter()


async def _get_offline_messages(
    manage_db,
    chat_db,
    user_id: str,
    last_offline_time,
    group_ids: list
) -> list:
    """
    查询用户离线消息
    Args:
        manage_db: 管理数据库
        chat_db: 聊天数据库
        user_id: 用户ID
        last_offline_time: 上次离线时间（可能为空）
        group_ids: 用户所在的群组ID列表
    Returns:
        离线消息列表，按群组分组
    """
    from app.utils.message_query import build_message_query

    offline_messages = []

    for group_id in group_ids:
        chat_collection = getattr(chat_db, group_id)

        # 使用公共函数构建基础查询条件
        query = await build_message_query(
            user_id=user_id,
            group_id=group_id,
            manage_db=manage_db,
        )
        query["sender_id"] = {"$ne": user_id}  # 离线消息排除自己的消息

        # 离线时间过滤：如果有离线时间，需要调整时间过滤
        if last_offline_time:
            # 查询用户对该群组的清空记录，取较晚的时间点
            clear_record = await manage_db.user_cleared_groups.find_one({
                "user_id": user_id,
                "group_id": group_id,
            })

            # 确定最终的时间过滤条件
            if clear_record:
                clear_time = clear_record["cleared_at"]
                # 取清空时间和离线时间中较晚的那个
                effective_time = max(clear_time, last_offline_time)
            else:
                effective_time = last_offline_time

            query["created_at"] = {"$gt": effective_time}

        # 查询消息，按时间排序
        messages = await chat_collection.find(query).sort("created_at", 1).to_list(None)

        if messages:
            offline_messages.append({
                "group_id": group_id,
                "messages": to_client_data(messages)
            })

    return offline_messages

'''这个函数是把 MongoDB 查出来的数据转换成前端能接收的 JSON 数据。
主要做几件事：
    如果是列表，就逐个转换
    如果是字典，就逐个字段转换，并去掉 MongoDB 的 _id
    如果是 datetime，转成字符串时间
    如果是 ObjectId，转成字符串
    其他普通值直接返回'''
def to_client_data(value: Any):
#     isinstance 是 Python 用来判断"某个值是不是某种类型"的函数。
# 比如：isinstance(value, list)，意思是：判断 value 是不是列表。
    if isinstance(value, list):
        return [to_client_data(item) for item in value]
    if isinstance(value, dict):
        return {
            key: to_client_data(item)
            for key, item in value.items()
            if key != "_id"     # 这句是排除 _id
        }
    if isinstance(value, datetime):
        return value.isoformat()
    if value.__class__.__name__ == "ObjectId":
        return str(value)  # ObjectId 是 MongoDB 自动生成的 _id 类型，前端不能直接识别，所以要转成字符串
    return value


class MessageHandler:
    """消息处理器"""

    @staticmethod
    async def create_message(
        manage_db,
        chat_db,
        group_id: str,
        sender_id: str,
        content: str,
        msg_type: str = "text",
        cite_id: str = None,
        at_list: list = None,
        duration: float = None,
        sound_file_id: str = None,
    ) -> Message:
        '''at_list：@了哪些人
            duration：语音时长
            sound_file_id：语音文件 ID'''
        
        """创建并保存消息"""
        user = await manage_db.users.find_one({"id": sender_id})
        if not user:
            return None

        group_collection = getattr(chat_db, group_id)
        if isinstance(content, (dict, list)):
            content = json.dumps(content, ensure_ascii=False)
            '''如果消息内容是字典或列表，就把它转成 JSON 字符串再存数据库。
                ensure_ascii=False 是为了中文不被转成乱码形式，能正常保存中文。'''

        # 语音消息和文字消息共用 Message 模型：
        # - 文字消息：type="text"，content 存文字本身。
        # - 语音消息：type 类似 "audio/webm"，content 存文件 ID，duration 存语音秒数。
        # 这样聊天列表只保存“消息记录”，真实语音文件由 files 表和 uploads 目录保存。
        message = Message(
            type=msg_type,
            content=content,
            sender_id=sender_id,
            sender_username=user.get("username", ""),
            sender_avatar=user.get("avatar"),
            group_id=group_id,
            at_list=at_list or [],
            read_list=[sender_id],
            duration=duration,
            sound_file_id=sound_file_id,
        )

        if cite_id:
            cite_message = await group_collection.find_one({"id": cite_id})
            if cite_message:
                message.cite = {
                    "id": cite_id,
                    "content": cite_message.get("content", ""),
                    "sender_id": cite_message.get("sender_id", ""),
                    "sender_username": cite_message.get("sender_username", ""),
                }

        message_dict = message.model_dump()
        # 每个群有自己的聊天集合，语音消息也会作为一条普通消息写进去。
        await group_collection.insert_one(message_dict)
        # 更新群列表最后一条消息，让左侧会话列表能显示最新动态。
        await manage_db.groups.update_one(
            {"id": group_id},
            {"$set": {"last_message": message_dict}},
        )

        return message

    @staticmethod
    async def broadcast_to_group(manage_db, group_id: str, message: Message):
        """广播消息给群组所有成员"""
        group = await manage_db.groups.find_one({"id": group_id})
        if not group or "member_ids" not in group:
            return

        # 关键改进：广播时带上group_id，让客户端知道是哪个群的消息
        broadcast_data = {
            "type": "message",
            "group_id": group_id,  # 标明消息来源群组
            "data": to_client_data(message.model_dump()),
            "timestamp": datetime.now().isoformat()
        }

        await connection_manager.broadcast_to_group(
            group_id, group["member_ids"], broadcast_data
        )


async def broadcast_and_save_msg(
    group_collection,
    manage_db,
    content,
    type,
    group_id,
    sender_id,
    cite_id=None,
    sound_file_id=None,
    duration=None,
    save_message=True,
    at_list=None,
    broadcast_ids=None,
):
    chat_db = await get_chat_database()
    handler = MessageHandler()
    # 文件/语音上传后会调用这里：先把“文件 ID + 文件类型 + 时长”包装成一条聊天消息并入库。
    message = await handler.create_message(
        manage_db=manage_db,
        chat_db=chat_db,
        group_id=group_id,
        sender_id=sender_id,
        content=content,
        msg_type=type,
        cite_id=cite_id,
        at_list=at_list or [],
        duration=duration,
        sound_file_id=sound_file_id,
    )

    if not message:
        return None

    if save_message:
        group = await manage_db.groups.find_one({"id": group_id})
        member_ids = broadcast_ids or (group.get("member_ids", []) if group else [])
        # 再通过 WebSocket 推给群成员；前端收到 type=audio/webm 后就会渲染语音播放器。
        await connection_manager.broadcast_to_group(
            group_id,
            member_ids,
            {
                "type": "message",
                "group_id": group_id,
                "data": to_client_data(message.model_dump()),
                "timestamp": datetime.now().isoformat(),
            },
        )
    return message


class UserGroupManager:
    """
    用户群组管理器
    核心功能：管理用户订阅的群组，实现多群组同时收消息
    """

    def __init__(self):
        self._user_groups: dict = {}  # {user_id: set(group_ids)}
        self._lock = asyncio.Lock()

    async def subscribe_groups(self, user_id: str, group_ids: list):
        """订阅用户的群组列表"""
        async with self._lock:
            if user_id not in self._user_groups:
                self._user_groups[user_id] = set()
            self._user_groups[user_id].update(group_ids)
            logger.info(f"用户 {user_id} 订阅了 {len(group_ids)} 个群组")

    async def unsubscribe(self, user_id: str):
        """用户断开连接时取消订阅"""
        async with self._lock:
            if user_id in self._user_groups:
                del self._user_groups[user_id]

    def get_user_groups(self, user_id: str) -> set:
        """获取用户订阅的群组"""
        return self._user_groups.get(user_id, set())


# 全局群组管理器
user_group_manager = UserGroupManager()


# ==================== 后台消息推送任务 ====================

async def message_push_worker():
    """
    消息推送工作线程
    功能：监听所有群组的新消息，推送给订阅了该群组的在线用户

    实际生产环境应该使用：
    - Redis Pub/Sub
    - Kafka消息队列
    - RabbitMQ
    """
    # 这里是简化版本，实际需要在消息创建时触发推送
    # 当前已经在 broadcast_to_group 中直接推送
    pass


# ==================== WebSocket端点 ====================

@router.websocket("/ws/{token}")
# token 是登录凭证，前端登录成功后拿到 access_token，然后连接 WebSocket 时把它拼进 URL：
#     /ws/{token}
#     FastAPI 会自动把 URL 里的 {token} 提取出来，传给函数参数：token: str
#     后端再用这个 token 解析用户身份，判断当前 WebSocket 连接是谁的。
async def websocket_endpoint(
    websocket: WebSocket,
    #FastAPI 自动把当前这条 WebSocket 连接对象传进来。
#     用户打开前端后建立连接： ws://127.0.0.1:8000/api/chat/ws/{token}
# 后端就会进入这个函数（ websocket_endpoint）：
    token: str,
    manage_db=Depends(get_database),
    chat_db=Depends(get_chat_database),
):
    """
    正式用户WebSocket端点
    改进：一个连接支持多群组，类似QQ
    """
    user = None

    try:
        # 验证用户
        user = await get_current_user(token)  # 这是根据 token 判断：当前登录的是谁。
        user_data = await manage_db.users.find_one({
            "id": user.id,
            "is_active": True,
        })# 返回的是当前用户对象。

        if not user_data:
            await websocket.close(code=4001, reason="用户不存在")
            return

        # 连接WebSocket
        await connection_manager.connect(user, websocket, send_ack=False)
        # send_ack 是"是否发送连接确认消息"

        # ===== 关键改进：查询用户所属的所有群组 =====
        user_groups = await manage_db.groups.find({
            "member_ids": user.id,
            "is_dissolved": False,
        }).to_list(None)

        group_ids = [g["id"] for g in user_groups]

        await user_group_manager.subscribe_groups(user.id, group_ids)
  #subscribe_groups    这个用户当前订阅了哪些群。主要用于判断用户能不能发/收某个群的消息。
        await connection_manager.register_user_groups(user.id, group_ids)
        #register_user_groups连接管理器里，这个用户和哪些群有关， 主要用于广播、在线用户、按群推送消息。
      
        # 发送连接成功消息（包含用户所有群组信息）
        groups_info = []
        for g in user_groups:
            # 获取每个群的未读数
            from app.utils.message_query import count_unread_messages
            chat_collection = getattr(chat_db, g["id"])
            unread = await count_unread_messages(
                user_id=user.id,
                group_id=g["id"],
                chat_collection=chat_collection,
                manage_db=manage_db,
            )

            groups_info.append({
                "group_id": g["id"],
                "name": g["name"],
                "type": g.get("type", "group"),
                "unread_count": unread,
                "last_message": g.get("last_message"),
            })

        '''在 WebSocket 连接成功后，主动发一条 connected 消息给前端，
        告诉前端当前用户是谁、有几个设备在线、有哪些群组、总未读数是多少。'''
        await websocket.send_json({
            "type": "connected",
            "content": {
                "user_id": user.id,
                "username": user.username,
                "device_count": connection_manager.get_user_device_count(user.id),
                "groups": to_client_data(groups_info),  # 用户所有群组列表
                "total_unread": sum(g["unread_count"] for g in groups_info),
            }
        })

        # ===== 为每个群组发送最近消息（仅10条）=====
        for group_id in group_ids:
            chat_collection = getattr(chat_db, group_id)

            # 使用公共函数构建查询条件，统一过滤逻辑
            from app.utils.message_query import build_message_query
            query = await build_message_query(
                user_id=user.id,
                group_id=group_id,
                manage_db=manage_db,
            )

            # 查询最近10条消息
            recent = await chat_collection.find(query).sort("created_at", -1).limit(10).to_list(None)
            recent.reverse()

            if recent:
                await websocket.send_json({
                    "type": "group_history",
                    "group_id": group_id,
                    "content": to_client_data(recent),
                })

        # ===== 发送离线消息 =====
        offline_messages = await _get_offline_messages(
            manage_db, chat_db, user.id, user_data.get("last_offline_time"), group_ids
        )
        if offline_messages:
            await websocket.send_json({
                "type": "offline_messages",
                "content": offline_messages
            })

        # ===== 消息处理循环 =====
        handler = MessageHandler()

        while True:
            try:
                data = await websocket.receive_json()

                # 心跳
                if data.get("type") == "ping":
                    await websocket.send_json({
                        "type": "pong",
                        "timestamp": datetime.now().isoformat()
                    })
                    continue

                # 刷新数据库
                manage_db = await get_database()
                chat_db = await get_chat_database()

                # ===== 处理各类请求 =====

                # 发送消息到指定群组
                if data.get("type") in ["send_message", "text"]:
                    group_id = data.get("group_id")
                    if not group_id:
                        await websocket.send_json({
                            "type": "error",
                            "content": {"message": "缺少group_id"}
                        })
                        continue
                    if not data.get("content"):
                        await websocket.send_json({
                            "type": "error",
                            "content": {"message": "消息内容不能为空"}
                        })
                        continue

                    # 检查权限
                    if group_id not in user_group_manager.get_user_groups(user.id):
                        await websocket.send_json({
                            "type": "error",
                            "content": {"message": "你不在该群组中"}
                        })
                        continue

                    # 检查群是否已解散
                    group = await manage_db.groups.find_one({"id": group_id})
                    if not group or group.get("is_dissolved"):
                        await websocket.send_json({
                            "type": "error",
                            "content": {"message": "该群已解散"}
                        })
                        continue

                    # 创建并广播消息
                    # 群禁言在真正创建消息前拦截：不写数据库，也不广播给其他成员。
                    can_send, reason = can_send_group_message(group, user.id, datetime.now())
                    if not can_send:
                        await websocket.send_json({
                            "type": "error",
                            "content": {"message": reason}
                        })
                        continue

                    message_type = data.get("msg_type")
                    if not message_type:
                        message_type = "text" if data.get("type") == "send_message" else data.get("type", "text")

                    message = await handler.create_message(
                        manage_db=manage_db,
                        chat_db=chat_db,
                        group_id=group_id,
                        sender_id=user.id,
                        content=data["content"],
                        msg_type=message_type,
                        cite_id=data.get("cite"),
                        at_list=data.get("at_list", []),
                    )

                    if message:
                        await handler.broadcast_to_group(manage_db, group_id, message)
                        await websocket.send_json({
                            "type": "message_sent",
                            "content": {
                                "message_id": message.id,
                                "group_id": group_id,
                                "success": True
                            }
                        })

                # 撤回消息
                elif data.get("type") == "revoke":
                    group_id = data.get("group_id")
                    message_id = data.get("message_id")

                    if group_id and message_id:
                        if group_id not in user_group_manager.get_user_groups(user.id):
                            await websocket.send_json({
                                "type": "error",
                                "content": {"message": "你不在该群组中"}
                            })
                            continue

                        group_collection = getattr(chat_db, group_id)
                        # getattr 的作用是：根据 group_id 动态找到这个群对应的消息集合。
                        # 检查权限
                        msg = await group_collection.find_one({"id": message_id})
                        if msg and msg["sender_id"] == user.id:
                            # 撤回时间限制：只能撤回2分钟内发送的消息
                            time_diff = datetime.now() - msg["created_at"]
                            if time_diff > timedelta(minutes=2):
                                await websocket.send_json({
                                    "type": "error",
                                    "content": {"message": "消息超过两分钟，不可撤回"}
                                })
                                continue

                            await group_collection.update_one(
                                {"id": message_id},
                                {"$set": {"is_revoke": True, "revoke_at": datetime.now()}}
                            )

                            # 广播撤回通知
                            group = await manage_db.groups.find_one({"id": group_id})
                            if group:
                                await connection_manager.broadcast_to_group(
                                    group_id,
                                    group["member_ids"],
                                    {
                                        "type": "message_revoke",
                                        '''表示后端广播给前端的消息类型是“消息已撤回”。
                                            前端收到这个类型后，就会找到对应消息，把它标记成：
                                            is_revoke: true
                                            然后页面显示“已撤回”。'''
                                                        "group_id": group_id,
                                        "content": {"message_id": message_id, "sender_id": user.id}
                                    }
                                )

                            await websocket.send_json({
                                "type": "revoke_success",
                                "content": {"message_id": message_id}
                            })

                # 删除消息（软删除，仅影响当前用户视角）
                elif data.get("type") == "delete_message":
                    group_id = data.get("group_id")
                    message_id = data.get("message_id")

                    if not group_id or not message_id:
                        await websocket.send_json({
                            "type": "error",
                            "content": {"message": "缺少group_id或message_id"}
                        })
                        continue

                    # 权限检查：用户必须在群组中
                    if group_id not in user_group_manager.get_user_groups(user.id):
                        await websocket.send_json({
                            "type": "error",
                            "content": {"message": "你不在该群组中"}
                        })
                        continue

                    group_collection = getattr(chat_db, group_id)

                    # 检查消息是否存在且未撤回
                    msg = await group_collection.find_one({"id": message_id, "is_revoke": False})
                    if not msg:
                        await websocket.send_json({
                            "type": "error",
                            "content": {"message": "消息不存在或已撤回"}
                        })
                        continue

                    # 将当前用户ID添加到 deleted_by_users 数组
                    await group_collection.update_one(
                        {"id": message_id},
                        {"$addToSet": {"deleted_by_users": user.id}, "$set": {"deleted_at": datetime.now()}}
                    )

                    # 返回删除成功响应
                    await websocket.send_json({
                        "type": "message_deleted",
                        "group_id": group_id,
                        "content": {
                            "message_id": message_id,
                            "deleted": True
                        }
                    })

                # 获取某个群的历史消息（分页加载）
                elif data.get("type") == "get_history":
                    group_id = data.get("group_id")
                    limit = data.get("limit", 20)
                    before_id = data.get("before_id")

                    if group_id in user_group_manager.get_user_groups(user.id):
                        chat_collection = getattr(chat_db, group_id)

                        # 获取分页锚点时间
                        before_time = None
                        if before_id:
                            before_msg = await chat_collection.find_one({"id": before_id})
                            if before_msg:
                                before_time = before_msg["created_at"]

                        # 使用公共函数构建查询条件，统一过滤逻辑
                        from app.utils.message_query import build_message_query
                        query = await build_message_query(
                            user_id=user.id,
                            group_id=group_id,
                            manage_db=manage_db,
                            before_time=before_time,
                        )

                        # ===== 分页逻辑：多查一条判断是否还有更多 =====
                        # 查询 limit + 1 条，用于判断是否还有更早的消息
                        messages = await chat_collection.find(query).sort("created_at", -1).limit(limit + 1).to_list(None)
                        # 倒序是为了先拿到"离 before_id 最近的几条历史消息"。后面前端展示还得倒回来

                        # 判断是否有更多消息
                        has_more = len(messages) > limit
                        if has_more:
                            # 截取前 limit 条
                            messages = messages[:limit]

                        # 按时间升序排列（旧消息在前，新消息在后）
                        messages.reverse()

                        # next_cursor 取当前批次最早消息的 ID（列表第一条）
                        next_cursor = messages[0]["id"] if messages else None

                        await websocket.send_json({
                            "type": "history",
                            "group_id": group_id,
                            "items": to_client_data(messages),
                            "has_more": has_more,
                            "next_cursor": next_cursor,
                            "before_id": before_id  # 返回请求中的 before_id，前端据此判断是首次加载还是加载更多
                        })
                        '''before_msg：这次根据 before_id 查出来的那条消息对象
                            next_cursor：后端返回给前端的"下次从哪里继续加载"的标记'''

                # 获取所有群组的在线用户
                elif data.get("type") == "get_online_users":
                    group_id = data.get("group_id")
                    if group_id:
                        if group_id not in user_group_manager.get_user_groups(user.id):
                            await websocket.send_json({
                                "type": "error",
                                "content": {"message": "你不在该群组中"}
                            })
                            continue
                        online = connection_manager.get_online_users(group_id)
                        await websocket.send_json({
                            "type": "online_users",
                            "group_id": group_id,
                            "content": online
                        })

                # 输入中状态
                elif data.get("type") == "typing":
                    group_id = data.get("group_id")
                    is_typing = data.get("is_typing", True)

                    if group_id and group_id in user_group_manager.get_user_groups(user.id):
                        # 检查群组类型，只处理私聊
                        group = await manage_db.groups.find_one({"id": group_id})
                        if group and group.get("type") == "private":
                            # 获取其他成员（排除自己）
                            other_member_ids = [mid for mid in group.get("member_ids", []) if mid != user.id]

                            if other_member_ids:
                                await connection_manager.broadcast_to_group(
                                    group_id,
                                    other_member_ids,
                                    {
                                        "type": "typing",
                                        "group_id": group_id,
                                        "content": {
                                            "user_id": user.id,
                                            "username": user.username,
                                            "is_typing": is_typing,
                                        }
                                    }
                                )

                # 标记已读
                elif data.get("type") == "mark_read":
                    group_id = data.get("group_id")
                    message_ids = data.get("message_ids", [])

                    if group_id and message_ids:
                        if group_id not in user_group_manager.get_user_groups(user.id):
                            await websocket.send_json({
                                "type": "error",
                                "content": {"message": "你不在该群组中"}
                            })
                            continue

                        # 检查群组类型
                        group = await manage_db.groups.find_one({"id": group_id})
                        is_private = group and group.get("type") == "private"

                        chat_collection = getattr(chat_db, group_id)

                        # 更新已读列表
                        await chat_collection.update_many(
                            {"id": {"$in": message_ids}},
                            {"$addToSet": {"read_list": user.id}}
                        )

                        # 发送已读确认给操作者
                        await websocket.send_json({
                            "type": "read_marked",
                            "group_id": group_id,
                            "content": {"message_ids": message_ids}
                        })

                        # 私聊已读通知：通知消息发送者"对方已读"
                        if is_private:
                            # 查询这些消息，找出发送者（排除自己）
                            messages = await chat_collection.find(
                                {"id": {"$in": message_ids}}
                            ).to_list(None)

                            sender_ids = set()
                            for msg in messages:
                                sender_id = msg.get("sender_id")
                                if sender_id and sender_id != user.id:
                                    sender_ids.add(sender_id)

                            # 通知每个发送者
                            for sender_id in sender_ids:
                                await connection_manager.send_to_user(
                                    sender_id,
                                    {
                                        "type": "message_read",
                                        "group_id": group_id,
                                        "content": {
                                            "message_ids": message_ids,
                                            "reader_id": user.id,
                                            "reader_name": user.username,
                                        }
                                    }
                                )

                # 刷新群组列表（比如新建群后）
                elif data.get("type") == "refresh_groups":
                    user_groups = await manage_db.groups.find({
                        "member_ids": user.id,
                        "is_dissolved": False,
                    }).to_list(None)

                    new_group_ids = [g["id"] for g in user_groups]
                    await user_group_manager.subscribe_groups(user.id, new_group_ids)
                    await connection_manager.register_user_groups(user.id, new_group_ids)

                    groups_info = []
                    for g in user_groups:
                        chat_collection = getattr(chat_db, g["id"])

                        # 使用公共函数统计未读数
                        from app.utils.message_query import count_unread_messages
                        unread = await count_unread_messages(
                            user_id=user.id,
                            group_id=g["id"],
                            chat_collection=chat_collection,
                            manage_db=manage_db,
                        )
                        groups_info.append({
                            "group_id": g["id"],
                            "name": g["name"],
                            "unread_count": unread,
                        })

                    await websocket.send_json({
                        "type": "groups_updated",
                        "content": to_client_data(groups_info)
                    })

            except WebSocketDisconnect:
                break
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "content": {"message": "无效JSON"}
                })
            except Exception as e:
                logger.error(f"消息处理错误: {e}")
                await websocket.send_json({
                    "type": "error",
                    "content": {"message": str(e)}
                })

    except Exception as e:
        logger.error(f"WebSocket错误: {e}")

    finally:
        if user:
            await connection_manager.disconnect(user.id, websocket)
            await connection_manager.unregister_user_groups(user.id)
            await user_group_manager.unsubscribe(user.id)


# ==================== HTTP接口 ====================

@router.get("/stats")
async def get_stats():
    """连接统计"""
    return success(data=connection_manager.get_stats())


@router.get("/online/{group_id}")
async def get_online(group_id: str, current_user: User = Depends(get_current_user)):
    """获取群组在线用户"""
    return success(data=connection_manager.get_online_users(group_id))


@router.get("/search", description="搜索会话内消息")
async def search_messages(
    group_id: str,
    keyword: str,
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(get_current_user),
    manage_db=Depends(get_database),
    chat_db=Depends(get_chat_database),
):
    """
    在指定会话内搜索消息

    Args:
        group_id: 群组/私聊ID
        keyword: 搜索关键词
        page: 页码，默认1
        page_size: 每页条数，默认20，最大100

    Returns:
        搜索结果列表，包含消息详情和分页信息
    """
    # 1. 参数校验
    keyword = keyword.strip()
    if not keyword:
        return error(code=400, message="关键词不能为空")
    if len(keyword) < 2:
        return error(code=400, message="关键词至少需要2个字符")

    # 限制每页最大条数
    page_size = min(page_size, 100)
    page = max(page, 1)

    # 2. 权限校验
    group = await manage_db.groups.find_one({
        "id": group_id,
        "is_dissolved": False,
    })
    if not group:
        return error(code=404, message="群组不存在")

    if current_user.id not in group.get("member_ids", []):
        return error(code=403, message="无权限访问该会话")

    # 3. 构建查询条件
    chat_collection = getattr(chat_db, group_id)

    # 使用公共函数构建基础查询条件（过滤已撤回、已删除消息）
    query = await build_message_query(
        user_id=current_user.id,
        group_id=group_id,
        manage_db=manage_db,
    )

    # 添加关键词匹配条件（只搜索文本消息）
    query["content"] = {"$regex": keyword, "$options": "i"}
    query["type"] = "text"

    # 4. 分页查询
    skip = (page - 1) * page_size
    total = await chat_collection.count_documents(query)

    messages = await chat_collection.find(query) \
        .sort("created_at", -1) \
        .skip(skip) \
        .limit(page_size) \
        .to_list(None)

    # 5. 构建响应
    items = []
    for msg in messages:
        items.append({
            "id": msg["id"],
            "content": msg["content"],
            "type": msg["type"],
            "sender_id": msg["sender_id"],
            "sender_username": msg.get("sender_username", ""),
            "sender_avatar": msg.get("sender_avatar"),
            "created_at": msg["created_at"].isoformat(),
        })

    return success(data={
        "group_id": group_id,
        "keyword": keyword,
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "has_more": skip + len(items) < total,
    })
