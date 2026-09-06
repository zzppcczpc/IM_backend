from datetime import datetime

from fastapi import APIRouter, Depends

from ..database import get_database
from ..models.user import AIProviderConfig, User
from ..schemas.ai import (
    AIChatRequest,
    AIChatResponse,
    AIModelResponse,
    AIProviderConfigRequest,
    AIProviderConfigResponse,
    AISelectedModelRequest,
)
from ..schemas.response import error, success
from ..utils.ai_service import AIModelConfig, ai_service
from ..utils.auth import get_current_user
from ..utils.log import logger
from ..utils.security import decrypt_api_key, encrypt_api_key, mask_api_key

router = APIRouter()


# 读取当前用户保存的 AI 接入配置；老用户没有该字段时返回 None。
def _get_provider_config(user_doc: dict) -> dict | None:
    user_setting = user_doc.get("user_setting") or {}
    return user_setting.get("ai_provider_config")


# 把数据库中的接入配置转换成安全响应，api_key 只返回脱敏值。
def _provider_config_response(provider_config: dict | None):
    if not provider_config:
        return None

    stored_key = provider_config.get("api_key") or ""
    try:
        plain_key = decrypt_api_key(stored_key) if stored_key else ""
    except Exception:
        plain_key = ""

    return AIProviderConfigResponse(
        provider=provider_config.get("provider", "openai_compatible"),
        base_url=provider_config.get("base_url", ""),
        api_key_masked=mask_api_key(plain_key),
        key_configured=bool(stored_key),
        selected_model=provider_config.get("selected_model"),
        created_at=str(provider_config.get("created_at") or ""),
        updated_at=str(provider_config.get("updated_at") or ""),
    ).model_dump()


# 保存或覆盖当前用户的 AI 接入配置；这是一个用户维度配置，不再按模型做 CRUD。
async def _save_provider_config(user_id: str, provider_config: dict):
    db = await get_database()
    await db.users.update_one(
        {"id": user_id},
        {"$set": {"user_setting.ai_provider_config": provider_config}},
    )


# 解密用户保存的 API Key；解密失败通常说明旧数据不可用，需要用户重新保存配置。
def _decrypt_provider_api_key(provider_config: dict) -> tuple[str | None, str | None]:
    try:
        return decrypt_api_key(provider_config.get("api_key") or ""), None
    except Exception:
        return None, "AI API Key 解密失败，请重新保存接口配置"


# 把保存的接口配置组装成运行时配置；拉模型列表只需要 provider/base_url/api_key。
def _build_provider_config(provider_config: dict) -> tuple[AIModelConfig | None, str | None]:
    if not provider_config:
        return None, "请先保存 AI 接口配置"

    api_key, key_error = _decrypt_provider_api_key(provider_config)
    if key_error:
        return None, key_error

    return ai_service.build_user_config(provider_config, api_key or "", ""), None


# 把保存的接口配置和当前选择的模型名组装成聊天可调用配置。
def _build_chat_config(provider_config: dict, model_name: str) -> tuple[AIModelConfig | None, str | None]:
    if not provider_config:
        return None, "请先保存 AI 接口配置"
    if not model_name:
        return None, "请先选择一个可用模型"

    api_key, key_error = _decrypt_provider_api_key(provider_config)
    if key_error:
        return None, key_error

    return ai_service.build_user_config(provider_config, api_key or "", model_name), None


# AI 服务健康检查接口：路由层只负责组织响应格式，具体检查逻辑放在 ai_service 中。
@router.get("/health", description="AI服务健康检查")
async def ai_health_check(probe: bool = False):
    try:
        data = await ai_service.health_check(probe=probe)
        if not data["configured"]:
            return error(code=503, message=data["error"], data=data)
        if not data["available"]:
            return error(code=503, message=data.get("error", "AI服务不可用"), data=data)
        return success(message="AI服务可用", data=data)
    except Exception as exc:
        logger.error(f"AI健康检查失败: {exc}", exc_info=True)
        return error(code=500, message="AI健康检查失败")


# 查看当前默认 AI 配置的公开信息，用于确认 .env 是否被正确读取；不会返回 api_key。
@router.get("/config", description="查看默认AI配置")
async def ai_config():
    config = ai_service.get_default_config()
    data = config.public_dict()
    return success(message="AI配置读取成功", data=data)


# 查询当前用户保存的 AI 接入配置；不会返回明文 api_key。
@router.get("/provider-config", description="查询用户AI接口配置")
async def get_ai_provider_config(current_user: User = Depends(get_current_user)):
    db = await get_database()
    user_doc = await db.users.find_one({"id": current_user.id})
    if not user_doc:
        return error(code=401, message="用户不存在或未登录")
    return success(message="AI接口配置读取成功", data=_provider_config_response(_get_provider_config(user_doc)))


# 保存当前用户的 AI 接口配置；前端只需要传 provider、base_url、api_key。
@router.post("/provider-config", description="保存用户AI接口配置")
async def save_ai_provider_config(config_data: AIProviderConfigRequest, current_user: User = Depends(get_current_user)):
    if config_data.provider != "openai_compatible":
        return error(code=400, message=f"暂不支持的AI服务提供方: {config_data.provider}")

    db = await get_database()
    user_doc = await db.users.find_one({"id": current_user.id})
    if not user_doc:
        return error(code=401, message="用户不存在或未登录")

    old_config = _get_provider_config(user_doc) or {}
    now = datetime.now()
    provider_config = AIProviderConfig(
        provider=config_data.provider,
        base_url=config_data.base_url.rstrip("/"),
        api_key=encrypt_api_key(config_data.api_key),
        selected_model=config_data.selected_model or old_config.get("selected_model"),
        created_at=old_config.get("created_at") or now,
        updated_at=now,
    ).model_dump()
    await _save_provider_config(current_user.id, provider_config)
    return success(message="AI接口配置保存成功", data=_provider_config_response(provider_config))


# 根据当前用户保存的 base_url 和 api_key，从模型服务读取可用模型列表。
@router.get("/provider-config/models", description="读取用户AI接口可用模型")
async def list_ai_provider_models(current_user: User = Depends(get_current_user)):
    db = await get_database()
    user_doc = await db.users.find_one({"id": current_user.id})
    if not user_doc:
        return error(code=401, message="用户不存在或未登录")

    provider_config = _get_provider_config(user_doc)
    config, build_error = _build_provider_config(provider_config)
    if build_error:
        return error(code=400, message=build_error)

    result = await ai_service.list_models(config)
    if not result["ok"]:
        return error(code=503, message=result["error"])
    return success(message="模型列表读取成功", data=[AIModelResponse(**item).model_dump() for item in result["data"]])


# 保存当前用户选中的模型；切换模型时调用，不需要重新提交 API Key。
@router.post("/provider-config/selected-model", description="保存用户当前选中的AI模型")
async def save_selected_ai_model(model_data: AISelectedModelRequest, current_user: User = Depends(get_current_user)):
    db = await get_database()
    user_doc = await db.users.find_one({"id": current_user.id})
    if not user_doc:
        return error(code=401, message="用户不存在或未登录")

    provider_config = _get_provider_config(user_doc)
    if not provider_config:
        return error(code=400, message="请先保存 AI 接口配置")

    provider_config["selected_model"] = model_data.model_name
    provider_config["updated_at"] = datetime.now()
    await _save_provider_config(current_user.id, provider_config)
    return success(message="当前模型已保存", data=_provider_config_response(provider_config))


# 最小 AI 聊天接口：用当前用户保存的接口配置和前端选择的模型名调用模型。
@router.post("/chat", description="最小AI聊天接口")
async def ai_chat(chat_data: AIChatRequest, current_user: User = Depends(get_current_user)):
    try:
        db = await get_database()
        user_doc = await db.users.find_one({"id": current_user.id})
        if not user_doc:
            return error(code=401, message="用户不存在或未登录")

        provider_config = _get_provider_config(user_doc)
        model_name = chat_data.model_name or (provider_config or {}).get("selected_model")
        config, build_error = _build_chat_config(provider_config, model_name)
        if build_error:
            return error(code=400, message=build_error)

        if chat_data.model_name and chat_data.model_name != provider_config.get("selected_model"):
            provider_config["selected_model"] = chat_data.model_name
            provider_config["updated_at"] = datetime.now()
            await _save_provider_config(current_user.id, provider_config)

        result = await ai_service.chat(
            message=chat_data.message,
            temperature=chat_data.temperature if chat_data.temperature is not None else 0.7,
            max_tokens=chat_data.max_tokens if chat_data.max_tokens is not None else 1024,
            config=config,
        )
        if not result["ok"]:
            return error(code=503, message=result["error"], data=result.get("data"))
        return success(message="生成成功", data=AIChatResponse(**result["data"]).model_dump())
    except Exception as exc:
        logger.error(f"AI聊天接口失败: {exc}", exc_info=True)
        return error(code=500, message="AI聊天接口失败")
