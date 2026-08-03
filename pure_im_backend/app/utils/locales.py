from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


class TranslationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 从请求头获取语言
        lang = request.headers.get("Accept-Language", "zh-CN")
        request.state.lang = lang
        response = await call_next(request)
        return response


def get_translator(request: Request):
    lang = request.state.lang
    return lambda text: text  # 简化版，不做翻译


def get_translator_func(lang: str):
    return lambda text: text  # 简化版，不做翻译