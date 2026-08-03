from pydantic import BaseModel
from typing import Optional, Any


class success(BaseModel):
    code: int = 200
    message: str = "成功"
    data: Optional[Any] = None


class error(BaseModel):
    code: int = 500
    message: str = "失败"
    data: Optional[Any] = None


class PaginationModel(BaseModel):
    total: int
    page: int
    page_size: int
    items: list
    start_index: Optional[str] = None