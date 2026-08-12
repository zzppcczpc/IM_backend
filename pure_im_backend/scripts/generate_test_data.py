#!/usr/bin/env python
"""
MongoDB 测试数据生成脚本

用法:
    python scripts/generate_test_data.py --clean      # 清空并重新生成
    python scripts/generate_test_data.py              # 追加数据
    python scripts/generate_test_data.py --help       # 查看帮助
"""

import argparse
import asyncio
import random
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings
from app.database import get_database, get_chat_database
from app.models.user import User
from app.models.group import Group
from app.models.message import Message
from app.utils.security import get_password_hash


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="生成MongoDB测试数据",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="清空现有测试数据后重新生成",
    )
    parser.add_argument(
        "--users",
        type=int,
        default=30,
        help="生成的用户数量（默认30）",
    )
    parser.add_argument(
        "--messages",
        type=int,
        default=250,
        help="生成的消息数量（默认250）",
    )
    parser.add_argument(
        "--password",
        type=str,
        default="123456",
        help="测试用户密码（默认123456）",
    )
    parser.add_argument(
        "--db-url",
        type=str,
        default=None,
        help="MongoDB连接串（默认读取config）",
    )
    return parser.parse_args()


# 姓氏列表（30个）
SURNAMES = [
    "张", "王", "李", "赵", "陈", "刘", "周", "吴", "郑", "孙",
    "钱", "冯", "杨", "朱", "徐", "何", "高", "林", "马", "黄",
    "罗", "梁", "宋", "谢", "韩", "唐", "于", "董", "许", "邓",
]

# 姓氏到拼音的映射
PINYIN_MAP = {
    "张": "zhangsan", "王": "wangwu", "李": "lisi", "赵": "zhaoliu",
    "陈": "chenqi", "刘": "liuba", "周": "zhoujiu", "吴": "wushi",
    "郑": "zhengshiyi", "孙": "sunshier", "钱": "qianshisan", "冯": "fengshisi",
    "杨": "yangshiwu", "朱": "zhushiliu", "徐": "xushiqi", "何": "heshiba",
    "高": "gaoshijiu", "林": "linershi", "马": "maershiyi", "黄": "huangershi",
    "罗": "luoershi", "梁": "liangershi", "宋": "songershis", "谢": "xieershiwu",
    "韩": "hanershiliu", "唐": "tangershiqi", "于": "yueershiba", "董": "dongershi",
    "许": "xusanshiyi", "邓": "dengsanshi",
}

# 群组配置
GROUP_CONFIGS = [
    {"name": "全员大群", "member_count": "all", "description": "全员群"},
    {"name": "产品研发组", "member_count": 15, "description": "工作群"},
    {"name": "技术交流群", "member_count": 8, "description": "技术群"},
    {"name": "项目小分队", "member_count": 5, "description": "小群"},
    {"name": "休闲茶话会", "member_count": 10, "description": "休闲群"},
]

# 消息示例内容
TEXT_SAMPLES = [
    "大家好，今天的工作进展如何？",
    "收到，马上处理",
    "这个方案我觉得不错",
    "有谁有空帮我看看这个问题",
    "稍等，我查一下文档",
    "好的，没问题",
    "今天的会议改到下午3点",
    "附件已发送，请查收",
    "这个bug已经修复了",
    "周末有空一起吃饭吗？",
    "项目进度正常，按时交付",
    "代码已经提交，请review",
    "测试通过了，可以上线",
    "有个问题想请教一下",
    "收到，谢谢！",
    "好的，我来看看",
    "这个问题我也遇到过",
    "建议使用新的方案",
    "文档已更新",
    "辛苦了！",
]

# 私聊消息示例
PRIVATE_TEXT_SAMPLES = [
    "你好，在吗？",
    "有个事想问问你",
    "刚才说的那个问题",
    "好的，我知道了",
    "谢谢帮忙！",
    "晚上一起吃饭？",
    "文档发你了",
    "那个需求怎么说？",
    "明白了",
    "稍后回复你",
]


def generate_users(count: int, password: str) -> List[Dict[str, Any]]:
    """生成用户数据"""
    users = []
    password_hash = get_password_hash(password)

    for i in range(count):
        surname = SURNAMES[i % len(SURNAMES)]
        pinyin = PINYIN_MAP[surname]

        # 如果有重名，添加数字后缀
        if i >= len(SURNAMES):
            pinyin = f"{pinyin}{i - len(SURNAMES) + 1}"

        user_id = f"test-user-{i+1:04d}"
        username = f"测试用户_{surname}"
        if i >= len(SURNAMES):
            username = f"{username}{i - len(SURNAMES) + 1}"

        user = {
            "id": user_id,
            "username": username,
            "email": f"test_{pinyin}@example.com",
            "hashed_password": password_hash,
            "is_active": True,
            "avatar": None,
            "phone": None,
            "verification_code": None,
            "created_at": datetime.now() - timedelta(days=random.randint(30, 365)),
            "department_id": None,
            "friends": [],
            "friend_requests": [],
            "is_temp_user": False,
        }
        users.append(user)

    return users


async def save_users(users: List[Dict[str, Any]], clean: bool = False) -> int:
    """保存用户到数据库"""
    db = await get_database()

    if clean:
        result = await db.users.delete_many({
            "email": {"$regex": r"^test_.*@example\.com$"}
        })
        print(f"已删除 {result.deleted_count} 个测试用户")

    inserted = 0
    for user in users:
        await db.users.update_one(
            {"id": user["id"]},
            {"$set": user},
            upsert=True
        )
        inserted += 1

    return inserted


async def generate_friendships(users: List[Dict[str, Any]]) -> int:
    """为用户生成好友关系（双向）"""
    db = await get_database()
    user_ids = [u["id"] for u in users]
    total_friendships = 0

    for user in users:
        # 好友数量：最少1个，最多min(15, 用户总数-1)
        max_friends = min(15, len(user_ids) - 1)
        min_friends = min(1, max_friends)
        friend_count = random.randint(min_friends, max_friends)
        potential_friends = [uid for uid in user_ids if uid != user["id"]]
        friends = random.sample(potential_friends, friend_count)

        await db.users.update_one(
            {"id": user["id"]},
            {"$set": {"friends": friends}}
        )

        total_friendships += len(friends)

    return total_friendships


async def generate_groups(users: List[Dict[str, Any]], clean: bool = False) -> int:
    """生成群组数据"""
    db = await get_database()
    user_ids = [u["id"] for u in users]

    if clean:
        result = await db.groups.delete_many({
            "id": {"$regex": r"^test-group-"}
        })
        print(f"已删除 {result.deleted_count} 个测试群组")

    created = 0
    for i, config in enumerate(GROUP_CONFIGS):
        if config["member_count"] == "all":
            member_ids = user_ids.copy()
        else:
            member_count = min(config["member_count"], len(user_ids))
            member_ids = random.sample(user_ids, member_count)

        group_id = f"test-group-{i+1:02d}"

        group = {
            "id": group_id,
            "name": config["name"],
            "owner_id": member_ids[0],
            "member_ids": member_ids,
            "type": "group",
            "is_dissolved": False,
            "last_message": {
                "created_at": datetime.now(),
                "id": "",
                "type": "",
                "content": "",
                "sender_id": "",
                "sender_username": "",
                "group_id": group_id,
            },
            "created_at": datetime.now() - timedelta(days=random.randint(1, 30)),
            "organization_id": None,
        }

        await db.groups.update_one(
            {"id": group_id},
            {"$set": group},
            upsert=True
        )
        created += 1

    return created


def create_message(
    msg_type: str,
    sender_id: str,
    sender_username: str,
    group_id: str,
    created_at: datetime,
    users: List[Dict],
    user_map: Dict[str, str],
    receiver: List[str] = None,
) -> Dict[str, Any]:
    """创建单条消息"""
    message = {
        "id": f"test-msg-{uuid.uuid4()}",
        "type": msg_type,
        "sender_id": sender_id,
        "sender_username": sender_username,
        "sender_avatar": None,
        "group_id": group_id,
        "receiver": receiver or [],
        "at_list": [],
        "read_list": [],
        "is_revoke": False,
        "is_deleted": False,
        "created_at": created_at,
        "cite": None,
    }

    if msg_type == "text":
        if group_id.startswith("private-"):
            message["content"] = random.choice(PRIVATE_TEXT_SAMPLES)
        else:
            message["content"] = random.choice(TEXT_SAMPLES)
    elif msg_type == "voice":
        message["content"] = "[语音消息]"
        message["duration"] = random.uniform(1, 60)
        message["sound_file_id"] = f"test-voice-{random.randint(1, 100)}"
    elif msg_type == "file":
        message["content"] = f"[文件] 测试文件_{random.randint(1, 100)}.pdf"
    elif msg_type == "at":
        at_user = random.choice(users)
        message["content"] = f"@{at_user['username']} {random.choice(TEXT_SAMPLES)}"
        message["at_list"] = [at_user["id"]]

    return message


async def generate_messages(
    users: List[Dict[str, Any]],
    message_count: int,
    clean: bool = False
) -> Dict[str, int]:
    """生成聊天消息"""
    db = await get_chat_database()

    if clean:
        result = await db.messages.delete_many({
            "sender_id": {"$regex": r"^test-user-"}
        })
        print(f"已删除 {result.deleted_count} 条测试消息")

    # 获取所有群组
    main_db = await get_database()
    groups = await main_db.groups.find({
        "id": {"$regex": r"^test-group-"}
    }).to_list(length=100)
    group_ids = [g["id"] for g in groups]

    user_ids = [u["id"] for u in users]
    user_map = {u["id"]: u["username"] for u in users}

    group_message_count = int(message_count * 0.6)
    private_message_count = message_count - group_message_count

    messages = []
    stats = {"group": 0, "private": 0, "text": 0, "voice": 0, "file": 0, "at": 0}

    # 生成群聊消息
    for _ in range(group_message_count):
        group_id = random.choice(group_ids)
        sender_id = random.choice(user_ids)

        created_at = datetime.now() - timedelta(
            days=random.randint(0, 6),
            hours=random.randint(0, 23),
            minutes=random.randint(0, 59)
        )

        msg_type = random.choices(
            ["text", "voice", "file", "at"],
            weights=[60, 15, 10, 15]
        )[0]

        message = create_message(
            msg_type=msg_type,
            sender_id=sender_id,
            sender_username=user_map[sender_id],
            group_id=group_id,
            created_at=created_at,
            users=users,
            user_map=user_map,
        )

        messages.append(message)
        stats["group"] += 1
        stats[msg_type] += 1

    # 生成私聊消息
    for _ in range(private_message_count):
        sender_id, receiver_id = random.sample(user_ids, 2)
        private_group_id = f"private-{min(sender_id, receiver_id)}-{max(sender_id, receiver_id)}"

        created_at = datetime.now() - timedelta(
            days=random.randint(0, 6),
            hours=random.randint(0, 23),
            minutes=random.randint(0, 59)
        )

        msg_type = random.choices(
            ["text", "voice", "file"],
            weights=[80, 10, 10]
        )[0]

        message = create_message(
            msg_type=msg_type,
            sender_id=sender_id,
            sender_username=user_map[sender_id],
            group_id=private_group_id,
            created_at=created_at,
            receiver=[receiver_id],
            users=users,
            user_map=user_map,
        )

        messages.append(message)
        stats["private"] += 1
        stats[msg_type] += 1

    if messages:
        await db.messages.insert_many(messages)

    return stats


async def main():
    """主函数"""
    args = parse_args()

    print("=== MongoDB 测试数据生成 ===")
    print(f"连接数据库: {args.db_url or settings.DATABASE_URL}")
    print(f"模式: {'清空并重新生成' if args.clean else '追加数据'}")
    print()

    # 生成用户
    print(f"生成用户: {args.users}个...")
    users = generate_users(args.users, args.password)
    inserted = await save_users(users, args.clean)
    print(f"已保存 {inserted} 个用户")
    print()

    # 生成好友关系
    print("生成好友关系...")
    friendship_count = await generate_friendships(users)
    print(f"已生成 {friendship_count} 条好友关系")
    print()

    # 生成群组
    print("生成群组...")
    group_count = await generate_groups(users, args.clean)
    print(f"已创建 {group_count} 个群组")
    print()

    # 生成消息
    print(f"生成消息: {args.messages}条...")
    stats = await generate_messages(users, args.messages, args.clean)
    print(f"已生成消息: 群聊 {stats['group']}条, 私聊 {stats['private']}条")
    print(f"消息类型: 文本 {stats['text']}条, 语音 {stats['voice']}条, 文件 {stats['file']}条, @提及 {stats['at']}条")
    print()

    # 输出统计信息
    print("=" * 50)
    print("数据生成完成!")
    print(f"用户: {args.users}个")
    print(f"群组: {len(GROUP_CONFIGS)}个")
    print(f"消息: {args.messages}条")
    print()

    # 输出测试账号信息
    print("测试账号（密码统一为 123456）:")
    for i, user in enumerate(users[:5]):
        print(f"  {user['username']}: {user['email']}")
    if len(users) > 5:
        print(f"  ... 还有 {len(users) - 5} 个用户")
    print()
    print("使用以下命令登录测试:")
    print("  邮箱: test_zhangsan@example.com")
    print("  密码: 123456")


if __name__ == "__main__":
    asyncio.run(main())