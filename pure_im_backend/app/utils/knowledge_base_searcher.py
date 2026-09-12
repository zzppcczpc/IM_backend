from .embedding_service import embedding_service
from .milvus_service import milvus_service


def search_knowledge_base_chunks(
    *,
    knowledge_base_id: str,
    query: str,
    top_k: int = 5,
) -> list[dict]:
    """把用户问题向量化后，到 Milvus 中检索当前知识库的相关 Chunk。"""
    query_embedding = embedding_service.encode([query])[0]
    hits = milvus_service.search_file_chunks(
        knowledge_base_id=knowledge_base_id,
        dense_vector=query_embedding.dense,
        sparse_vector=query_embedding.sparse,
        top_k=top_k,
    )

    chunks = []
    for hit in hits:
        entity = hit["entity"]
        metadata = entity.get("metadata_json") or {}
        chunks.append({
            "chunk_id": entity.get("id", ""),
            "knowledge_base_id": entity.get("knowledge_base_id", knowledge_base_id),
            "file_id": entity.get("file_id", ""),
            "chunk_index": entity.get("chunk_index", 0),
            "filename": metadata.get("filename", ""),
            "content": entity.get("content", ""),
            "score": hit["score"],
            "metadata": metadata,
        })
    return chunks
