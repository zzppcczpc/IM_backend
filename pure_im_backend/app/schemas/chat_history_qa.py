from pydantic import BaseModel, Field


class ChatHistoryQASearchRequest(BaseModel):
    group_id: str
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)


class ChatHistoryQASearchItem(BaseModel):
    qa_id: str
    group_id: str
    question: str
    answer: str
    user_message_id: str
    ai_message_id: str
    score: float


class ChatHistoryQASearchResponse(BaseModel):
    query: str
    items: list[ChatHistoryQASearchItem] = Field(default_factory=list)
