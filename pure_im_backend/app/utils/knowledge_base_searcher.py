from typing import Any

from .embedding_service import embedding_service
from .milvus_service import milvus_service
from .reranker_service import reranker_service


def _hit_to_candidate(hit: dict, default_knowledge_base_id: str) -> dict:
    entity = hit.get("entity") or {}
    return {
        "id": entity.get("id", ""),
        "type": "file_chunk",
        "content": entity.get("content", ""),
        "knowledge_base_id": entity.get(
            "knowledge_base_id",
            default_knowledge_base_id,
        ),
        "file_id": entity.get("file_id", ""),
        "chunk_index": entity.get("chunk_index", 0),
        "metadata": entity.get("metadata_json") or {},
        "score": float(hit.get("score", hit.get("distance", 0)) or 0),
    }


def search_knowledge_base_chunks(
    *,
    knowledge_base_id: str | list[str],
    query: str,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """直接从 Milvus 检索知识库 Chunk，并使用 Reranker 重排。"""
    if isinstance(knowledge_base_id, str):
        knowledge_base_ids = [knowledge_base_id]
    else:
        knowledge_base_ids = [
            value for value in knowledge_base_id
            if isinstance(value, str) and value.strip()
        ]
    if not knowledge_base_ids:
        return []

    query_embedding = embedding_service.encode([query])[0]
    candidate_top_k = max(top_k * 4, 20)
    milvus_scope = (
        knowledge_base_ids[0]
        if len(knowledge_base_ids) == 1
        else knowledge_base_ids
    )
    hits = milvus_service.search_file_chunks(
        knowledge_base_id=milvus_scope,
        dense_vector=query_embedding.dense,
        sparse_vector=query_embedding.sparse,
        top_k=candidate_top_k,
    )

    candidates = [
        _hit_to_candidate(hit, knowledge_base_ids[0])
        for hit in hits
        if (hit.get("entity") or {}).get("id")
    ]
    if not candidates:
        return []

    candidates, reranker_used = reranker_service.rerank(
        query=query,
        candidates=candidates,
        top_n=top_k,
    )
    return [
        {
            "chunk_id": item["id"],
            "knowledge_base_id": item.get(
                "knowledge_base_id",
                knowledge_base_ids[0],
            ),
            "file_id": item.get("file_id", ""),
            "chunk_index": item.get("chunk_index", 0),
            "filename": (item.get("metadata") or {}).get("filename", ""),
            "content": item.get("content", ""),
            "score": item.get("score", 0),
            "rerank_score": item.get("rerank_score"),
            "reranked": reranker_used,
            "retrieval": "milvus_hybrid",
            "metadata": item.get("metadata") or {},
        }
        for item in candidates
    ]
