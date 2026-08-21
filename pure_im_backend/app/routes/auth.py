import uuid
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Request
import random
import string

from ..config import settings
from ..database import get_database
from ..models.user import User
from ..schemas.email import EmailContent, PhoneContent, UserSendCodeResponse
from ..schemas.response import error, success
from ..schemas.user import (
    ResetPasswordForm,
    ResetPasswordSendCode,
    UserCreate,
    UserEmailLogin,
    UserLoginResponse,
    UserPhoneLogin,
    UserResponse,
)
from ..utils.security import create_access_token, get_password_hash, verify_password
from ..utils.log import logger
from ..utils.rate_limit import check_rate_limit, record_rate_limit

router = APIRouter()


@router.get("/confirm", description="确认连接")
async def confirm():
    return success(message="通讯成功")


@router.post("/register/send-email-code", description="发送邮箱验证码")
async def send_verification_email_code(
    user_data: EmailContent,
    request: Request,
    db=Depends(get_database),
):
    try:
        # 获取客户端 IP
        client_ip = request.client.host if request.client else "unknown"

        # 频率限制1：同一邮箱60秒内最多发送1次
        allowed, error_msg = await check_rate_limit(
            db=db,
            limit_type="email_code",
            identifier=user_data.email,
            max_requests=1,
            window_seconds=60,
        )
        if not allowed:
            return error(code=429, message=error_msg)

        # 频率限制2：同一 IP 60秒内最多发送5次（防止单 IP 滥用）
        allowed, error_msg = await check_rate_limit(
            db=db,
            limit_type="email_code_ip",
            identifier=client_ip,
            max_requests=5,
            window_seconds=60,
        )
        if not allowed:
            return error(code=429, message=error_msg)

        user = await db.users.find_one({"email": user_data.email, "is_active": True})
        if user:
            return error(code=409, message="邮箱已注册")

        # 生成验证码
        code = "".join(random.choices(string.digits, k=6))

        # 创建临时用户存储验证码
        temp_user = User(
            username="",
            email=user_data.email,
            verification_code=code,
            hashed_password="",
            avatar=None,
        )

        await db.users.insert_one(temp_user.model_dump())

        # TODO: 实际发送邮件（需要配置SMTP）
        logger.info(f"验证码: {code} 已发送到 {user_data.email}")

        # 记录频率限制（邮箱）
        await record_rate_limit(
            db=db,
            limit_type="email_code",
            identifier=user_data.email,
        )

        # 记录频率限制（IP）
        await record_rate_limit(
            db=db,
            limit_type="email_code_ip",
            identifier=client_ip,
        )

        return success(message="验证码已发送")
    except Exception as e:
        logger.error(f"发送验证码出错: {e}")
        return error(code=500, message="发送验证码出错")


@router.post("/send-phone-code", description="发送手机验证码")
async def send_verification_phone_code(
    user_data: PhoneContent,
    request: Request,
    db=Depends(get_database),
):
    try:
        # 获取客户端 IP
        client_ip = request.client.host if request.client else "unknown"

        # 频率限制1：同一手机号60秒内最多发送1次
        allowed, error_msg = await check_rate_limit(
            db=db,
            limit_type="phone_code",
            identifier=user_data.phone,
            max_requests=1,
            window_seconds=60,
        )
        if not allowed:
            return error(code=429, message=error_msg)

        # 频率限制2：同一 IP 60秒内最多发送5次
        allowed, error_msg = await check_rate_limit(
            db=db,
            limit_type="phone_code_ip",
            identifier=client_ip,
            max_requests=5,
            window_seconds=60,
        )
        if not allowed:
            return error(code=429, message=error_msg)

        code = "".join(random.choices(string.digits, k=6))

        user = await db.users.find_one({"phone": user_data.phone, "is_active": True})
        if user:
            await db.users.update_one(
                {"phone": user_data.phone, "id": user["id"]},
                {"$set": {"verification_code": code}},
            )
        else:
            new_user = User(
                username="",
                phone=user_data.phone,
                verification_code=code,
                hashed_password="",
                avatar=None,
            )
            user = new_user.model_dump()
            await db.users.insert_one(user)

        # TODO: 实际发送短信（需要配置短信服务）
        logger.info(f"验证码: {code} 已发送到 {user_data.phone}")

        # 记录频率限制（手机号）
        await record_rate_limit(
            db=db,
            limit_type="phone_code",
            identifier=user_data.phone,
        )

        # 记录频率限制（IP）
        await record_rate_limit(
            db=db,
            limit_type="phone_code_ip",
            identifier=client_ip,
        )

        return success(message="验证码已发送", data=UserSendCodeResponse(**user))
    except Exception as e:
        logger.error(f"发送短信验证码出错: {e}")
        return error(code=500, message="发送验证码出错")


@router.post("/login-phone", description="手机验证码登录")
async def phone_register(
    user_data: UserPhoneLogin,
    db=Depends(get_database),
):
    try:
        user = await db.users.find_one({"id": user_data.id, "is_active": True})

        if not user:
            # 注册新用户
            temp_user = await db.users.find_one({
                "id": user_data.id,
                "phone": user_data.phone,
                "verification_code": user_data.verification_code,
                "is_active": False,
            })

            if not temp_user:
                return error(code=422, message="验证码错误")

            username = f"{user_data.phone}_{temp_user['id'][:4]}"
            user_id = str(uuid.uuid4())

            await db.users.update_one(
                {"_id": temp_user["_id"]},
                {"$set": {
                    "id": user_id,
                    "username": username,
                    "hashed_password": "",
                    "phone": user_data.phone,
                    "is_active": True,
                    "verification_code": None,
                    "friends": [user_id],
                }},
            )

            user = await db.users.find_one({"_id": temp_user["_id"]})

            # 创建默认私聊（可选）
            if user_data.group_id:
                await db.groups.update_one(
                    {"id": user_data.group_id},
                    {"$push": {"member_ids": user_id}},
                )
        else:
            # 已注册用户登录
            user = await db.users.find_one({
                "id": user_data.id,
                "phone": user_data.phone,
                "verification_code": user_data.verification_code,
                "is_active": True,
            })

            if not user:
                return error(code=422, message="验证码错误")

            await db.users.update_one(
                {"id": user_data.id},
                {"$set": {"verification_code": None}}
            )

        access_token = create_access_token(data={"uuid": str(user["id"])})
        user["access_token"] = access_token
        user["token_type"] = "bearer"

        return success(data=UserLoginResponse(**user))
    except Exception as e:
        logger.error(f"手机登录出错: {e}")
        return error(code=500, message="登录出错")


@router.post("/register", description="邮箱注册")
async def email_register(
    user_data: UserCreate,
    db=Depends(get_database),
):
    try:
        # 检查用户名
        existing_username = await db.users.find_one({
            "username": user_data.username,
            "is_active": True,
        })
        if existing_username and existing_username.get("email") != user_data.email:
            return error(code=409, message="用户名已被使用")

        # 检查手机号
        if user_data.phone:
            existing_phone = await db.users.find_one({
                "phone": user_data.phone,
                "is_active": True,
            })
            if existing_phone:
                return error(code=409, message="手机号已注册")

        # 验证验证码
        temp_user = await db.users.find_one({
            "email": user_data.email,
            "verification_code": user_data.verification_code,
            "is_active": False,
        })

        if not temp_user:
            return error(code=422, message="验证码错误")

        user_id = str(uuid.uuid4())

        await db.users.update_one(
            {"_id": temp_user["_id"]},
            {"$set": {
                "id": user_id,
                "username": user_data.username,
                "hashed_password": get_password_hash(user_data.password),
                "phone": user_data.phone,
                "is_active": True,
                "verification_code": None,
                "friends": [user_id],
            }},
        )

        updated_user = await db.users.find_one({"_id": temp_user["_id"]})

        # 群跳转注册
        if user_data.group_id:
            await db.groups.update_one(
                {"id": user_data.group_id},
                {"$push": {"member_ids": user_id}},
            )

        return success(data=UserResponse(**updated_user), message="注册成功")
    except Exception as e:
        logger.error(f"注册出错: {e}")
        return error(code=500, message="注册出错")


@router.post("/login", description="邮箱密码登录")
async def login(user_data: UserEmailLogin, db=Depends(get_database)):
    try:
        user = await db.users.find_one({"email": user_data.email, "is_active": True})

        if not user:
            return error(code=401, message="用户不存在")

        if not verify_password(user_data.password, user["hashed_password"]):
            return error(code=401, message="邮箱或密码错误")

        if not user["is_active"]:
            return error(code=401, message="账号未激活")

        access_token = create_access_token(data={"uuid": str(user["id"])})
        user["access_token"] = access_token
        user["token_type"] = "bearer"

        return success(data=UserLoginResponse(**user).model_dump())
    except Exception as e:
        logger.error(f"登录出错: {e}")
        return error(code=500, message="登录出错")


@router.post("/password/send-code", description="发送密码重置验证码")
async def send_password_reset_code(
    user_data: ResetPasswordSendCode,
    request: Request,
    db=Depends(get_database),
):
    try:
        # 获取客户端 IP
        client_ip = request.client.host if request.client else "unknown"

        # 频率限制1：同一邮箱60秒内最多发送1次
        allowed, error_msg = await check_rate_limit(
            db=db,
            limit_type="password_reset",
            identifier=user_data.email,
            max_requests=1,
            window_seconds=60,
        )
        if not allowed:
            return error(code=429, message=error_msg)

        # 频率限制2：同一 IP 60秒内最多发送5次
        allowed, error_msg = await check_rate_limit(
            db=db,
            limit_type="password_reset_ip",
            identifier=client_ip,
            max_requests=5,
            window_seconds=60,
        )
        if not allowed:
            return error(code=429, message=error_msg)

        user = await db.users.find_one({"email": user_data.email, "is_active": True})
        if not user:
            return error(code=404, message="用户不存在")

        code = "".join(random.choices(string.digits, k=6))

        await db.users.update_one(
            {"email": user_data.email, "is_active": True},
            {"$set": {
                "password_reset_code": code,
                "reset_code_expiry": datetime.now() + timedelta(minutes=5),
            }},
        )

        # TODO: 实际发送邮件
        logger.info(f"重置验证码: {code} 已发送到 {user_data.email}")

        # 记录频率限制（邮箱）
        await record_rate_limit(
            db=db,
            limit_type="password_reset",
            identifier=user_data.email,
        )

        # 记录频率限制（IP）
        await record_rate_limit(
            db=db,
            limit_type="password_reset_ip",
            identifier=client_ip,
        )

        return success(message="验证码已发送")
    except Exception as e:
        logger.error(f"发送重置验证码出错: {e}")
        return error(code=500, message="发送验证码出错")


@router.post("/password/reset", description="重置密码")
async def password_reset(
    reset_data: ResetPasswordForm,
    db=Depends(get_database),
):
    try:
        user = await db.users.find_one({
            "email": reset_data.email,
            "is_active": True,
            "password_reset_code": reset_data.verification_code,
            "reset_code_expiry": {"$gt": datetime.now()},
        })

        if not user:
            return error(code=422, message="验证码错误或已过期")

        await db.users.update_one(
            {"email": reset_data.email, "is_active": True},
            {"$set": {
                "hashed_password": get_password_hash(reset_data.new_password),
                "password_reset_code": None,
                "reset_code_expiry": None,
            }},
        )

        return success(message="密码重置成功")
    except Exception as e:
        logger.error(f"重置密码出错: {e}")
        return error(code=500, message="重置密码出错")
