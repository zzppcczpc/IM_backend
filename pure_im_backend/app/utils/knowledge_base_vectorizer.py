from typing import Any

from .embedding_service import embedding_service
from .milvus_service import milvus_service


def build_file_chunk_vector_records(
    chunks: list[dict],
    embeddings: list[Any],
) -> list[dict]:
    if len(chunks) != len(embeddings):
        raise ValueError("Chunk数量和向量数量不一致")

    return [
        {
            "id": chunk["id"],
            "knowledge_base_id": chunk["knowledge_base_id"],
            "file_id": chunk["file_id"],
            "chunk_index": chunk["chunk_index"],
            "content": chunk["content"],
            "metadata_json": chunk.get("metadata") or {},
            "dense_vector": embedding.dense,
            "sparse_vector": embedding.sparse,
        }
        for chunk, embedding in zip(chunks, embeddings)
    ]


def vectorize_and_store_file_chunks(chunks: list[dict]) -> dict:
    """批量生成 Chunk 向量，并以文件为单位覆盖写入 Milvus。"""
    if not chunks:
        raise ValueError("没有可向量化的 Chunk")

    embeddings = embedding_service.encode([chunk["content"] for chunk in chunks])
    milvus_service.ensure_file_chunks_collection(len(embeddings[0].dense))
    records = build_file_chunk_vector_records(chunks, embeddings)
    milvus_service.delete_file_chunks(chunks[0]["file_id"])
    return milvus_service.insert_file_chunks(records)
