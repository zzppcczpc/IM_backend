from fastapi import APIRouter

from ..schemas.response import error, success
from ..utils.ai_service import ai_service
from ..utils.log import logger

router = APIRouter()


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
