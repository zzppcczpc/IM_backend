import re
import json
from datetime import datetime
from fastapi import APIRouter, Depends
from jose import jwt

from ..config import settings
from ..database import get_database
from ..models.token_blacklist import TokenBlacklist
from ..models.user import User
from ..schemas.response import PaginationModel, error, success
from ..schemas.user import (
    SearchFriend,
    UserFriendHandle,
    UserFriendRequest,
    UserFriendRequestResponse,
    UserQuery,
    UserResponse,
    UserSearch,
    UserUpdate,
)
from ..utils import security
from ..utils.auth import get_current_user, oauth2_scheme
from ..utils.log import logger
from ..utils.websocket_manager import connection_dic

router = APIRouter()


@router.post("/search", description="搜索用户")
async def search_user(
    search_data: UserSearch,
    current_user: User = Depends(get_current_user),
    db=Depends(get_database),
):
    try:
        query = {}
        if search_data.id:
            query["id"] = search_data.id
        if search_data.username:
            query["username"] = {"$regex": search_data.username, "$options": "i"}
        if search_data.phone:
            query["phone"] = search_data.phone
        if search_data.email:
            query["email"] = search_data.email

        if not query:
            return error(code=404, message="未查询到用户")

        query["is_active"] = True
        users = await db.users.find(query).to_list(length=None)

        if not users:
            return error(code=404, message="未查询到用户")

        for user in users:
            user["is_friend"] = user["id"] in current_user.friends

        return success(data=[
            UserResponse(**user).model_dump() for user in users
        ])
    except Exception as e:
        logger.error(f"搜索用户出错: {e}")
        return error(code=500, message="搜索用户出错")


@router.post("/query", description="精确搜索用户")
async def query_user(
    query_data: UserQuery,
    current_user: User = Depends(get_current_user),
    db=Depends(get_database),
):
    try:
        users = await db.users.find({
            "$or": [
                {"username": {"$eq": query_data.query_str}},
                {"phone": {"$eq": query_data.query_str}},
                {"email": {"$eq": query_data.query_str}},
            ],
            "is_active": True,
        }).to_list(length=None)

        for user in users:
            user["is_friend"] = user["id"] in current_user.friends

        return success(data=[
            UserResponse(**item) for item in users
        ])
    except Exception as e:
        logger.error(f"查询用户出错: {e}")
        return error(code=500, message="查询用户出错")


@router.put("/{user_id}", description="修改用户信息")
async def update_user(
    user_id: str,
    user_data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db=Depends(get_database),
):
    try:
        if current_user.id != user_id:
            return error(code=403, message="无权修改")

        user = await db.users.find_one({"id": user_id, "is_active": True})
        if not user:
            return error(code=404, message="用户不存在")

        # 检查用户名重复
        existing = await db.users.find_one({
            "username": user_data.username,
            "is_active": True,
        })
        if existing and existing["id"] != user_id:
            return error(code=409, message="用户名已被使用")

        modify_data = {"username": user_data.username}
        if user_data.phone and user_data.phone != current_user.phone:
            exist_phone = await db.users.find_one({
                "phone": user_data.phone,
                "is_active": True,
            })
            if exist_phone:
                return error(code=409, message="手机号已被使用")
            modify_data["phone"] = user_data.phone

        await db.users.update_one({"id": user_id}, {"$set": modify_data})

        return success(message="更新成功")
    except Exception as e:
        logger.error(f"更新用户出错: {e}")
        return error(code=500, message="更新用户出错")


@router.delete("/friend/{friend_id}", description="删除好友")
async def delete_friend(
    friend_id: str,
    current_user: User = Depends(get_current_user),
    db=Depends(get_database),
):
    try:
        if friend_id == current_user.id:
            return error(code=403, message="不能删除自己")

        friend = await db.users.find_one({"id": friend_id, "is_active": True})
        if not friend:
            return error(code=404, message="用户不存在")

        if friend_id not in current_user.friends:
            return error(code=403, message="该用户不是你的好友")

        # 双向删除
        await db.users.update_one(
            {"id": current_user.id},
            {"$pull": {"friends": friend_id}}
        )
        await db.users.update_one(
            {"id": friend_id},
            {"$pull": {"friends": current_user.id}}
        )

        return success(message="删除成功")
    except Exception as e:
        logger.error(f"删除好友出错: {e}")
        return error(code=500, message="删除好友出错")


@router.get("/friend/request/{friend_id}", description="发送好友请求")
async def send_friend_request(
    friend_id: str,
    current_user: User = Depends(get_current_user),
    db=Depends(get_database),
):
    try:
        if friend_id == current_user.id:
            return error(code=403, message="不能添加自己")

        send_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        friend = await db.users.find_one({"id": friend_id, "is_active": True})
        if not friend:
            return error(code=404, message="用户不存在")

        if friend_id in current_user.friends:
            return error(code=409, message="已经是好友")

        # 检查是否已发送
        for req in friend.get("friend_requests", []):
            if (
                req.get("request_type") == "from"
                and req.get("user_id") == current_user.id
                and req.get("status") == "pending"
            ):
                return error(code=409, message="已发送过请求")

        # 创建请求记录
        from_request = UserFriendRequest(
            request_type="from",
            user_id=current_user.id,
            username=current_user.username,
            avatar=current_user.avatar,
            status="pending",
            created_at=send_time,
        )

        to_request = UserFriendRequest(
            request_type="to",
            user_id=friend_id,
            username=friend["username"],
            avatar=friend.get("avatar"),
            status="sended",
            created_at=send_time,
        )

        await db.users.update_one(
            {"id": friend_id},
            {"$push": {"friend_requests": from_request.model_dump()}}
        )
        await db.users.update_one(
            {"id": current_user.id},
            {"$push": {"friend_requests": to_request.model_dump()}}
        )

        await connection_dic.broadcast(
            [friend_id],
            json.dumps({"type": "refresh_friend_request_count"})
        )

        return success(message="好友请求已发送")
    except Exception as e:
        logger.error(f"发送好友请求出错: {e}")
        return error(code=500, message="发送好友请求出错")


@router.post("/friend/request_list/list", description="获取好友请求列表")
async def get_friend_request_list(
    user_search: SearchFriend,
    current_user: User = Depends(get_current_user),
    db=Depends(get_database),
):
    try:
        user_data = await db.users.find_one({
            "id": current_user.id,
            "is_active": True,
        })

        requests = user_data.get("friend_requests", [])

        if user_search.search:
            escaped = re.escape(user_search.search)
            pattern = f".*{escaped}.*"
            requests = [
                r for r in requests
                if re.search(pattern, r.get("username", ""), re.IGNORECASE)
            ]

        requests = sorted(requests, key=lambda x: x["created_at"], reverse=True)

        start = (user_search.page - 1) * user_search.page_size
        end = start + user_search.page_size
        page_requests = requests[start:end]

        return success(data=PaginationModel(
            total=len(requests),
            page=user_search.page,
            page_size=user_search.page_size,
            items=[UserFriendRequestResponse(**r) for r in page_requests],
        ))
    except Exception as e:
        logger.error(f"获取好友请求列表出错: {e}")
        return error(code=500, message="获取好友请求列表出错")


@router.post("/friend/handle", description="处理好友请求")
async def handle_friend_request(
    request_data: UserFriendHandle,
    current_user: User = Depends(get_current_user),
    db=Depends(get_database),
):
    try:
        handle_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if request_data.action not in ["accept", "reject"]:
            return error(code=400, message="无效操作")

        # 找到请求
        request = None
        for req in current_user.friend_requests:
            if req.get("status") == "pending" and req.get("user_id") == request_data.friend_id:
                request = req
                break

        if not request:
            return error(code=404, message="未找到好友请求")

        if request_data.action == "accept":
            # 双向添加好友
            await db.users.update_one(
                {"id": current_user.id},
                {
                    "$push": {"friends": request_data.friend_id},
                    "$set": {
                        "friend_requests.$[elem].status": "accepted",
                        "friend_requests.$[elem].handled_at": handle_time,
                    },
                },
                array_filters=[
                    {"elem.user_id": request_data.friend_id, "elem.request_type": "from", "elem.status": "pending"}
                ],
            )
            await db.users.update_one(
                {"id": request_data.friend_id},
                {
                    "$push": {"friends": current_user.id},
                    "$set": {
                        "friend_requests.$[elem].status": "accepted",
                        "friend_requests.$[elem].handled_at": handle_time,
                    },
                },
                array_filters=[
                    {"elem.user_id": current_user.id, "elem.request_type": "to", "elem.status": "sended"}
                ],
            )
            result = "已接受好友请求"
        else:
            # 拒绝
            await db.users.update_one(
                {"id": current_user.id},
                {"$set": {
                    "friend_requests.$[elem].status": "rejected",
                    "friend_requests.$[elem].handled_at": handle_time,
                }},
                array_filters=[
                    {"elem.user_id": request_data.friend_id, "elem.request_type": "from", "elem.status": "pending"}
                ],
            )
            await db.users.update_one(
                {"id": request_data.friend_id},
                {"$set": {
                    "friend_requests.$[elem].status": "rejected",
                    "friend_requests.$[elem].handled_at": handle_time,
                }},
                array_filters=[
                    {"elem.user_id": current_user.id, "elem.request_type": "to", "elem.status": "sended"}
                ],
            )
            result = "已拒绝好友请求"

        await connection_dic.broadcast(
            [current_user.id],
            json.dumps({"type": "refresh_friend_request_count"})
        )

        return success(message=result)
    except Exception as e:
        logger.error(f"处理好友请求出错: {e}")
        return error(code=500, message="处理好友请求出错")


@router.get("/friends", description="获取好友列表")
async def get_friends(
    search: str = None,
    current_user: User = Depends(get_current_user),
    db=Depends(get_database),
):
    try:
        friends = []

        if search == "[object Object]":
            search = None

        if not search:
            for friend_id in set(current_user.friends):
                friend = await db.users.find_one({
                    "id": friend_id,
                    "is_active": True,
                })
                if friend:
                    friend["is_friend"] = True
                    friends.append(UserResponse(**friend).model_dump())
        else:
            users = await db.users.find({
                "$or": [
                    {"username": {"$regex": search, "$options": "i"}},
                    {"phone": {"$regex": search, "$options": "i"}},
                    {"email": {"$regex": search, "$options": "i"}},
                ],
                "is_active": True,
            }).to_list(length=None)

            for user in users:
                if user["id"] in current_user.friends:
                    user["is_friend"] = True
                    friends.append(UserResponse(**user).model_dump())

        return success(data=friends)
    except Exception as e:
        logger.error(f"获取好友列表出错: {e}")
        return error(code=500, message="获取好友列表出错")


@router.delete("/logout", description="注销用户")
async def logout(
    current_user: User = Depends(get_current_user),
    db=Depends(get_database),
):
    try:
        await db.users.update_one(
            {"id": current_user.id},
            {"$set": {"is_active": False}}
        )
        return success(message="注销成功")
    except Exception as e:
        logger.error(f"注销出错: {e}")
        return error(code=500, message="注销出错")


@router.post("/invalidate-token", description="使token失效")
async def invalidate_token(
    current_user: User = Depends(get_current_user),
    token: str = Depends(oauth2_scheme),
    db=Depends(get_database),
):
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[security.ALGORITHM])
        expired_at = datetime.fromtimestamp(payload["exp"])

        blacklist_token = TokenBlacklist(
            token=token,
            user_id=current_user.id,
            expired_at=expired_at,
        )
        await db.token_blacklist.insert_one(blacklist_token.model_dump())

        return success(message="token已失效")
    except Exception as e:
        logger.error(f"使token失效出错: {e}")
        return error(code=500, message="使token失效出错")


@router.get("/friend_requests/count", description="获取好友请求数量")
async def get_friend_requests_count(
    current_user: User = Depends(get_current_user),
    db=Depends(get_database),
):
    try:
        user = await db.users.find_one({"id": current_user.id, "is_active": True})
        if not user:
            return error(code=404, message="用户不存在")

        count = len([
            r for r in user.get("friend_requests", [])
            if r.get("status") == "pending"
        ])

        return success(data={"count": count})
    except Exception as e:
        logger.error(f"获取好友请求数量出错: {e}")
        return error(code=500, message="获取好友请求数量出错")
