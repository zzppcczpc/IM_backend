import re
from datetime import datetime

from fastapi import APIRouter, Depends

from ..database import get_database
from ..models.ai_call_log import AICallLog
from ..models.user import AIProviderConfig, User
from ..schemas.ai import (
    AIChatRequest,
    AIChatResponse,
    AIModelResponse,
    AIProviderConfigRequest,
    AIProviderConfigResponse,
    AISelectedModelRequest,
    AIUsageStatsResponse,
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


def _usage_token_value(usage: dict | None, *keys: str) -> int:
    # 不同 OpenAI-compatible 服务商的 usage 字段命名可能不一致，这里做兼容读取。
    if not isinstance(usage, dict):
        return 0
    for key in keys:
        value = usage.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
    return 0


def _sanitize_log_error(message: str | None) -> str | None:
    # 日志可用于排错，但不能把 Authorization 或 API Key 明文落库。
    if not message:
        return None
    safe_message = re.sub(r"Bearer\s+[^\s,;]+", "Bearer ***", message, flags=re.IGNORECASE)
    safe_message = re.sub(r"sk-[A-Za-z0-9_\-]{8,}", "sk-***", safe_message)
    return safe_message[:500]


async def _record_ai_call_log(
    *,
    user_id: str,
    model_name: str | None,
    success_flag: bool,
    started_at: datetime,
    finished_at: datetime,
    usage: dict | None = None,
    error_message: str | None = None,
):
    # 需求4核心写入点：每次 AI 调用都落一条明细日志，成功/失败都记录。
    prompt_tokens = _usage_token_value(usage, "prompt_tokens", "input_tokens")
    completion_tokens = _usage_token_value(usage, "completion_tokens", "output_tokens")
    total_tokens = _usage_token_value(usage, "total_tokens") or prompt_tokens + completion_tokens

    log_doc = AICallLog(
        user_id=user_id,
        model_id=model_name,
        model_name=model_name,
        success=success_flag,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        error_message=_sanitize_log_error(error_message),
        started_at=started_at,
        finished_at=finished_at,
    ).model_dump()

    try:
        db = await get_database()
        await db.ai_call_logs.insert_one(log_doc)
        if total_tokens > 0:
            # 用户表保留一份累计 token，方便后续做用户用量额度或面板展示。
            await db.users.update_one(
                {"id": user_id},
                {"$inc": {"user_service.token_usage": total_tokens}},
            )
    except Exception as exc:
        logger.error(f"AI调用日志写入失败: {exc}", exc_info=True)


async def _build_ai_usage_stats(user_id: str) -> dict:
    db = await get_database()
    # 需求4统计读取点：按当前用户过滤，再按模型聚合调用次数和 token 消耗。
    pipeline = [
        {"$match": {"user_id": user_id}},
        {
            "$group": {
                "_id": "$model_name",
                "total_calls": {"$sum": 1},
                "success_calls": {"$sum": {"$cond": ["$success", 1, 0]}},
                "failed_calls": {"$sum": {"$cond": ["$success", 0, 1]}},
                "prompt_tokens": {"$sum": "$prompt_tokens"},
                "completion_tokens": {"$sum": "$completion_tokens"},
                "total_tokens": {"$sum": "$total_tokens"},
            }
        },
        {"$sort": {"total_tokens": -1, "total_calls": -1}},
    ]
    model_stats = await db.ai_call_logs.aggregate(pipeline).to_list(None)
    models = [
        {
            "model_name": item.get("_id") or "unknown",
            "total_calls": item.get("total_calls", 0),
            "success_calls": item.get("success_calls", 0),
            "failed_calls": item.get("failed_calls", 0),
            "prompt_tokens": item.get("prompt_tokens", 0),
            "completion_tokens": item.get("completion_tokens", 0),
            "total_tokens": item.get("total_tokens", 0),
        }
        for item in model_stats
    ]
    return AIUsageStatsResponse(
        user_id=user_id,
        total_calls=sum(item["total_calls"] for item in models),
        success_calls=sum(item["success_calls"] for item in models),
        failed_calls=sum(item["failed_calls"] for item in models),
        prompt_tokens=sum(item["prompt_tokens"] for item in models),
        completion_tokens=sum(item["completion_tokens"] for item in models),
        total_tokens=sum(item["total_tokens"] for item in models),
        models=models,
    ).model_dump()


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


# 查询当前用户的 AI 调用次数与 token 累计，用于后续用量面板。
@router.get("/usage/stats", description="查询当前用户AI调用与Token统计")
async def get_ai_usage_stats(current_user: User = Depends(get_current_user)):
    # 登录用户只能查看自己的 AI 调用统计，不接收 user_id 参数，避免越权查询。
    return success(message="AI用量统计读取成功", data=await _build_ai_usage_stats(current_user.id))


# 最小 AI 聊天接口：用当前用户保存的接口配置和前端选择的模型名调用模型。
@router.post("/chat", description="最小AI聊天接口")
async def ai_chat(chat_data: AIChatRequest, current_user: User = Depends(get_current_user)):
    # 从进入路由开始计时，后续无论成功还是失败都用同一个 started_at 写调用日志。
    started_at = datetime.now()
    model_name = chat_data.model_name
    try:
        db = await get_database()
        user_doc = await db.users.find_one({"id": current_user.id})
        if not user_doc:
            message = "用户不存在或未登录"
            # 异常分支也写日志，保证失败调用能进入需求4的失败次数统计。
            await _record_ai_call_log(
                user_id=current_user.id,
                model_name=model_name,
                success_flag=False,
                started_at=started_at,
                finished_at=datetime.now(),
                error_message=message,
            )
            return error(code=401, message=message)

        provider_config = _get_provider_config(user_doc)
        # 本次请求指定模型优先；否则使用用户上次保存的 selected_model。
        model_name = chat_data.model_name or (provider_config or {}).get("selected_model")
        config, build_error = _build_chat_config(provider_config, model_name)
        if build_error:
            # 配置缺失、模型未选择、API Key 解密失败等都按失败调用记录。
            await _record_ai_call_log(
                user_id=current_user.id,
                model_name=model_name,
                success_flag=False,
                started_at=started_at,
                finished_at=datetime.now(),
                error_message=build_error,
            )
            return error(code=400, message=build_error)

        if chat_data.model_name and chat_data.model_name != provider_config.get("selected_model"):
            provider_config["selected_model"] = chat_data.model_name
            provider_config["updated_at"] = datetime.now()
            await _save_provider_config(current_user.id, provider_config)

        # 真正的模型请求在 ai_service.chat 中完成；usage 是后续 token 统计的数据来源。
        result = await ai_service.chat(
            message=chat_data.message,
            temperature=chat_data.temperature if chat_data.temperature is not None else 0.7,
            max_tokens=chat_data.max_tokens if chat_data.max_tokens is not None else 1024,
            config=config,
        )
        if not result["ok"]:
            # 第三方模型接口返回错误或网络失败时，写失败日志并保留安全处理后的错误信息。
            await _record_ai_call_log(
                user_id=current_user.id,
                model_name=model_name,
                success_flag=False,
                started_at=started_at,
                finished_at=datetime.now(),
                error_message=result["error"],
            )
            return error(code=503, message=result["error"], data=result.get("data"))
        response_data = AIChatResponse(**result["data"]).model_dump()
        # 成功分支写入 token 明细，并同步累加 users.user_service.token_usage。
        await _record_ai_call_log(
            user_id=current_user.id,
            model_name=response_data.get("model") or model_name,
            success_flag=True,
            started_at=started_at,
            finished_at=datetime.now(),
            usage=response_data.get("usage"),
        )
        return success(message="生成成功", data=response_data)
    except Exception as exc:
        logger.error(f"AI聊天接口失败: {exc}", exc_info=True)
        # 兜底异常同样落失败日志，避免接口 500 时统计链路断档。
        await _record_ai_call_log(
            user_id=current_user.id,
            model_name=model_name,
            success_flag=False,
            started_at=started_at,
            finished_at=datetime.now(),
            error_message=str(exc)[:500] or "AI聊天接口失败",
        )
        return error(code=500, message="AI聊天接口失败")
