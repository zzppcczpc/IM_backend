from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)


class KnowledgeBaseUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=2000)


class KnowledgeBaseResponse(BaseModel):
    id: str
    name: str
    description: str = ""
    owner_id: str
    member_ids: list[str] = Field(default_factory=list)
    file_count: int = 0
    created_at: datetime
    updated_at: datetime


class KnowledgeBaseFileResponse(BaseModel):
    id: str
    knowledge_base_id: str
    owner_id: str
    file_name: str
    file_type: str
    file_extension: str
    file_size: int
    status: str
    error_message: Optional[str] = None
    parsed_text: Optional[str] = None
    parse_metadata: dict = Field(default_factory=dict)
    chunk_count: int = 0
    vector_error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class KnowledgeBaseChunkResponse(BaseModel):
    id: str
    knowledge_base_id: str
    file_id: str
    chunk_index: int
    content: str
    metadata: dict = Field(default_factory=dict)
    created_at: datetime


class KnowledgeBaseSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)


class KnowledgeBaseSearchChunk(BaseModel):
    chunk_id: str
    knowledge_base_id: str
    file_id: str
    chunk_index: int
    filename: str = ""
    content: str
    score: float
    rrf_score: float = 0
    retrieval: str = "hybrid"
    retrieval_ranks: dict[str, int] = Field(default_factory=dict)
    retrieval_scores: dict[str, float] = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)


class KnowledgeBaseSearchResponse(BaseModel):
    query: str
    chunks: list[KnowledgeBaseSearchChunk] = Field(default_factory=list)

