from .bm25 import BM25Index
from .embedding_service import embedding_service
from .hybrid_search import rrf_fuse
from .milvus_service import milvus_service
from .reranker_service import reranker_service


def search_knowledge_base_chunks(
    *,
    knowledge_base_id: str,
    query: str,
    chunks: list[dict],
    top_k: int = 5,
    rrf_k: int = 60,
) -> list[dict]:
    """使用 BM25 + Dense，并通过 RRF 融合知识库 Chunk。"""
    documents = [
        {
            "id": chunk["id"],
            "knowledge_base_id": chunk["knowledge_base_id"],
            "file_id": chunk["file_id"],
            "chunk_index": chunk["chunk_index"],
            "content": chunk.get("content", ""),
            "metadata": chunk.get("metadata") or {},
        }
        for chunk in chunks
    ]
    bm25_hits = BM25Index(documents).search(query, top_k=max(top_k * 4, 20))
    bm25_results = [
        {
            "id": hit["id"],
            "type": "file_chunk",
            "content": hit["document"]["content"],
            "knowledge_base_id": hit["document"]["knowledge_base_id"],
            "file_id": hit["document"]["file_id"],
            "chunk_index": hit["document"]["chunk_index"],
            "metadata": hit["document"]["metadata"],
            "score": hit["score"],
        }
        for hit in bm25_hits
    ]

    dense_results = []
    try:
        query_embedding = embedding_service.encode([query])[0]
        hits = milvus_service.search_file_chunks_dense(
            knowledge_base_id=knowledge_base_id,
            dense_vector=query_embedding.dense,
            top_k=max(top_k * 4, 20),
        )
        for hit in hits:
            entity = hit["entity"]
            dense_results.append({
                "id": entity.get("id", ""),
                "type": "file_chunk",
                "content": entity.get("content", ""),
                "knowledge_base_id": entity.get(
                    "knowledge_base_id",
                    knowledge_base_id,
                ),
                "file_id": entity.get("file_id", ""),
                "chunk_index": entity.get("chunk_index", 0),
                "metadata": entity.get("metadata_json") or {},
                "score": hit["score"],
            })
    except Exception:
        dense_results = []

    fused = rrf_fuse(
        bm25_results=bm25_results,
        dense_results=dense_results,
        top_k=top_k,
        rrf_k=rrf_k,
    )
    fused, reranker_used = reranker_service.rerank(
        query=query,
        candidates=fused,
        top_n=top_k,
    )
    return [
        {
            "chunk_id": item["id"],
            "knowledge_base_id": item.get(
                "knowledge_base_id",
                knowledge_base_id,
            ),
            "file_id": item.get("file_id", ""),
            "chunk_index": item.get("chunk_index", 0),
            "filename": (item.get("metadata") or {}).get("filename", ""),
            "content": item.get("content", ""),
            "score": item["score"],
            "rrf_score": item["rrf_score"],
            "retrieval": item["retrieval"],
            "retrieval_ranks": item["retrieval_ranks"],
            "retrieval_scores": item["retrieval_scores"],
            "rerank_score": item.get("rerank_score"),
            "reranked": reranker_used,
            "metadata": item.get("metadata") or {},
        }
        for item in fused
    ]
