import re
from datetime import datetime

from fastapi import APIRouter, Depends

from ..database import get_database
from ..models.ai_call_log import AICallLog
from ..models.user import User
from ..schemas.ai import (
    AIChatRequest,
    AIChatResponse,
    AIModelResponse,
    AIProviderConfigResponse,
    AIUsageStatsResponse,
)
from ..schemas.response import error, success
from ..utils.ai_service import ai_service
from ..utils.auth import get_current_user
from ..utils.log import logger

router = APIRouter()


# 把平台配置转换成公开响应；API Key 永远不返回给前端。
def _platform_config_response():
    config = ai_service.get_default_config()
    return AIProviderConfigResponse(
        provider=config.provider,
        base_url=config.base_url,
        api_key_masked="",
        key_configured=bool(config.api_key),
        selected_model=config.model_name or None,
        created_at="",
        updated_at="",
    ).model_dump()


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


@router.get("/provider-config", description="查询平台AI配置")
async def get_ai_provider_config(current_user: User = Depends(get_current_user)):
    return success(message="平台AI配置读取成功", data=_platform_config_response())


@router.get("/provider-config/models", description="读取平台AI可用模型")
async def list_ai_provider_models(current_user: User = Depends(get_current_user)):
    config = ai_service.get_default_config()
    if not config.configured:
        return error(code=503, message="平台 AI 尚未完成配置")
    result = await ai_service.list_models(config)
    if not result["ok"]:
        return error(code=503, message=result["error"])
    return success(message="模型列表读取成功", data=[AIModelResponse(**item).model_dump() for item in result["data"]])


# 查询当前用户的 AI 调用次数与 token 累计，用于后续用量面板。
@router.get("/usage/stats", description="查询当前用户AI调用与Token统计")
async def get_ai_usage_stats(current_user: User = Depends(get_current_user)):
    # 登录用户只能查看自己的 AI 调用统计，不接收 user_id 参数，避免越权查询。
    return success(message="AI用量统计读取成功", data=await _build_ai_usage_stats(current_user.id))


# 最小 AI 聊天接口：所有用户统一使用平台配置。
@router.post("/chat", description="最小AI聊天接口")
async def ai_chat(chat_data: AIChatRequest, current_user: User = Depends(get_current_user)):
    # 从进入路由开始计时，后续无论成功还是失败都用同一个 started_at 写调用日志。
    started_at = datetime.now()
    model_name = chat_data.model_name
    try:
        config = ai_service.get_default_config()
        model_name = config.model_name
        if not config.configured:
            message = "平台 AI 尚未完成配置，请联系管理员"
            await _record_ai_call_log(
                user_id=current_user.id,
                model_name=model_name,
                success_flag=False,
                started_at=started_at,
                finished_at=datetime.now(),
                error_message=message,
            )
            return error(code=503, message=message)

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
