import re
from typing import Any

from rank_bm25 import BM25Okapi


_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")


def tokenize(text: str) -> list[str]:
    """为 rank-bm25 准备中英文混合分词结果。"""
    text = (text or "").lower()
    base_tokens = _TOKEN_PATTERN.findall(text)
    cjk_chars = [char for char in text if "\u4e00" <= char <= "\u9fff"]
    cjk_bigrams = [
        cjk_chars[index] + cjk_chars[index + 1]
        for index in range(len(cjk_chars) - 1)
    ]
    return base_tokens + cjk_bigrams


class BM25Index:
    """项目内 BM25 适配器，具体 BM25 计算交给 rank-bm25。"""

    def __init__(
        self,
        documents: list[dict[str, Any]],
        *,
        id_field: str = "id",
        text_field: str = "content",
        k1: float = 1.5,
        b: float = 0.75,
    ):
        self.documents = documents
        self.id_field = id_field
        self.text_field = text_field
        self._tokenised_documents = [
            tokenize(str(document.get(text_field, "")))
            for document in documents
        ]
        self._index = BM25Okapi(
            self._tokenised_documents,
            k1=k1,
            b=b,
        )

    def search(self, query: str, top_k: int = 20) -> list[dict[str, Any]]:
        if not self.documents:
            return []

        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        scores = self._index.get_scores(query_tokens)
        ranked_indexes = sorted(
            range(len(self.documents)),
            key=lambda index: float(scores[index]),
            reverse=True,
        )
        return [
            {
                "id": self.documents[index].get(self.id_field),
                "score": float(scores[index]),
                "document": self.documents[index],
            }
            for index in ranked_indexes[:top_k]
            if float(scores[index]) > 0
            or any(token in self._tokenised_documents[index] for token in query_tokens)
        ]
