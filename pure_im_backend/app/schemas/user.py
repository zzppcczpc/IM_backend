from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str
    phone: Optional[str] = None
    verification_code: str
    group_id: Optional[str] = None


class UserEmailLogin(BaseModel):
    email: str
    password: str


class UserPhoneLogin(BaseModel):
    id: str
    phone: str
    verification_code: str
    group_id: Optional[str] = None


class UserLoginResponse(BaseModel):
    id: str
    username: str
    email: Optional[str] = None
    phone: Optional[str] = None
    avatar: Optional[str] = None
    is_active: bool
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    username: str
    email: Optional[str] = None
    phone: Optional[str] = None
    avatar: Optional[str] = None
    is_active: bool
    created_at: Optional[datetime] = None
    is_friend: Optional[bool] = False


class UserUpdate(BaseModel):
    username: str
    phone: Optional[str] = None


class UserSearch(BaseModel):
    id: Optional[str] = None
    username: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None


class UserQuery(BaseModel):
    query_str: str


class UserFriendRequest(BaseModel):
    request_type: str  # from 或 to
    user_id: str
    username: str
    avatar: Optional[str] = None
    status: str  # pending, accepted, rejected, sended
    created_at: str
    handled_at: Optional[str] = None


class UserFriendRequestResponse(BaseModel):
    request_type: str
    user_id: str
    username: str
    avatar: Optional[str] = None
    status: str
    created_at: str
    handled_at: Optional[str] = None


class UserFriendHandle(BaseModel):
    friend_id: str
    action: str  # accept 或 reject


class SearchFriend(BaseModel):
    search: Optional[str] = None
    page: int = 1
    page_size: int = 10


class ResetPasswordSendCode(BaseModel):
    email: str


class ResetPasswordForm(BaseModel):
    email: str
    verification_code: str
    new_password: str