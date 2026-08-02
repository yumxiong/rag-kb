"""
向量存储管理模块
"""

import logging
import uuid
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.config import Settings as ChromaSettings
from langchain_chroma import Chroma
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings

from app.core.cached_embeddings import CachedEmbeddings
from app.core.config import settings

logger = logging.getLogger(__name__)


class VectorStore:
    """向量存储管理类（单例模式）"""

    _instance = None
    _lock = None

    def __new__(cls):
        if cls._instance is None:
            import threading

            if cls._lock is None:
                cls._lock = threading.Lock()
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(VectorStore, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        # 只在第一次初始化时设置属性
        if not hasattr(self, "embeddings"):
            self.embeddings = None
            self.vectorstore = None
            self.chroma_client = None
            self.collection_name = "rag_documents"
            self._initialized = False

    def _ensure_initialized(self):
        """确保实例已初始化（延迟初始化）"""
        if not self._initialized:
            with self._lock:  # 添加线程锁保护
                if not self._initialized:
                    self._initialize_embeddings()
                    self._initialize_vectorstore()
                    self._initialized = True

    def _initialize_embeddings(self):
        """初始化嵌入模型"""
        try:
            # 获取嵌入模型的API key
            api_key = settings.get_embedding_api_key()
            if not api_key:
                raise ValueError(
                    "API key not configured for embedding provider: "
                    f"{settings.embedding_provider}"
                )

            # 获取模型配置
            model_config = settings.get_model_config()
            embedding_api_url = model_config.get("embedding_api_base_url")

            provider = model_config.get("embedding_provider")
            model_name = model_config["embedding_model"]

            if provider == "qwen":
                # 使用原生 DashScopeEmbeddings，避免兼容模式在 /embeddings 的参数不一致
                try:
                    # 优先通过参数传入 Key；若版本不支持该参数，则回退到环境变量
                    try:
                        base_embeddings = DashScopeEmbeddings(
                            model=model_name, dashscope_api_key=api_key
                        )
                    except TypeError:
                        import os

                        os.environ.setdefault("DASHSCOPE_API_KEY", api_key)
                        base_embeddings = DashScopeEmbeddings(model=model_name)
                except Exception as e:
                    logger.error(f"Failed to initialize DashScopeEmbeddings: {e}")
                    raise
            else:
                # 使用 OpenAIEmbeddings（支持 OpenAI 兼容 API）
                embedding_kwargs = {
                    "api_key": api_key,
                    "model": model_name,
                }
                embedding_api_url = model_config.get("embedding_api_base_url")
                if (
                    embedding_api_url
                    and embedding_api_url != "https://api.openai.com/v1"
                ):
                    embedding_kwargs["base_url"] = embedding_api_url
                    embedding_kwargs["organization"] = ""
                base_embeddings = OpenAIEmbeddings(**embedding_kwargs)

            # 使用缓存包装器
            base = (embedding_api_url or "https://api.openai.com/v1").rstrip("/")
            self.embeddings = CachedEmbeddings(
                base_embeddings=base_embeddings,
                model_name=f"{provider}/{model_name}@{base}",
            )

            logger.info(
                "Cached embeddings model initialized successfully: "
                f"{provider}/{model_name}"
            )

        except Exception as e:
            logger.error(f"Error initializing embeddings: {str(e)}")
            raise

    def _initialize_vectorstore(self):
        """初始化向量存储"""
        try:
            # 配置ChromaDB
            chroma_settings = ChromaSettings(
                persist_directory=settings.chroma_db_path,
                anonymized_telemetry=False,
                allow_reset=True,
            )

            # 使用直接的client_settings方式初始化Langchain的Chroma包装器
            self.vectorstore = Chroma(
                collection_name=self.collection_name,
                embedding_function=self.embeddings,
                persist_directory=settings.chroma_db_path,
                client_settings=chroma_settings,
            )

            # 获取底层的chroma_client用于直接操作
            self.chroma_client = self.vectorstore._client

            logger.info("Vector store initialized successfully")

        except Exception as e:
            logger.error(f"Error initializing vector store: {str(e)}")
            raise

    def _ensure_chroma_client_only(self):
        """仅初始化Chroma客户端（不初始化嵌入模型），用于轻量级元数据查询"""
        if self.chroma_client is not None:
            return
        try:
            # 直接使用持久化客户端，避免LangChain封装与embeddings初始化
            self.chroma_client = chromadb.PersistentClient(path=settings.chroma_db_path)
            # 确保集合存在
            try:
                self.chroma_client.get_collection(self.collection_name)
            except Exception:
                self.chroma_client.create_collection(self.collection_name)
            logger.debug("Chroma client (lightweight) initialized")
        except Exception as e:
            logger.error(f"Error initializing lightweight Chroma client: {str(e)}")
            # 兜底：如果轻量初始化失败，回退到完整初始化
            self._ensure_initialized()

    def add_documents(self, documents: List[Document]) -> List[str]:
        """添加文档到向量存储"""
        self._ensure_initialized()
        try:
            if not documents:
                logger.warning("No documents to add")
                return []

            # 为文档生成ID
            doc_ids = []
            for doc in documents:
                if "chunk_id" not in doc.metadata:
                    doc.metadata["chunk_id"] = str(uuid.uuid4())
                doc_ids.append(doc.metadata["chunk_id"])

            # 尝试批量添加
            try:
                self.vectorstore.add_documents(documents, ids=doc_ids)
                # 在新版本 langchain-chroma 中不再需要 persist()；为兼容老版本做条件调用
                try:
                    if hasattr(self.vectorstore, "persist"):
                        self.vectorstore.persist()
                except Exception:
                    logger.debug(
                        "Vector store persist() not supported; "
                        "skipping explicit persist"
                    )
                logger.info(
                    f"Added {len(documents)} documents to vector store (batch mode)"
                )
                return doc_ids
            except Exception as batch_error:
                logger.warning(f"Batch processing failed: {str(batch_error)}")
                logger.info("Falling back to individual document processing...")

                # 回退到逐个处理模式
                successful_ids = []
                for i, doc in enumerate(documents):
                    try:
                        doc_id = doc_ids[i]
                        self.vectorstore.add_documents([doc], ids=[doc_id])
                        successful_ids.append(doc_id)
                        logger.debug(
                            f"Successfully added document {i+1}/{len(documents)}"
                        )
                    except Exception as individual_error:
                        logger.error(
                            f"Failed to add document {i+1}: {str(individual_error)}"
                        )
                        continue

                # 持久化所有成功的文档（新版本无需，保留兼容）
                if successful_ids:
                    try:
                        if hasattr(self.vectorstore, "persist"):
                            self.vectorstore.persist()
                    except Exception:
                        logger.debug(
                            "Vector store persist() not supported; "
                            "skipping explicit persist"
                        )
                    logger.info(
                        f"Added {len(successful_ids)}/{len(documents)} documents "
                        "to vector store (individual mode)"
                    )
                    return successful_ids
                else:
                    raise Exception("Failed to add any documents to vector store")

        except Exception as e:
            logger.error(f"Error adding documents to vector store: {str(e)}")
            raise

    def similarity_search(
        self, query: str, k: int = 4, filter_dict: Optional[Dict] = None
    ) -> List[Document]:
        """执行相似度搜索"""
        self._ensure_initialized()
        try:
            results = self.vectorstore.similarity_search(
                query=query, k=k, filter=filter_dict
            )

            logger.info(f"Found {len(results)} similar documents for query")
            return results

        except Exception as e:
            logger.error(f"Error in similarity search: {str(e)}")
            raise

    def similarity_search_with_score(
        self,
        query: str,
        k: int = 4,
        filter_dict: Optional[Dict] = None,
        threshold: Optional[float] = None,
    ) -> List[tuple]:
        """执行带分数的相似度搜索
        返回 (Document, distance) 列表，并按给定阈值（或默认阈值）过滤。
        注意：Chroma 返回的是距离（distance），越小越相似。
        """
        self._ensure_initialized()
        try:
            results = self.vectorstore.similarity_search_with_score(
                query=query, k=k, filter=filter_dict
            )

            # 选择阈值：未指定时使用全局默认相似度阈值
            effective_threshold = (
                settings.similarity_threshold if threshold is None else threshold
            )
            # 过滤：保留距离小于等于阈值的结果
            filtered_results = [
                (doc, score) for doc, score in results if score <= effective_threshold
            ]

            logger.info(
                f"Found {len(filtered_results)} relevant documents "
                f"(threshold: {effective_threshold})"
            )
            return filtered_results

        except Exception as e:
            logger.error(f"Error in similarity search with score: {str(e)}")
            raise

    def delete_documents_by_metadata(self, metadata_filter: Dict[str, Any]) -> bool:
        """根据元数据删除文档"""
        self._ensure_initialized()
        try:
            # 获取ChromaDB collection
            collection = self.chroma_client.get_collection(self.collection_name)

            # 查找匹配的文档ID
            results = collection.get(where=metadata_filter)

            if results and results["ids"]:
                # 删除文档
                collection.delete(ids=results["ids"])
                logger.info(f"Deleted {len(results['ids'])} documents")
                return True
            else:
                logger.warning("No documents found matching the filter")
                return False

        except Exception as e:
            logger.error(f"Error deleting documents: {str(e)}")
            raise

    def delete_document_by_id(self, document_id: str) -> bool:
        """根据文档ID删除相关的所有chunks"""
        return self.delete_documents_by_metadata({"document_id": document_id})

    def delete_by_metadata(self, key: str, value: str) -> bool:
        """根据元数据键值对删除文档（便捷方法）"""
        return self.delete_documents_by_metadata({key: value})

    def get_collection_info(self) -> Dict[str, Any]:
        """获取集合信息"""
        # 避免在此处初始化嵌入；尽量使用轻量客户端获取信息
        try:
            # 优先使用与当前LangChain向量库绑定的collection，避免路径不一致
            collection = getattr(self.vectorstore, "_collection", None)
            if collection is None:
                if self.chroma_client is None:
                    self._ensure_chroma_client_only()
                collection = self.chroma_client.get_collection(self.collection_name)

            count = collection.count()
            # 报告当前配置的嵌入模型名称，避免误导
            from app.core.config import settings as _settings

            _cfg = _settings.get_model_config()
            return {
                "collection_name": self.collection_name,
                "document_count": count,
                "embedding_model": _cfg.get("embedding_model", "unknown"),
            }
        except Exception as e:
            logger.error(f"Error getting collection info: {str(e)}")
            return {"error": str(e)}

    def list_documents(self) -> List[Dict[str, Any]]:
        """列出所有文档的基本信息"""
        self._ensure_initialized()
        try:
            # 优先使用与当前LangChain向量库绑定的collection，避免路径不一致
            collection = getattr(self.vectorstore, "_collection", None)
            if collection is None:
                if self.chroma_client is None:
                    self._ensure_chroma_client_only()
                collection = self.chroma_client.get_collection(self.collection_name)

            # 获取所有文档的元数据（加大limit，避免默认分页导致漏数据）
            results = collection.get(include=["metadatas"], limit=100000)
            metadatas = results.get("metadatas") if isinstance(results, dict) else None
            if not metadatas:
                # 记录一次计数供诊断
                try:
                    cnt = collection.count()
                    logger.info(
                        f"list_documents(): metadatas empty, collection.count()={cnt}"
                    )
                except Exception:
                    pass
                return []

            # 按document_id分组（兼容某些版本返回的嵌套结构）
            documents: Dict[str, Dict[str, Any]] = {}
            flat_list: List[Dict[str, Any]] = []
            for item in metadatas:
                if isinstance(item, list):
                    flat_list.extend([m for m in item if isinstance(m, dict)])
                elif isinstance(item, dict):
                    flat_list.append(item)

            for metadata in flat_list:
                doc_id = metadata.get("document_id", "unknown")
                filename = metadata.get("filename", "unknown")
                if doc_id not in documents:
                    documents[doc_id] = {
                        "document_id": doc_id,
                        "filename": filename,
                        "chunk_count": 0,
                        "processed_at": metadata.get("processed_at"),
                    }
                documents[doc_id]["chunk_count"] += 1

            return list(documents.values())
        except Exception as e:
            logger.error(f"Error listing documents: {str(e)}")
            return []

    def document_exists_by_filename(self, filename: str) -> bool:
        """使用元数据精确查询判断文件名是否已存在，避免全量扫描且避免初始化embeddings"""
        # 仅初始化Chroma客户端，避免加载embeddings
        self._ensure_chroma_client_only()
        try:
            collection = self.chroma_client.get_collection(self.collection_name)
            # 进行元数据过滤查询，直接检查是否返回任何ID
            results = collection.get(where={"filename": filename})
            ids = results.get("ids") if isinstance(results, dict) else None
            return bool(ids)
        except Exception as e:
            logger.warning(f"Error checking filename existence: {str(e)}")
            return False

    def document_exists_by_content_hash(self, content_hash: str) -> bool:
        """使用元数据精确查询判断内容哈希是否已存在"""
        self._ensure_chroma_client_only()
        try:
            collection = self.chroma_client.get_collection(self.collection_name)
            results = collection.get(where={"content_hash": content_hash})
            ids = results.get("ids") if isinstance(results, dict) else None
            return bool(ids)
        except Exception as e:
            logger.warning(f"Error checking content hash existence: {str(e)}")
            return False

    def _get_document_summary_by_key(
        self, key: str, value: str
    ) -> Optional[Dict[str, Any]]:
        """根据某个元数据键查询并汇总文档信息（轻量，避免初始化embeddings）"""
        self._ensure_chroma_client_only()
        try:
            collection = self.chroma_client.get_collection(self.collection_name)
            results = collection.get(where={key: value})
            if not isinstance(results, dict):
                return None
            metadatas = results.get("metadatas")
            if not metadatas:
                return None
            # metadatas 是一个包含每个chunk元数据的列表
            chunk_count = len(metadatas)
            first = metadatas[0] if chunk_count > 0 else {}
            return {
                "document_id": first.get("document_id"),
                "job_id": first.get("job_id"),
                "filename": first.get("filename"),
                "chunk_count": chunk_count,
                "processed_at": first.get("processed_at"),
                "file_path": first.get("file_path"),
            }
        except Exception as e:
            logger.warning(f"Error getting document summary by {key}: {str(e)}")
            return None

    def get_summary_by_job_id(self, job_id: str) -> Optional[Dict[str, Any]]:
        return self._get_document_summary_by_key("job_id", job_id)

    def get_summary_by_document_id(self, document_id: str) -> Optional[Dict[str, Any]]:
        """按内部document_id查询文档汇总（轻量）"""
        return self._get_document_summary_by_key("document_id", document_id)

    def health_check(self, deep: Optional[bool] = None) -> Dict[str, Any]:
        """健康检查"""
        if deep is False:
            # 轻量检查：仅确认向量库可连通，不触发嵌入初始化/外部网络
            self._ensure_chroma_client_only()
            info = self.get_collection_info()
            if isinstance(info, dict) and info.get("error"):
                return {
                    "status": "unhealthy",
                    "vector_store": "unavailable",
                    "collection_info": info,
                }
            return {
                "status": "healthy",
                "vector_store": "connected",
                "collection_info": info,
            }
        try:
            # 深度检查：初始化并验证嵌入模型
            self._ensure_initialized()
            info = self.get_collection_info()
            test_embedding = self.embeddings.embed_query("test")
            return {
                "status": "healthy",
                "vector_store": "connected",
                "embedding_model": "working",
                "collection_info": info,
                "embedding_dimension": len(test_embedding),
            }
        except Exception as e:
            logger.error(f"Vector store health check failed: {str(e)}")
            return {"status": "unhealthy", "error": str(e)}

    def as_retriever(self, **kwargs):
        """返回LangChain检索器接口"""
        self._ensure_initialized()
        return self.vectorstore.as_retriever(**kwargs)


# 全局单例实例
_vector_store_instance = None


def get_vector_store() -> VectorStore:
    """获取向量存储单例实例"""
    global _vector_store_instance
    if _vector_store_instance is None:
        _vector_store_instance = VectorStore()
    return _vector_store_instance
