from .embedding_service import embedding_service
from .milvus_service import milvus_service


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
    top_k: int = 5,
) -> list[dict]:
    """将问题向量化，只检索指定群聊的历史 QA。"""
    embedding = embedding_service.encode([query.strip()])[0]
    hits = milvus_service.search_chat_history_qa(
        group_id=group_id,
        dense_vector=embedding.dense,
        sparse_vector=embedding.sparse,
        top_k=top_k,
    )

    items = []
    for hit in hits:
        entity = hit.get("entity") or {}
        items.append({
            "qa_id": entity.get("qa_id", ""),
            "group_id": entity.get("group_id", group_id),
            "question": entity.get("question", ""),
            "answer": entity.get("answer", ""),
            "user_message_id": entity.get("user_message_id", ""),
            "ai_message_id": entity.get("ai_message_id", ""),
            "score": hit.get("score", 0),
        })
    return items
