import asyncio
import json
import time
from typing import Dict, List, Set, Optional
from datetime import datetime

from fastapi import WebSocket

from ..models.user import User
from .log import logger


class ConnectionInfo:
    """单个WebSocket连接信息"""
    def __init__(self, websocket: WebSocket, connected_at: datetime):
        self.websocket = websocket
        self.connected_at = connected_at
        self.last_ping = time.time()


class UserInfo:
    """用户连接信息（支持多设备）"""
    def __init__(self, user_id: str, username: str):
        self.user_id = user_id
        self.username = username
        self.connections: List[ConnectionInfo] = []
        self.last_active = time.time()

    def add_connection(self, websocket: WebSocket) -> ConnectionInfo:
        conn = ConnectionInfo(websocket, datetime.now())
        self.connections.append(conn)
        return conn

    def remove_connection(self, websocket: WebSocket) -> bool:
        for conn in self.connections:
            if conn.websocket == websocket:
                self.connections.remove(conn)
                return True
        return False

    def is_online(self) -> bool:
        return len(self.connections) > 0

    def update_active(self):
        self.last_active = time.time()


class ConnectionManager:
    """
    WebSocket连接管理器
    功能：
    - 多用户多设备连接管理
    - 在线状态追踪
    - 高效消息广播
    - 连接健康检查
    """

    def __init__(self):
        self.users: Dict[str, UserInfo] = {}  # user_id -> UserInfo
        self._lock = asyncio.Lock()
        self._group_members: Dict[str, Set[str]] = {}  # group_id -> set(user_ids)

    async def connect(
        self,
        user: User,
        websocket: WebSocket,
        group_id: Optional[str] = None,
        send_ack: bool = True,
    ):
        """
        用户连接WebSocket
        Args:
            user: 用户对象
            websocket: WebSocket连接
            group_id: 加入的群组ID（可选）
        """
        await websocket.accept()

        async with self._lock:
            user_id = user.id

            # 创建或更新用户信息
            if user_id not in self.users:
                self.users[user_id] = UserInfo(user_id, user.username)

            user_info = self.users[user_id]
            user_info.add_connection(websocket)
            user_info.update_active()

            # 记录群组成员
            if group_id:
                self._group_members.setdefault(group_id, set()).add(user_id)

        logger.info(f"用户 {user.username}({user_id}) 已连接，当前在线设备: {len(self.users[user_id].connections)}")

        if send_ack:
            await websocket.send_json({
                "type": "connected",
                "content": {
                    "user_id": user_id,
                    "username": user.username,
                    "connected_at": datetime.now().isoformat(),
                    "online_devices": len(self.users[user_id].connections)
                }
            })

    async def register_user_groups(self, user_id: str, group_ids: List[str]):
        async with self._lock:
            for group_id in group_ids:
                self._group_members.setdefault(group_id, set()).add(user_id)

    async def unregister_user_groups(self, user_id: str):
        async with self._lock:
            user_info = self.users.get(user_id)
            if user_info and user_info.is_online():
                return
            for members in self._group_members.values():
                members.discard(user_id)
            empty_groups = [
                group_id for group_id, members in self._group_members.items()
                if not members
            ]
            for group_id in empty_groups:
                del self._group_members[group_id]

    async def disconnect(self, user_id: str, websocket: WebSocket, group_id: Optional[str] = None):
        """
        用户断开WebSocket连接
        """
        async with self._lock:
            if user_id in self.users:
                user_info = self.users[user_id]
                user_info.remove_connection(websocket)

                # 从群组记录移除
                if group_id and group_id in self._group_members:
                    if user_id in self._group_members[group_id]:
                        # 只有用户完全离线时才移除
                        if not user_info.is_online():
                            self._group_members[group_id].discard(user_id)

                # 用户完全离线时清理
                if not user_info.is_online():
                    logger.info(f"用户 {user_info.username}({user_id}) 已完全离线")
                    # 不删除用户信息，保留最后活跃时间

        logger.info(f"{user_id} 断开一个连接")

    async def send_to_user(self, user_id: str, message: dict) -> bool:
        """
        发送消息给指定用户的所有设备
        Returns:
            是否成功发送
        """
        async with self._lock:
            user_info = self.users.get(user_id)
            if not user_info or not user_info.is_online():
                return False

            success = False
            for conn in list(user_info.connections):
                try:
                    await conn.websocket.send_json(message)
                    success = True
                except Exception as e:
                    logger.error(f"发送给用户 {user_id} 失败: {e}")
                    # 连接可能已断开，标记移除
                    if conn in user_info.connections:
                        user_info.connections.remove(conn)

            if success:
                user_info.update_active()

            return success

    async def broadcast_to_group(self, group_id: str, member_ids: List[str], message: dict) -> Dict[str, bool]:
        """
        广播消息给群组所有在线成员
        Args:
            group_id: 群组ID
            member_ids: 群组成员ID列表
            message: 要发送的消息字典
        Returns:
            发送结果 {user_id: bool}
        """
        results = {}
        message_str = json.dumps(message, ensure_ascii=False, default=str)

        # 并行发送提高效率
        tasks = []
        for user_id in member_ids:
            tasks.append(self._send_to_user_locked(user_id, message_str))

        # 使用 asyncio.gather 并行执行
        send_results = await asyncio.gather(*tasks, return_exceptions=True)

        for user_id, result in zip(member_ids, send_results):
            if isinstance(result, Exception):
                results[user_id] = False
            else:
                results[user_id] = result

        # 记录在线用户
        online_count = sum(1 for v in results.values() if v)
        logger.debug(f"群 {group_id} 消息广播完成: {online_count}/{len(member_ids)} 在线")

        return results

    async def _send_to_user_locked(self, user_id: str, message_str: str) -> bool:
        """内部方法：发送消息给用户"""
        async with self._lock:
            user_info = self.users.get(user_id)
            if not user_info or not user_info.is_online():
                return False

            success = False
            for conn in list(user_info.connections):
                try:
                    await conn.websocket.send_text(message_str)
                    success = True
                except Exception as e:
                    logger.warning(f"发送失败: {e}")
                    if conn in user_info.connections:
                        user_info.connections.remove(conn)

            if success:
                user_info.update_active()

            return success

    def get_online_users(self, group_id: Optional[str] = None) -> List[dict]:
        """
        获取在线用户列表
        Args:
            group_id: 可选，只返回指定群组的在线用户
        Returns:
            在线用户信息列表
        """
        online_users = []

        if group_id and group_id in self._group_members:
            user_ids = self._group_members[group_id]
        else:
            user_ids = self.users.keys()

        for user_id in user_ids:
            user_info = self.users.get(user_id)
            if user_info and user_info.is_online():
                online_users.append({
                    "user_id": user_id,
                    "username": user_info.username,
                    "device_count": len(user_info.connections),
                    "last_active": user_info.last_active
                })

        return online_users

    def is_user_online(self, user_id: str) -> bool:
        """检查用户是否在线"""
        user_info = self.users.get(user_id)
        return user_info is not None and user_info.is_online()

    def get_user_device_count(self, user_id: str) -> int:
        """获取用户在线设备数"""
        user_info = self.users.get(user_id)
        return len(user_info.connections) if user_info else 0

    def get_stats(self) -> dict:
        """获取连接统计信息"""
        total_users = len(self.users)
        online_users = sum(1 for u in self.users.values() if u.is_online())
        total_connections = sum(len(u.connections) for u in self.users.values())

        return {
            "total_users": total_users,
            "online_users": online_users,
            "total_connections": total_connections,
            "groups": len(self._group_members)
        }

    async def broadcast_online_status(self, group_id: str, user_id: str, is_online: bool):
        """
        广播用户在线状态变化给群组成员
        """
        user_info = self.users.get(user_id)
        if not user_info:
            return

        status_message = {
            "type": "user_status",
            "content": {
                "user_id": user_id,
                "username": user_info.username,
                "is_online": is_online,
                "device_count": len(user_info.connections) if is_online else 0,
                "timestamp": datetime.now().isoformat()
            }
        }

        # 获取群组成员并广播状态
        if group_id in self._group_members:
            member_ids = list(self._group_members[group_id])
            await self.broadcast_to_group(group_id, member_ids, status_message)

    async def broadcast(self, user_list: List[str], message) -> List[str]:
        if isinstance(message, str):
            message_str = message
        else:
            message_str = json.dumps(message, ensure_ascii=False, default=str)

        sent_user_ids = []
        tasks = [self._send_to_user_locked(user_id, message_str) for user_id in user_list]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for user_id, result in zip(user_list, results):
            if result is True:
                sent_user_ids.append(user_id)
        return sent_user_ids


# 全局连接管理器实例
connection_manager = ConnectionManager()

# 兼容旧代码的别名
connection_dic = connection_manager
