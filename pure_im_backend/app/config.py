from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "mongodb://localhost:27017"

    SECRET_KEY: str = "your-secret-key-change-in-production"
    SECRET_ENCRYPTION_KEY: str = "your-32-byte-encryption-key-here"
    SECRET_IV: str = "your-16-byte-iv-here"

    MAX_FILE_SIZE: int = 10 * 1024 * 1024
    ALLOWED_EXTENSIONS: list = [
        ".png", ".jpg", ".jpeg", ".gif",
        ".pdf", ".doc", ".docx", ".xls", ".xlsx",
        ".txt", ".md", ".json", ".csv",
        ".mp3", ".mp4", ".wav", ".ogg", ".webm",
    ]

    OPENAPI_DOCS: bool = True
    DEFAULT_GROUP_NAME: str = "我的消息"
    CORS_ALLOW_ORIGINS: list[str] = ["*"]
    CORS_ALLOW_CREDENTIALS: bool = False

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