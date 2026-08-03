from datetime import datetime

from ..config import settings
from ..database import get_database
from ..models.group import Group
from ..models.user import User
from ..utils.log import logger
from ..utils.security import get_password_hash


TEST_USERS = [
    {
        "id": "11111111-1111-1111-1111-111111111111",
        "username": "测试用户一",
        "email": "test1@example.com",
    },
    {
        "id": "22222222-2222-2222-2222-222222222222",
        "username": "测试用户二",
        "email": "test2@example.com",
    },
]

TEST_GROUP_ID = "im-test-group"


async def ensure_test_data():
    if not settings.INIT_TEST_USERS:
        return

    db = await get_database()
    password_hash = get_password_hash(settings.TEST_USER_PASSWORD)
    user_ids = [item["id"] for item in TEST_USERS]

    for item in TEST_USERS:
        user = User(
            id=item["id"],
            username=item["username"],
            email=item["email"],
            hashed_password=password_hash,
            is_active=True,
            friends=user_ids,
        )
        await db.users.update_one(
            {"email": item["email"]},
            {
                "$set": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "hashed_password": user.hashed_password,
                    "is_active": True,
                    "friends": user_ids,
                    "verification_code": None,
                },
                "$setOnInsert": {
                    "created_at": datetime.now(),
                    "avatar": None,
                    "phone": None,
                    "friend_requests": [],
                    "is_temp_user": False,
                },
            },
            upsert=True,
        )

    existing_group = await db.groups.find_one({
        "id": TEST_GROUP_ID,
        "is_dissolved": False,
    })
    if not existing_group:
        now = datetime.now()
        group = Group(
            id=TEST_GROUP_ID,
            name="IM测试群",
            owner_id=TEST_USERS[0]["id"],
            member_ids=user_ids,
            type="group",
            last_message={
                "created_at": now,
                "id": "",
                "type": "",
                "content": "",
                "sender_id": "",
                "sender_username": "",
                "group_id": TEST_GROUP_ID,
            },
        )
        await db.groups.insert_one(group.model_dump())
    else:
        await db.groups.update_one(
            {"id": TEST_GROUP_ID},
            {"$set": {"member_ids": user_ids, "is_dissolved": False}},
        )

    logger.info(
        "测试账号已初始化: test1@example.com / %s, test2@example.com / %s",
        settings.TEST_USER_PASSWORD,
        settings.TEST_USER_PASSWORD,
    )
