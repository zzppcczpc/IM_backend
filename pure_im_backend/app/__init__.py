# 纯IM系统 Backend
# 从原DeepTalk项目精简而来，去除了所有AI相关功能

from .models import user, group, message, file, token_blacklist
from .routes import chat, group_route, user_route, file_route, auth
from .schemas import response, user, group, message, email
from .utils import auth as auth_utils, security, log, locales, websocket_manager, file_handler