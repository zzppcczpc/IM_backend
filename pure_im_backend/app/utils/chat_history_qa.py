from .bm25 import BM25Index
from .embedding_service import embedding_service
from .hybrid_search import rrf_fuse
from .milvus_service import milvus_service
from .reranker_service import reranker_service


def build_chat_history_qa_vector_record(qa: dict, embedding) -> dict:
    return {
        "qa_id": qa["qa_id"],
        "group_id": qa["group_id"],
        "question": qa["question"],
        "answer": qa["answer"],
        "user_message_id": qa["user_message_id"],
        "ai_message_id": qa["ai_message_id"],
        "dense_vector": embedding.dense,
        "sparse_vector": embedding.sparse,
    }


def vectorize_and_store_chat_history_qa(qa: dict) -> dict:
    """将一条群聊历史 QA 的问题向量化并写入 Milvus。"""
    question = (qa.get("question") or "").strip()
    if not question:
        raise ValueError("历史 QA 的问题不能为空")

    embedding = embedding_service.encode([question])[0]
    milvus_service.ensure_chat_history_qa_collection(len(embedding.dense))
    record = build_chat_history_qa_vector_record(qa, embedding)
    milvus_service.delete_chat_history_qa(qa["qa_id"])
    return milvus_service.insert_chat_history_qa([record])


def search_chat_history_qa(
    *,
    group_id: str,
    query: str,
    qa_records: list[dict],
    top_k: int = 5,
    rrf_k: int = 60,
) -> list[dict]:
    """使用 BM25 + Dense，并通过 RRF 融合群聊历史 QA。"""
    documents = [
        {
            "qa_id": qa["qa_id"],
            "group_id": qa["group_id"],
            "question": qa.get("question", ""),
            "answer": qa.get("answer", ""),
            "user_message_id": qa["user_message_id"],
            "ai_message_id": qa["ai_message_id"],
        }
        for qa in qa_records
    ]
    bm25_documents = [
        {
            **document,
            "content": document["question"],
        }
        for document in documents
    ]
    bm25_hits = BM25Index(
        bm25_documents,
        id_field="qa_id",
        text_field="content",
    ).search(query, top_k=max(top_k * 4, 20))
    bm25_results = [
        {
            "id": hit["id"],
            "type": "chat_history",
            "question": hit["document"]["question"],
            "answer": hit["document"]["answer"],
            "group_id": hit["document"]["group_id"],
            "user_message_id": hit["document"]["user_message_id"],
            "ai_message_id": hit["document"]["ai_message_id"],
            "content": hit["document"]["answer"],
            "score": hit["score"],
        }
        for hit in bm25_hits
    ]

    dense_results = []
    try:
        query_embedding = embedding_service.encode([query])[0]
        hits = milvus_service.search_chat_history_qa_dense(
            group_id=group_id,
            dense_vector=query_embedding.dense,
            top_k=max(top_k * 4, 20),
        )
        for hit in hits:
            entity = hit["entity"]
            dense_results.append({
                "id": entity.get("qa_id", ""),
                "type": "chat_history",
                "question": entity.get("question", ""),
                "answer": entity.get("answer", ""),
                "group_id": entity.get("group_id", group_id),
                "user_message_id": entity.get("user_message_id", ""),
                "ai_message_id": entity.get("ai_message_id", ""),
                "content": entity.get("answer", ""),
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
    for item in fused:
        item["rerank_content"] = (
            f"问题：{item.get('question', '')}\n"
            f"答案：{item.get('answer', '')}"
        )
    fused, reranker_used = reranker_service.rerank(
        query=query,
        candidates=fused,
        top_n=top_k,
    )
    return [
        {
            "qa_id": item["id"],
            "group_id": item.get("group_id", group_id),
            "question": item.get("question", ""),
            "answer": item.get("answer", ""),
            "user_message_id": item.get("user_message_id", ""),
            "ai_message_id": item.get("ai_message_id", ""),
            "score": item["score"],
            "rrf_score": item["rrf_score"],
            "retrieval": item["retrieval"],
            "retrieval_ranks": item["retrieval_ranks"],
            "retrieval_scores": item["retrieval_scores"],
            "rerank_score": item.get("rerank_score"),
            "reranked": reranker_used,
        }
        for item in fused
    ]
