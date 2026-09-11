from fastapi import APIRouter

from ..schemas.response import error, success
from ..utils.embedding_service import embedding_service
from ..utils.log import logger
from ..utils.milvus_service import milvus_service

router = APIRouter()


@router.get("/embedding/health", description="Embedding服务健康检查")
async def embedding_health_check():
    try:
        data = await embedding_service.health_check()
        if not data["available"]:
            return error(code=503, message=data.get("error", "Embedding服务不可用"), data=data)
        return success(message="Embedding服务可用", data=data)
    except Exception as exc:
        logger.error(f"Embedding健康检查失败: {exc}", exc_info=True)
        return error(code=500, message="Embedding健康检查失败")


@router.post("/embedding/test", description="测试文本Embedding")
async def embedding_test(data: dict):
    texts = data.get("texts")
    if isinstance(texts, str):
        texts = [texts]
    if not isinstance(texts, list) or not texts:
        return error(code=400, message="texts 必须是非空字符串或字符串数组")
    if not all(isinstance(text, str) for text in texts):
        return error(code=400, message="texts 中每一项都必须是字符串")
    try:
        results = embedding_service.encode(texts)
        return success(
            message="Embedding生成成功",
            data={
                "count": len(results),
                "items": [
                    {
                        "dense_dimension": len(item.dense),
                        "dense": item.dense,
                        "sparse": item.sparse,
                    }
                    for item in results
                ],
            },
        )
    except ValueError as exc:
        return error(code=400, message=str(exc))
    except Exception as exc:
        logger.error(f"Embedding生成失败: {exc}", exc_info=True)
        return error(code=503, message="Embedding生成失败，请检查模型和依赖配置")


@router.get("/milvus/health", description="Milvus健康检查")
async def milvus_health_check():
    data = milvus_service.health_check()
    if not data["available"]:
        return error(code=503, message=data.get("error", "Milvus不可用"), data=data)
    return success(message="Milvus可用", data=data)


@router.post("/milvus/file-chunks/initialize", description="初始化文件Chunk向量集合")
async def initialize_file_chunks_collection():
    try:
        embedding_health = await embedding_service.health_check()
        if not embedding_health["available"]:
            return error(
                code=503,
                message="Embedding不可用，无法确定 dense 向量维度",
                data=embedding_health,
            )
        data = milvus_service.ensure_file_chunks_collection(
            embedding_health["dense_dimension"]
        )
        return success(message="file_chunks集合初始化成功", data=data)
    except Exception as exc:
        logger.error(f"Milvus集合初始化失败: {exc}", exc_info=True)
        return error(code=503, message="file_chunks集合初始化失败，请检查Milvus配置")
