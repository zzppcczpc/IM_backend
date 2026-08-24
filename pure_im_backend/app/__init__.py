# IM系统 Backend
# 从原DeepTalk项目精简而来，正在逐步迁回AI能力

from .models import user, group, message, file, token_blacklist
from .routes import chat, group_route, user_route, file_route, auth, ai_route
from .schemas import response, user, group, message, email
from .utils import auth as auth_utils, security, log, locales, websocket_manager, file_handler, ai_service
