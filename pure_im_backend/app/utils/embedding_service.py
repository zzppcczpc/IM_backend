from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from ..config import settings


@dataclass
class EmbeddingResult:
    dense: list[float]
    sparse: dict[int, float]


class EmbeddingService:
    """BGE-M3 向量服务：按需加载模型，提供单条和批量 embedding。"""

    def __init__(self):
        self._model = None

    def _load_model(self):
        if self._model is not None:
            return self._model

        if settings.EMBEDDING_PROVIDER != "local_bge_m3":
            raise RuntimeError(
                f"暂不支持的 Embedding 提供方: {settings.EMBEDDING_PROVIDER}"
            )

        try:
            from FlagEmbedding import BGEM3FlagModel
        except ImportError as exc:
            raise RuntimeError(
                "未安装 FlagEmbedding，请先安装 requirements.txt 中的向量化依赖"
            ) from exc

        device = None if settings.BGE_M3_DEVICE == "auto" else settings.BGE_M3_DEVICE
        kwargs = {"use_fp16": settings.BGE_M3_USE_FP16}
        if device:
            kwargs["devices"] = device
        self._model = BGEM3FlagModel(settings.BGE_M3_MODEL_NAME, **kwargs)
        return self._model

    def encode(self, texts: list[str]) -> list[EmbeddingResult]:
        if not texts:
            return []
        clean_texts = [text.strip() for text in texts]
        if any(not text for text in clean_texts):
            raise ValueError("Embedding文本不能为空")

        model = self._load_model()
        output = model.encode(
            clean_texts,
            batch_size=settings.EMBEDDING_BATCH_SIZE,
            max_length=8192,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
        )
        dense_vectors = output.get("dense_vecs")
        sparse_vectors = output.get("lexical_weights")
        if dense_vectors is None or sparse_vectors is None:
            raise RuntimeError("BGE-M3没有返回完整的 dense/sparse 向量")

        return [
            EmbeddingResult(
                dense=[float(value) for value in dense_vectors[index]],
                sparse=self._normalise_sparse(sparse_vectors[index]),
            )
            for index in range(len(clean_texts))
        ]

    @staticmethod
    def _normalise_sparse(value: Any) -> dict[int, float]:
        if hasattr(value, "items"):
            return {
                int(key): float(weight)
                for key, weight in value.items()
                if float(weight) != 0
            }
        raise RuntimeError("BGE-M3返回的 sparse 向量格式无法识别")

    async def health_check(self) -> dict:
        data = {
            "provider": settings.EMBEDDING_PROVIDER,
            "model_name": settings.BGE_M3_MODEL_NAME,
            "device": settings.BGE_M3_DEVICE,
            "configured": bool(settings.BGE_M3_MODEL_NAME),
            "available": False,
        }
        if not data["configured"]:
            data["error"] = "BGE_M3_MODEL_NAME 未配置"
            return data
        try:
            result = self.encode(["向量化健康检查"])
            data["available"] = bool(result and result[0].dense)
            data["dense_dimension"] = len(result[0].dense)
            data["sparse_terms"] = len(result[0].sparse)
        except Exception as exc:
            data["error"] = str(exc)[:500]
        return data


embedding_service = EmbeddingService()
