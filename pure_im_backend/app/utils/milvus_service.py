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


milvus_service = MilvusService()
