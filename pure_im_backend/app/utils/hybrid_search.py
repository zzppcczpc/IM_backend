from typing import Any


def rrf_fuse(
    *,
    bm25_results: list[dict[str, Any]],
    dense_results: list[dict[str, Any]],
    top_k: int = 5,
    rrf_k: int = 60,
) -> list[dict[str, Any]]:
    """按独立排名使用 RRF 融合 BM25 与 Dense 结果。"""
    merged: dict[str, dict[str, Any]] = {}

    for channel, results in (
        ("bm25", bm25_results),
        ("dense", dense_results),
    ):
        for rank, item in enumerate(results, start=1):
            result_id = str(item.get("id") or "")
            if not result_id:
                continue

            current = merged.setdefault(
                result_id,
                {
                    "id": result_id,
                    "type": item.get("type", ""),
                    "content": item.get("content", ""),
                    "metadata": item.get("metadata") or {},
                    "rrf_score": 0.0,
                    "retrieval_ranks": {},
                    "retrieval_scores": {},
                },
            )
            current["rrf_score"] += 1 / (rrf_k + rank)
            current["retrieval_ranks"][channel] = rank
            current["retrieval_scores"][channel] = float(item.get("score", 0) or 0)

            for field in (
                "type",
                "content",
                "metadata",
                "group_id",
                "knowledge_base_id",
                "file_id",
                "chunk_index",
                "question",
                "answer",
                "user_message_id",
                "ai_message_id",
            ):
                if field in item and not current.get(field):
                    current[field] = item[field]

    fused = sorted(
        merged.values(),
        key=lambda item: item["rrf_score"],
        reverse=True,
    )[:top_k]
    for item in fused:
        channels = set(item["retrieval_ranks"])
        item["score"] = item["rrf_score"]
        item["retrieval"] = (
            "hybrid"
            if len(channels) > 1
            else next(iter(channels), "none")
        )
    return fused
