import os
import re
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.docs import get_swagger_ui_html

from .config import settings
from .utils.log import logger
from .utils.locales import TranslationMiddleware

app = FastAPI(
    title="Pure IM Backend",
    description="纯IM系统后端 - WebSocket实时聊天",
    version="1.0.0",
    docs_url="/docs" if settings.OPENAPI_DOCS else None,
    redoc_url="/redoc" if settings.OPENAPI_DOCS else None,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOW_ORIGINS,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 国际化
app.add_middleware(TranslationMiddleware)

# 安全扫描拦截
SCANNER_PATTERNS = [
    r"nikto", r"acunetix", r"sqlmap", r"nmap", r"dirb",
    r"wpscan", r"\/\.env", r"\/\.git", r"\/wp\-admin"
]


@app.middleware("http")
async def block_scanners(request: Request, call_next):
    user_agent = request.headers.get("user-agent", "").lower()
    path = request.url.path.lower()

    if any(
        re.search(pattern, user_agent) or re.search(pattern, path)
        for pattern in SCANNER_PATTERNS
    ):
        logger.info(f"BLOCKED: {request.client.host} - {user_agent}")
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Forbidden")

    return await call_next(request)


def create_routes():
    from .routes import auth, chat, group_route, user_route, file_route

    app.include_router(auth.router, prefix="/api/auth", tags=["认证"])
    app.include_router(chat.router, prefix="/api/chat", tags=["聊天"])
    app.include_router(group_route.router, prefix="/api/group", tags=["群组"])
    app.include_router(user_route.router, prefix="/api/user", tags=["用户"])
    app.include_router(file_route.router, prefix="/api/files", tags=["文件"])


create_routes()


@app.on_event("startup")
async def init_test_data_on_startup():
    from .utils.init_data import ensure_test_data

    await ensure_test_data()

# 静态文件
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")


# 根路径
@app.get("/")
async def root():
    return {
        "message": "Pure IM Backend API",
        "version": "1.0.0",
        "docs": "/docs",
        "features": [
            "WebSocket实时聊天",
            "多人同时在线",
            "多设备登录",
            "消息撤回/删除",
            "在线状态显示",
            "离线消息补发",
            "好友系统",
            "群组管理"
        ]
    }


# 健康检查
@app.get("/health")
async def health_check():
    from .utils.websocket_manager import connection_manager
    stats = connection_manager.get_stats()
    return {
        "status": "healthy",
        "websocket_stats": stats
    }

"""
11111111

"""


"""

112222222
"""