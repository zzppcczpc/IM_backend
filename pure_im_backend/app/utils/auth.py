from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from ..config import settings
from ..database import get_database
from ..models.user import User
from ..utils.security import ALGORITHM

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login")


async def get_current_user(token: str = Depends(oauth2_scheme)):
    db = await get_database()
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无效的认证凭据",
        headers={"WWW-Authenticate": "Bearer"},
    )
    """在准备认证流程，先拿 token、连数据库、准备好认证失败时返回的 401 错误。返回的是查询到的用户信息"""
    # 检查token是否在黑名单中
    blacklist_token = await db.token_blacklist.find_one({"token": token})
    if blacklist_token:
        raise credentials_exception

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("uuid")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = await db.users.find_one({"id": user_id, "is_active": True})
    if user is None:
        raise credentials_exception
    return User(**user)