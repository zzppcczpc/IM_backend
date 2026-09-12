import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ChatHistoryQA(BaseModel):
    """群聊中一次成功完成的 AI 问答记录。"""

    qa_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    group_id: str
    question: str
    answer: str
    user_message_id: str
    ai_message_id: str
    created_at: datetime = Field(default_factory=datetime.now)
