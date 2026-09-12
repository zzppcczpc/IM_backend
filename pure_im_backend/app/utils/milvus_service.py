from ..config import settings


class MilvusService:
    """Milvus 连接和 file_chunks 集合初始化能力。"""

    def __init__(self):
        self._client = None

    def get_client(self):
        if self._client is None:
            try:
                from pymilvus import MilvusClient
            except ImportError as exc:
                raise RuntimeError(
                    "未安装 pymilvus，请先安装 requirements.txt 中的向量化依赖"
                ) from exc
            kwargs = {"uri": settings.MILVUS_URI}
            if settings.MILVUS_TOKEN:
                kwargs["token"] = settings.MILVUS_TOKEN
            if settings.MILVUS_DB_NAME:
                kwargs["db_name"] = settings.MILVUS_DB_NAME
            self._client = MilvusClient(**kwargs)
        return self._client

    def health_check(self) -> dict:
        data = {
            "uri": settings.MILVUS_URI,
            "database": settings.MILVUS_DB_NAME,
            "collection": settings.MILVUS_FILE_CHUNKS_COLLECTION,
            "available": False,
        }
        try:
            client = self.get_client()
            client.list_collections()
            data["available"] = True
        except Exception as exc:
            data["error"] = str(exc)[:500]
        return data

    def ensure_file_chunks_collection(self, dense_dimension: int) -> dict:
        if dense_dimension <= 0:
            raise ValueError("dense 向量维度必须大于 0")

        try:
            from pymilvus import DataType
        except ImportError as exc:
            raise RuntimeError(
                "未安装 pymilvus，请先安装 requirements.txt 中的向量化依赖"
            ) from exc

        client = self.get_client()
        collection_name = settings.MILVUS_FILE_CHUNKS_COLLECTION
        if client.has_collection(collection_name):
            self._ensure_file_chunk_indexes(client, collection_name)
            return {
                "collection": collection_name,
                "created": False,
                "dense_dimension": dense_dimension,
            }

        schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field(
            field_name="id",
            datatype=DataType.VARCHAR,
            is_primary=True,
            max_length=100,
        )
        schema.add_field(
            field_name="knowledge_base_id",
            datatype=DataType.VARCHAR,
            max_length=100,
        )
        schema.add_field(field_name="file_id", datatype=DataType.VARCHAR, max_length=100)
        schema.add_field(field_name="chunk_index", datatype=DataType.INT64)
        schema.add_field(
            field_name="content",
            datatype=DataType.VARCHAR,
            max_length=65535,
        )
        schema.add_field(
            field_name="metadata_json",
            datatype=DataType.JSON,
        )
        schema.add_field(
            field_name="dense_vector",
            datatype=DataType.FLOAT_VECTOR,
            dim=dense_dimension,
        )
        schema.add_field(
            field_name="sparse_vector",
            datatype=DataType.SPARSE_FLOAT_VECTOR,
        )

        index_params = client.prepare_index_params()
        index_params.add_index(
            field_name="dense_vector",
            index_type="AUTOINDEX",
            metric_type="COSINE",
        )
        index_params.add_index(
            field_name="sparse_vector",
            index_type="AUTOINDEX",
            metric_type="IP",
        )
        client.create_collection(
            collection_name=collection_name,
            schema=schema,
            index_params=index_params,
        )
        return {
            "collection": collection_name,
            "created": True,
            "dense_dimension": dense_dimension,
        }

    @staticmethod
    def _ensure_file_chunk_indexes(client, collection_name: str):
        """兼容需求17已创建但缺少 sparse 索引的旧集合。"""
        dense_indexes = client.list_indexes(collection_name, "dense_vector")
        if not dense_indexes:
            index_params = client.prepare_index_params()
            index_params.add_index(
                field_name="dense_vector",
                index_type="AUTOINDEX",
                metric_type="COSINE",
            )
            client.create_index(collection_name, index_params)

        sparse_indexes = client.list_indexes(collection_name, "sparse_vector")
        if not sparse_indexes:
            index_params = client.prepare_index_params()
            index_params.add_index(
                field_name="sparse_vector",
                index_type="AUTOINDEX",
                metric_type="IP",
            )
            client.create_index(collection_name, index_params)

    def delete_file_chunks(self, file_id: str):
        """删除某个文件旧的向量，保证重新向量化不会产生重复数据。"""
        self.get_client().delete(
            collection_name=settings.MILVUS_FILE_CHUNKS_COLLECTION,
            filter=f'file_id == "{file_id}"',
        )

    def insert_file_chunks(self, records: list[dict]):
        if not records:
            return {"inserted": 0}
        result = self.get_client().insert(
            collection_name=settings.MILVUS_FILE_CHUNKS_COLLECTION,
            data=records,
        )
        return {
            "inserted": result.get("insert_count", len(records)),
            "ids": result.get("ids", []),
        }

    def search_file_chunks(
        self,
        *,
        knowledge_base_id: str,
        dense_vector: list[float],
        sparse_vector: dict[int, float] | None = None,
        top_k: int = 5,
    ) -> list[dict]:
        """在 file_chunks 集合中按知识库范围检索相关 Chunk。"""
        client = self.get_client()
        collection_name = settings.MILVUS_FILE_CHUNKS_COLLECTION
        if not client.has_collection(collection_name):
            raise RuntimeError("file_chunks 集合不存在，请先初始化并完成 Chunk 向量化")

        self._ensure_file_chunk_indexes(client, collection_name)
        client.load_collection(collection_name)
        filter_expr = f'knowledge_base_id == "{knowledge_base_id}"'
        output_fields = [
            "id",
            "knowledge_base_id",
            "file_id",
            "chunk_index",
            "content",
            "metadata_json",
        ]

        hits = self._search_dense_chunks(
            client=client,
            collection_name=collection_name,
            dense_vector=dense_vector,
            filter_expr=filter_expr,
            output_fields=output_fields,
            top_k=top_k,
        )
        if sparse_vector:
            try:
                hits.extend(
                    self._search_sparse_chunks(
                        client=client,
                        collection_name=collection_name,
                        sparse_vector=sparse_vector,
                        filter_expr=filter_expr,
                        output_fields=output_fields,
                        top_k=top_k,
                    )
                )
            except Exception:
                # sparse 检索失败时保留 dense 检索结果，保证接口可用。
                pass

        return self._merge_search_hits(hits, top_k)

    @staticmethod
    def _search_dense_chunks(
        *,
        client,
        collection_name: str,
        dense_vector: list[float],
        filter_expr: str,
        output_fields: list[str],
        top_k: int,
    ) -> list[dict]:
        results = client.search(
            collection_name=collection_name,
            data=[dense_vector],
            anns_field="dense_vector",
            filter=filter_expr,
            limit=top_k,
            output_fields=output_fields,
            search_params={"metric_type": "COSINE"},
        )
        return results[0] if results else []

    @staticmethod
    def _search_sparse_chunks(
        *,
        client,
        collection_name: str,
        sparse_vector: dict[int, float],
        filter_expr: str,
        output_fields: list[str],
        top_k: int,
    ) -> list[dict]:
        results = client.search(
            collection_name=collection_name,
            data=[sparse_vector],
            anns_field="sparse_vector",
            filter=filter_expr,
            limit=top_k,
            output_fields=output_fields,
            search_params={"metric_type": "IP"},
        )
        return results[0] if results else []

    @staticmethod
    #接收多个检索结果，把重复的 Chunk 合并去重，按照相似度排序，最后返回前 top_k 条。
    #理解这个的核心就要了解hits里是长什么样子
    def _merge_search_hits(hits: list[dict], top_k: int) -> list[dict]:
        merged = {}
        for hit in hits:
            entity = hit.get("entity") or {}
            chunk_id = entity.get("id") or hit.get("id")
            if not chunk_id:
                continue
            """
            1. 优先读取 hit["distance"]
            2. 如果没有 distance，就读取 hit["score"]
            3. 如果两个字段都没有，就使用 0
            """
            score = float(hit.get("distance", hit.get("score", 0)) or 0)
            current = merged.get(chunk_id)
            if current is None or score > current["score"]:
                merged[chunk_id] = {"score": score, "entity": entity}
        return sorted(merged.values(), key=lambda item: item["score"], reverse=True)[:top_k]


milvus_service = MilvusService()
