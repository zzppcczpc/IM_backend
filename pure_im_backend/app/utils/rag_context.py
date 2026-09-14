import asyncio
from typing import Any

from .log import logger


def get_group_knowledge_base_ids(group: dict) -> list[str]:
    """读取群聊绑定的知识库 ID，兼容列表字段和旧的单值字段。"""
    raw_ids = group.get("knowledge_base_ids")
    if raw_ids is None:
        raw_ids = group.get("knowledge_base_id")

    if isinstance(raw_ids, str):
        raw_ids = [raw_ids]
    if not isinstance(raw_ids, list):
        return []

    result = []
    for value in raw_ids:
        if isinstance(value, str) and value.strip() and value not in result:
            result.append(value)
    return result


def _source_label(item: dict[str, Any]) -> str:
    metadata = item.get("metadata") or {}
    filename = (
        metadata.get("filename")
        or metadata.get("file_name")
        or item.get("file_id")
        or "未命名文件"
    )
    location = (
        metadata.get("page")
        or metadata.get("page_number")
        or metadata.get("sheet")
        or metadata.get("sheet_name")
    )
    if location is not None and str(location).strip():
        return f"文件：{filename}，位置：{location}"
    return f"文件：{filename}，Chunk：{item.get('chunk_index', 0)}"


def build_rag_prompt(
    question: str,
    chunks: list[dict[str, Any]],
    file_contexts: list[dict[str, Any]] | None = None,
) -> tuple[str, list[dict]]:
    """把知识库 Chunk 和群最近文件整理成带来源编号的 RAG Prompt。"""
    source_lines = []
    citations = []
    index = 0
    for item in file_contexts or []:
        index += 1
        filename = item.get("filename") or "未命名文件"
        is_cited = item.get("priority") == "cited"
        source_type = item.get("source_type", "group_recent_file")
        source_label = (
            "被引用群文件 Chunk（优先参考）"
            if is_cited
            else "群文件检索 Chunk"
            if source_type == "group_file_chunk"
            else "群聊最近文件"
        )
        source_lines.extend([
            f"[{index}] {source_label}：{filename}，Chunk：{item.get('chunk_index', 0)}",
            str(item.get("content") or "").strip(),
            "",
        ])
        citations.append({
            "source_index": index,
            "source_type": source_type,
            "file_id": item.get("file_id", ""),
            "message_id": item.get("message_id", ""),
            "filename": filename,
            "file_type": item.get("file_type", ""),
            "chunk_id": item.get("chunk_id", ""),
            "chunk_index": item.get("chunk_index", 0),
            "uploaded_by": item.get("uploaded_by", ""),
            "uploaded_by_username": item.get("uploaded_by_username", ""),
            "priority": item.get("priority", "recent"),
            "metadata": item.get("metadata") or {},
        })

    for item in chunks:
        index += 1
        source_lines.extend([
            f"[{index}] {_source_label(item)}",
            str(item.get("content") or "").strip(),
            "",
        ])
        metadata = item.get("metadata") or {}
        citations.append({
            "source_index": index,
            "source_type": "knowledge_base_chunk",
            "chunk_id": item.get("chunk_id", ""),
            "knowledge_base_id": item.get("knowledge_base_id", ""),
            "file_id": item.get("file_id", ""),
            "chunk_index": item.get("chunk_index", 0),
            "filename": metadata.get("filename") or metadata.get("file_name") or "",
            "metadata": metadata,
            "rerank_score": item.get("rerank_score"),
        })

    references = (
        "\n".join(source_lines).strip()
        if source_lines
        else "没有检索到与问题直接相关的知识库资料。"
    )
    prompt = f"""你是群聊中的 AI 助手。请根据下面的参考资料回答用户问题。
如果资料中有“被引用文件（优先参考）”，请优先依据它回答。
如果参考资料中没有足够信息，请明确说明资料不足，不要把资料中没有的内容说成确定事实。
回答尽量简洁、准确；如果使用了参考资料，请在对应内容后标注来源编号，例如 [1]。

用户问题：
{question.strip()}

参考资料：
{references}
"""
    return prompt, citations


async def search_group_knowledge_base(
    *,
    manage_db,
    group: dict,
    query: str,
    top_k: int = 5,
) -> list[dict]:
    """直接从 Milvus 检索群绑定知识库的 Chunk。"""
    knowledge_base_ids = get_group_knowledge_base_ids(group)
    if not knowledge_base_ids:
        return []

    from .knowledge_base_searcher import search_knowledge_base_chunks

    try:
        return await asyncio.to_thread(
            search_knowledge_base_chunks,
            knowledge_base_id=knowledge_base_ids,
            query=query,
            top_k=top_k,
        )
    except Exception as exc:
        logger.warning(f"绑定知识库 Milvus 检索失败: {exc}")
        return []
