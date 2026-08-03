from pydantic import BaseModel
from typing import Optional


class EmailContent(BaseModel):
    email: str


class PhoneContent(BaseModel):
    phone: str


class UserSendCodeResponse(BaseModel):
    id: str
    phone: str
    verification_code: Optional[str] = None