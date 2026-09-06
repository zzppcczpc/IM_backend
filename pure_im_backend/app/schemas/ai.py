from typing import Optional

from pydantic import BaseModel, Field


class AIChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="用户输入的问题")
    model_name: Optional[str] = Field(default=None, description="从当前接口配置拉取到的模型名称")
    temperature: Optional[float] = Field(default=None, ge=0, le=2)
    max_tokens: Optional[int] = Field(default=None, ge=1, le=8192)


class AIChatResponse(BaseModel):
    source: Optional[str] = None
    model: str
    content: str
    usage: Optional[dict] = None


class AIProviderConfigRequest(BaseModel):
    provider: str = Field(default="openai_compatible")
    base_url: str = Field(..., min_length=1)
    api_key: str = Field(..., min_length=1)
    selected_model: Optional[str] = None


class AIProviderConfigResponse(BaseModel):
    provider: str
    base_url: str
    api_key_masked: str
    key_configured: bool
    selected_model: Optional[str] = None
    created_at: str
    updated_at: str


class AISelectedModelRequest(BaseModel):
    model_name: str = Field(..., min_length=1, description="当前用户选中的模型名称")


class AIModelResponse(BaseModel):
    id: str
    name: str
