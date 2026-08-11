import asyncio
import json
from typing import Any
from datetime import datetime
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from ..database import get_chat_database, get_database
from ..models.user import User
from ..models.message import Message
from ..utils.auth import get_current_user
from ..utils.websocket_manager import connection_manager
from ..utils.log import logger
from ..schemas.response import error, success

router = APIRouter()


def to_client_data(value: Any):
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
        """创建并保存消息"""
        user = await manage_db.users.find_one({"id": sender_id})
        if not user:
            return None

        group_collection = getattr(chat_db, group_id)
        if isinstance(content, (dict, list)):
            content = json.dumps(content, ensure_ascii=False)

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
        await group_collection.insert_one(message_dict)
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
async def websocket_endpoint(
    websocket: WebSocket,
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
        user = await get_current_user(token)
        user_data = await manage_db.users.find_one({
            "id": user.id,
            "is_active": True,
        })

        if not user_data:
            await websocket.close(code=4001, reason="用户不存在")
            return

        # 连接WebSocket
        await connection_manager.connect(user, websocket, send_ack=False)

        # ===== 关键改进：查询用户所属的所有群组 =====
        user_groups = await manage_db.groups.find({
            "member_ids": user.id,
            "is_dissolved": False,
        }).to_list(None)

        group_ids = [g["id"] for g in user_groups]

        # 订阅所有群组
        await user_group_manager.subscribe_groups(user.id, group_ids)
        await connection_manager.register_user_groups(user.id, group_ids)

        # 发送连接成功消息（包含用户所有群组信息）
        groups_info = []
        for g in user_groups:
            # 获取每个群的未读数
            chat_collection = getattr(chat_db, g["id"])
            unread = await chat_collection.count_documents({
                "group_id": g["id"],
                "is_revoke": False,
                "read_list": {"$ne": user.id},
            })
            groups_info.append({
                "group_id": g["id"],
                "name": g["name"],
                "type": g.get("type", "group"),
                "unread_count": unread,
                "last_message": g.get("last_message"),
            })

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

        # ===== 为每个群组发送最近消息 =====
        for group_id in group_ids:
            chat_collection = getattr(chat_db, group_id)
            recent = await chat_collection.find({
                "is_revoke": False,
            }).sort("created_at", -1).limit(5).to_list(None)
            recent.reverse()

            if recent:
                await websocket.send_json({
                    "type": "group_history",
                    "group_id": group_id,
                    "content": to_client_data(recent),
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

                        # 检查权限
                        msg = await group_collection.find_one({"id": message_id})
                        if msg and msg["sender_id"] == user.id:
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
                                        "group_id": group_id,
                                        "content": {"message_id": message_id, "sender_id": user.id}
                                    }
                                )

                            await websocket.send_json({
                                "type": "revoke_success",
                                "content": {"message_id": message_id}
                            })

                # 获取某个群的历史消息
                elif data.get("type") == "get_history":
                    group_id = data.get("group_id")
                    limit = data.get("limit", 20)
                    before_id = data.get("before_id")

                    if group_id in user_group_manager.get_user_groups(user.id):
                        chat_collection = getattr(chat_db, group_id)

                        query = {"is_revoke": False}
                        if before_id:
                            before_msg = await chat_collection.find_one({"id": before_id})
                            if before_msg:
                                query["created_at"] = {"$lt": before_msg["created_at"]}

                        messages = await chat_collection.find(query).sort("created_at", -1).limit(limit).to_list(None)
                        messages.reverse()

                        await websocket.send_json({
                            "type": "history",
                            "group_id": group_id,
                            "content": to_client_data(messages)
                        })

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
                        chat_collection = getattr(chat_db, group_id)
                        await chat_collection.update_many(
                            {"id": {"$in": message_ids}},
                            {"$addToSet": {"read_list": user.id}}
                        )
                        await websocket.send_json({
                            "type": "read_marked",
                            "group_id": group_id,
                            "content": {"message_ids": message_ids}
                        })

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
                        unread = await chat_collection.count_documents({
                            "is_revoke": False,
                            "read_list": {"$ne": user.id},
                        })
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
