from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "mongodb://localhost:27017"

    SECRET_KEY: str = "your-secret-key-change-in-production"
    SECRET_ENCRYPTION_KEY: str = "your-32-byte-encryption-key-here"
    SECRET_IV: str = "your-16-byte-iv-here"

    MAX_FILE_SIZE: int = 100 * 1024 * 1024  # 100MB
    ALLOWED_EXTENSIONS: list = [
        # 图片
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp",
        # 文档
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".txt", ".md", ".json", ".csv",
        # 音频
        ".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a",
        # 视频
        ".mp4", ".webm", ".mov", ".avi", ".mkv",
    ]

    OPENAPI_DOCS: bool = True
    DEFAULT_GROUP_NAME: str = "我的消息"
    CORS_ALLOW_ORIGINS: list[str] = ["*"]
    CORS_ALLOW_CREDENTIALS: bool = False

    AI_PROVIDER: str = "openai_compatible"
    AI_BASE_URL: str = ""
    AI_API_KEY: str = ""
    AI_MODEL_NAME: str = ""
    AI_HEALTHCHECK_TIMEOUT: float = 10.0

    # 知识库向量化：本地加载 BGE-M3，同时生成 dense/sparse 表示。
    EMBEDDING_PROVIDER: str = "local_bge_m3"
    BGE_M3_MODEL_NAME: str = "BAAI/bge-m3"
    BGE_M3_DEVICE: str = "auto"
    BGE_M3_USE_FP16: bool = False
    EMBEDDING_BATCH_SIZE: int = 8

    # Milvus 默认连接本机 Docker 暴露的 19530 端口。
    MILVUS_URI: str = "http://127.0.0.1:19530"
    MILVUS_TOKEN: str = ""
    MILVUS_DB_NAME: str = "default"
    MILVUS_FILE_CHUNKS_COLLECTION: str = "file_chunks"
    MILVUS_CHAT_HISTORY_QA_COLLECTION: str = "chat_history_qa"
    MILVUS_CONNECT_TIMEOUT: float = 5.0

    SMTP_SERVER: str = ""
    SMTP_PORT: int = 465
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""

    SMS_API_KEY: str = ""
    SMS_API_URL: str = ""

    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_PASSWORD: str = ""
    REDIS_MESSAGE_CHANNEL: str = "im:message"
    REDIS_USER_STATUS_CHANNEL: str = "im:user_status"
    REDIS_GROUP_CHANNEL_PREFIX: str = "im:group:"
    SERVER_ID: str = "server_1"
    MAX_CONNECTIONS_PER_SERVER: int = 50000

    class Config:
        env_file = ".env"


settings = Settings()
