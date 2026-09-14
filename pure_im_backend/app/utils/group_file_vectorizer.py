import asyncio
import os
from datetime import datetime

from ..models.group_file_chunk import GroupFileChunk
from .embedding_service import embedding_service
from .group_recent_files import get_message_file_id, update_recent_file_status
from .knowledge_base_chunker import split_text
from .knowledge_base_parser import parse_knowledge_base_file
from .knowledge_base_vectorizer import vectorize_and_store_file_chunks
from .log import logger
from .milvus_service import milvus_service
from .multimodal_text_extractor import (
    extract_multimodal_file,
    is_multimodal_extension,
)
from .reranker_service import reranker_service


GROUP_FILE_SCOPE_PREFIX = "group:"


def group_file_scope(group_id: str) -> str:
    """将群文件映射到现有 file_chunks 集合的独立检索范围。"""
    return f"{GROUP_FILE_SCOPE_PREFIX}{group_id}"


def _file_extension(file_record: dict) -> str:
    filename = file_record.get("file_name") or ""
    return os.path.splitext(filename)[1].lower()


async def process_group_file(file_id: str, group_id: str, manage_db):
    """后台完成群文件解析、切分、向量化和状态更新。"""
    file_record = await manage_db.files.find_one({
        "id": file_id,
        "group_id": group_id,
        "is_deleted": False,
    })
    if not file_record:
        return

    extension = _file_extension(file_record)
    multimodal = is_multimodal_extension(extension)
    path = file_record.get("local_file_path")
    if extension not in {
        ".pdf", ".docx", ".pptx", ".xlsx", ".csv", ".txt", ".md",
        ".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a",
        ".png", ".jpg", ".jpeg", ".webp", ".bmp",
    }:
        await manage_db.files.update_one(
            {"id": file_id},
            {"$set": {
                "parse_status": "unsupported",
                "parse_error": f"暂不支持解析文件类型: {extension or 'unknown'}",
                "vector_error": None,
                "extraction_status": "not_required",
                "updated_at": datetime.now(),
            }},
        )
        await update_recent_file_status(
            manage_db,
            group_id,
            file_id,
            status="unsupported",
        )
        return

    await manage_db.files.update_one(
        {"id": file_id},
        {"$set": {
            "parse_status": "parsing",
            "parse_error": None,
            "vector_error": None,
            "extraction_type": None,
            "extraction_status": "processing" if multimodal else "not_required",
            "extraction_error": None,
            "extraction_metadata": {},
            "updated_at": datetime.now(),
        }},
    )
    await update_recent_file_status(
        manage_db,
        group_id,
        file_id,
        status="parsing",
        extraction_error="",
    )

    try:
        if not path or not os.path.isfile(path):
            raise FileNotFoundError("文件存储路径不存在")

        if multimodal:
            text, parse_metadata = await asyncio.to_thread(
                extract_multimodal_file,
                path,
                extension,
            )
        else:
            text, parse_metadata = await asyncio.to_thread(
                parse_knowledge_base_file,
                path,
                extension,
            )
        await manage_db.files.update_one(
            {"id": file_id},
            {"$set": {
                "parse_status": "chunking",
                "parsed_text": text,
                "parse_metadata": parse_metadata,
                "extraction_type": parse_metadata.get("extraction_type"),
                "extraction_status": "success" if multimodal else "not_required",
                "extraction_error": None,
                "extraction_metadata": parse_metadata if multimodal else {},
                "parsed_at": datetime.now(),
                "updated_at": datetime.now(),
            }},
        )
        await update_recent_file_status(
            manage_db,
            group_id,
            file_id,
            status="chunking",
            extraction_type=parse_metadata.get("extraction_type"),
        )

        chunks = split_text(text)
        if not chunks:
            raise ValueError("解析结果无法生成有效 Chunk")

        chunk_documents = [
            GroupFileChunk(
                group_id=group_id,
                file_id=file_id,
                chunk_index=index,
                content=chunk,
                metadata={
                    "filename": file_record.get("file_name", ""),
                    "file_extension": extension,
                    "source_type": "group_file",
                    "group_id": group_id,
                    **parse_metadata,
                },
            ).model_dump()
            for index, chunk in enumerate(chunks)
        ]
        await manage_db.group_file_chunks.delete_many({"file_id": file_id})
        await manage_db.group_file_chunks.insert_many(chunk_documents)

        await manage_db.files.update_one(
            {"id": file_id},
            {"$set": {
                "parse_status": "vectorizing",
                "chunk_count": len(chunk_documents),
                "updated_at": datetime.now(),
            }},
        )
        await update_recent_file_status(
            manage_db,
            group_id,
            file_id,
            status="vectorizing",
            chunk_count=len(chunk_documents),
        )

        vector_documents = [
            {
                **chunk,
                "knowledge_base_id": group_file_scope(group_id),
            }
            for chunk in chunk_documents
        ]
        await asyncio.to_thread(
            vectorize_and_store_file_chunks,
            vector_documents,
        )
    except Exception as exc:
        logger.error(f"群文件处理失败: {file_id}, {exc}", exc_info=True)
        await manage_db.files.update_one(
            {"id": file_id},
            {"$set": {
                "parse_status": "failed",
                "parse_error": str(exc)[:1000],
                "vector_error": str(exc)[:1000],
                "extraction_status": "failed" if multimodal else "not_required",
                "extraction_error": str(exc)[:1000] if multimodal else None,
                "updated_at": datetime.now(),
            }},
        )
        await update_recent_file_status(
            manage_db,
            group_id,
            file_id,
            status="failed",
            extraction_error=str(exc)[:1000] if multimodal else None,
        )
        return

    await manage_db.files.update_one(
        {"id": file_id},
        {"$set": {
            "parse_status": "success",
            "parse_error": None,
            "vector_error": None,
            "updated_at": datetime.now(),
        }},
    )
    await update_recent_file_status(
        manage_db,
        group_id,
        file_id,
        status="success",
        chunk_count=len(chunk_documents),
        extraction_type=parse_metadata.get("extraction_type"),
        extraction_error="",
    )


def _hit_to_candidate(hit: dict, group_id: str, priority: str = "recent") -> dict:
    entity = hit.get("entity") or {}
    return {
        "id": entity.get("id", ""),
        "type": "group_file_chunk",
        "content": entity.get("content", ""),
        "knowledge_base_id": entity.get(
            "knowledge_base_id",
            group_file_scope(group_id),
        ),
        "file_id": entity.get("file_id", ""),
        "chunk_index": entity.get("chunk_index", 0),
        "metadata": entity.get("metadata_json") or {},
        "score": float(hit.get("distance", hit.get("score", 0)) or 0),
        "priority": priority,
    }


def search_group_file_chunks(
    *,
    group_id: str,
    query: str,
    cited_file_id: str | None = None,
    include_group_files: bool = True,
    top_k: int = 5,
) -> list[dict]:
    """直接在 Milvus 中检索群文件 Chunk，不读取 MongoDB 全量 Chunk。"""
    embedding = embedding_service.encode([query])[0]
    candidate_top_k = max(top_k * 4, 20)

    cited_hits = []
    if cited_file_id:
        cited_hits = milvus_service.search_file_chunks(
            knowledge_base_id=group_file_scope(group_id),
            file_id=cited_file_id,
            dense_vector=embedding.dense,
            sparse_vector=embedding.sparse,
            top_k=candidate_top_k,
        )

    # 引用文件时只使用被引用文件，不再把群里的其他文件带入上下文。
    all_hits = []
    if include_group_files and not cited_file_id:
        all_hits = milvus_service.search_file_chunks(
            knowledge_base_id=group_file_scope(group_id),
            dense_vector=embedding.dense,
            sparse_vector=embedding.sparse,
            top_k=candidate_top_k,
        )

    cited_ids = {
        (hit.get("entity") or {}).get("id")
        for hit in cited_hits
    }
    candidates = [
        _hit_to_candidate(hit, group_id, "cited")
        for hit in cited_hits
        if (hit.get("entity") or {}).get("id")
    ]
    candidates.extend(
        _hit_to_candidate(hit, group_id, "recent")
        for hit in all_hits
        if (hit.get("entity") or {}).get("id")
        and (hit.get("entity") or {}).get("id") not in cited_ids
    )
    if not candidates:
        return []

    cited_candidates = [item for item in candidates if item["priority"] == "cited"]
    other_candidates = [item for item in candidates if item["priority"] != "cited"]
    cited_results, reranker_used = reranker_service.rerank(
        query=query,
        candidates=cited_candidates,
        top_n=min(3, top_k),
    )
    other_results, other_reranker_used = reranker_service.rerank(
        query=query,
        candidates=other_candidates,
        top_n=top_k,
    )
    reranker_used = reranker_used or other_reranker_used

    results = []
    seen_ids = set()
    for item in [*cited_results, *other_results]:
        if item["id"] in seen_ids:
            continue
        seen_ids.add(item["id"])
        results.append({
            "chunk_id": item["id"],
            "knowledge_base_id": item["knowledge_base_id"],
            "file_id": item["file_id"],
            "chunk_index": item["chunk_index"],
            "filename": (item["metadata"] or {}).get("filename", ""),
            "content": item["content"],
            "score": item["score"],
            "rerank_score": item.get("rerank_score"),
            "reranked": reranker_used,
            "retrieval": "milvus_hybrid",
            "priority": item["priority"],
            "metadata": item["metadata"],
            "source_type": "group_file_chunk",
        })
        if len(results) >= top_k:
            break
    return results


async def search_group_file_context(
    *,
    group_id: str,
    query: str,
    user_message: dict | object,
    chat_db,
    include_group_files: bool = True,
    top_k: int = 5,
) -> list[dict]:
    """读取引用消息中的文件 ID，并按引用优先检索群文件。"""
    cite = (
        user_message.get("cite")
        if isinstance(user_message, dict)
        else getattr(user_message, "cite", None)
    )
    cite_id = (
        cite.get("id")
        if isinstance(cite, dict)
        else getattr(cite, "id", None)
    )
    cited_file_id = None
    if cite_id:
        group_collection = getattr(chat_db, group_id)
        cited_message = await group_collection.find_one({"id": cite_id})
        cited_file_id = get_message_file_id(cited_message)

    return await asyncio.to_thread(
        search_group_file_chunks,
        group_id=group_id,
        query=query,
        cited_file_id=cited_file_id,
        include_group_files=include_group_files,
        top_k=top_k,
    )
