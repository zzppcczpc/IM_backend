from typing import Any

from ..config import settings
from .log import logger


class RerankerService:
    """可选的 BGE Cross-Encoder 重排服务。"""

    def __init__(self):
        self._model = None

    def _load_model(self):
        if self._model is not None:
            return self._model
        if not settings.RERANKER_ENABLED:
            raise RuntimeError("Reranker 已关闭")

        try:
            from FlagEmbedding import FlagReranker
        except ImportError as exc:
            raise RuntimeError("当前环境未安装 FlagEmbedding") from exc

        kwargs = {
            "query_max_length": settings.RERANKER_QUERY_MAX_LENGTH,
            "max_length": settings.RERANKER_PASSAGE_MAX_LENGTH,
            "use_fp16": settings.RERANKER_USE_FP16,
        }
        if settings.RERANKER_DEVICE != "auto":
            kwargs["devices"] = settings.RERANKER_DEVICE

        self._model = FlagReranker(
            settings.RERANKER_MODEL_NAME,
            **kwargs,
        )
        return self._model

    @staticmethod
    def _candidate_text(candidate: dict[str, Any]) -> str:
        if candidate.get("rerank_content"):
            return str(candidate["rerank_content"])
        if candidate.get("content"):
            return str(candidate["content"])
        if candidate.get("question") or candidate.get("answer"):
            return (
                f"问题：{candidate.get('question', '')}\n"
                f"答案：{candidate.get('answer', '')}"
            )
        return ""

    def rerank(
        self,
        *,
        query: str,
        candidates: list[dict[str, Any]],
        top_n: int,
    ) -> tuple[list[dict[str, Any]], bool]:
        """返回重排后的结果和是否实际使用了 Reranker。"""
        if not candidates or top_n <= 0:
            return [], False

        try:
            model = self._load_model()
            pairs = [
                [query, self._candidate_text(candidate)]
                for candidate in candidates
            ]
            scores = model.compute_score(pairs, normalize=True)
            if hasattr(scores, "tolist"):
                scores = scores.tolist()
            if not isinstance(scores, (list, tuple)):
                scores = [scores]
            if len(scores) != len(candidates):
                raise RuntimeError("Reranker 返回结果数量不匹配")

            reranked = []
            for candidate, score in zip(candidates, scores):
                item = dict(candidate)
                item["rerank_score"] = float(score)
                reranked.append(item)
            reranked.sort(
                key=lambda item: item["rerank_score"],
                reverse=True,
            )
            return reranked[:top_n], True
        except Exception as exc:
            logger.warning(f"Reranker 不可用，保留 RRF 排序: {exc}")
            fallback = []
            for candidate in candidates[:top_n]:
                item = dict(candidate)
                item["rerank_score"] = None
                fallback.append(item)
            return fallback, False


reranker_service = RerankerService()
