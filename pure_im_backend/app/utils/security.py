import bcrypt
import base64
import hashlib
import os
from datetime import datetime, timedelta
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from jose import jwt

from ..config import settings

ALGORITHM = "HS256"
API_KEY_PREFIX = "enc:v1:"


# 用项目密钥派生 AES-GCM 密钥，避免要求配置值必须刚好是固定字节长度。
def _api_key_cipher() -> AESGCM:
    key = hashlib.sha256(settings.SECRET_ENCRYPTION_KEY.encode("utf-8")).digest()
    return AESGCM(key)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    password_bytes = plain_password.encode("utf-8")
    hashed_bytes = hashed_password.encode("utf-8")
    try:
        return bcrypt.checkpw(password_bytes, hashed_bytes)
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    password_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode("utf-8")


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=7)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)


# 加密用户自定义模型的 API Key，数据库中只保存密文。
def encrypt_api_key(api_key: str) -> str:
    nonce = os.urandom(12)
    encrypted = _api_key_cipher().encrypt(nonce, api_key.encode("utf-8"), None)
    token = base64.urlsafe_b64encode(nonce + encrypted).decode("utf-8")
    return f"{API_KEY_PREFIX}{token}"


# 解密用户自定义模型的 API Key；兼容早期可能误存的明文值。
def decrypt_api_key(stored_api_key: str) -> str:
    if not stored_api_key.startswith(API_KEY_PREFIX):
        return stored_api_key
    raw = base64.urlsafe_b64decode(stored_api_key[len(API_KEY_PREFIX):].encode("utf-8"))
    nonce = raw[:12]
    encrypted = raw[12:]
    return _api_key_cipher().decrypt(nonce, encrypted, None).decode("utf-8")


# 响应给前端时只显示首尾字符，不能把完整 API Key 返回出去。
def mask_api_key(api_key: str) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "****"
    return f"{api_key[:4]}****{api_key[-4:]}"
