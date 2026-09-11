import re


DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 150


def split_text(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    """按字符长度切分文本，并保留相邻 Chunk 的重叠内容。"""
    if chunk_size <= 0:
        raise ValueError("chunk_size 必须大于 0")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap 必须大于等于 0 且小于 chunk_size")

    #把不同操作系统的换行符统一为\n，并去除首尾空白字符
    normalized = re.sub(r"\r\n?", "\n", text or "").strip()
    if not normalized:
        return []

    chunks = []
    start = 0
    text_length = len(normalized)
    step = chunk_size - chunk_overlap
    while start < text_length:
        end = min(start + chunk_size, text_length)
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= text_length:
            break
        start += step
    return chunks
