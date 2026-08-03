"""
RAG问答引擎模块
"""

import logging
import time
from typing import Any, Dict, List, Optional

from langchain.chains import RetrievalQA
from langchain_core.documents import Document
from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI

from app.core.cache_manager import cache_manager
from app.core.config import settings
from app.core.vector_store import VectorStore
from app.models.schemas import QuestionResponse, SourceDocument

logger = logging.getLogger(__name__)


def _format_scored_candidate(doc: Document, score: float) -> str:
    """Format a scored document for retrieval diagnostics."""
    document_id = doc.metadata.get("document_id")
    if not isinstance(document_id, str):
        document_id = "unknown"
    filename = doc.metadata.get("filename", "Unknown")
    return f"(doc_id={document_id[:8]}, file={filename}, dist={score:.4f})"


class QAEngine:
    """RAG问答引擎"""

    def __init__(self, vector_store: VectorStore, overrides: Optional[dict] = None):
        self.vector_store = vector_store
        self.llm = None
        self.qa_chain = None
        # 允许按请求覆盖：{"api_key": str, "provider": str, "api_base_url": str, "model": str}
        self._overrides = overrides or {}
        self._effective_model_config = None  # 记录生效的模型配置用于缓存等

        self._initialize_llm()
        self._build_qa_chain()

    def _initialize_llm(self):
        """初始化大语言模型"""
        try:
            overrides = self._overrides
            # 1) API Key 优先使用请求覆盖，否则使用全局配置
            api_key = overrides.get("api_key") or settings.get_api_key()
            if overrides.get("api_base_url") and not overrides.get("api_key"):
                raise ValueError("base URL 需同时提供LLM-Api-Key")
            if not api_key:
                raise ValueError(f"API key not configured for {settings.llm_provider}")

            # 2) 获取模型配置并应用覆盖项（不修改全局 settings）
            model_config = settings.get_model_config(overrides)
            # 记录生效配置
            self._effective_model_config = dict(model_config)

            # 使用ChatOpenAI（支持兼容的API）
            llm_kwargs = {
                "model": model_config["chat_model"],
                "api_key": api_key,
                "temperature": 0.1,
                "max_tokens": 1000,
            }

            # 设置自定义API端点（如果指定）
            if (
                model_config["api_base_url"]
                and model_config["api_base_url"] != "https://api.openai.com/v1"
            ):
                llm_kwargs["base_url"] = model_config["api_base_url"]
                # 对于DeepSeek等兼容OpenAI的API，设置组织ID为空
                llm_kwargs["organization"] = ""

            self.llm = ChatOpenAI(**llm_kwargs)

            logger.info(
                "LLM initialized successfully: %s/%s",
                model_config["provider"],
                model_config["chat_model"],
            )

        except Exception as e:
            logger.error(f"Error initializing LLM: {str(e)}")
            raise

    def _build_qa_chain(self, retriever=None):
        """构建问答链"""
        try:
            # 自定义提示模板
            prompt_template = """你是一个智能助手，请根据以下文档内容回答用户的问题。

文档内容：
{context}

问题：{question}

请注意：
1. 请尽量基于提供的文档内容来回答问题
2. 如果文档中没有相关信息，请明确说明
3. 回答要准确、简洁、有帮助
4. 如果涉及多个方面，请分点说明

回答："""

            PROMPT = PromptTemplate(
                template=prompt_template, input_variables=["context", "question"]
            )

            # 构建检索问答链（支持传入按请求定制的 retriever）
            effective_retriever = retriever or self.vector_store.as_retriever(
                search_kwargs={"k": settings.max_sources}
            )
            qa_chain = RetrievalQA.from_chain_type(
                llm=self.llm,
                chain_type="stuff",
                retriever=effective_retriever,
                return_source_documents=True,
                chain_type_kwargs={"prompt": PROMPT},
            )
            # 仅当未传入自定义 retriever 时，保留为默认链
            if retriever is None:
                self.qa_chain = qa_chain
            logger.info("QA chain built successfully")
            return qa_chain

        except Exception as e:
            logger.error(f"Error building QA chain: {str(e)}")
            raise

    def ask(
        self,
        question: str,
        max_sources: Optional[int] = None,
        document_id: Optional[str] = None,
    ) -> QuestionResponse:
        """回答问题（带缓存优化）"""
        start_time = time.time()

        try:
            if not question.strip():
                raise ValueError("Question cannot be empty")

            user_source_limit = max_sources or settings.max_sources
            precheck_k = settings.retrieval_precheck_k
            scoped_k = settings.retrieval_k_scoped
            global_k = settings.retrieval_k_global
            global_fetch_k = settings.retrieval_fetch_k_global
            mmr_lambda_mult = settings.retrieval_mmr_lambda_mult

            # 首先获取相关文档用于生成上下文hash；
            # 若限定文档下只有“低相关”（距离大于阈值）或为零，则回退到全库
            used_document_id = document_id
            fallback_note = ""

            if document_id:
                # 使用打分检索做预判（更严格阈值），并与全库结果比较，必要时回退
                try:
                    restricted_scored = self.vector_store.similarity_search_with_score(
                        query=question,
                        k=precheck_k,
                        filter_dict={"document_id": document_id},
                        threshold=settings.relevance_fallback_threshold,
                    )
                except Exception as _e:
                    logger.warning(
                        "Scored search failed under document scope, "
                        f"fallback to vanilla search: {_e}"
                    )
                    restricted_scored = []
                # 全库打分（同阈值），用于与限定范围对比
                try:
                    global_scored = self.vector_store.similarity_search_with_score(
                        query=question,
                        k=precheck_k,
                        filter_dict=None,
                        threshold=settings.relevance_fallback_threshold,
                    )
                except Exception as _e:
                    logger.warning(f"Scored search failed for global scope: {_e}")
                    global_scored = []

                # 计算最优距离（距离越小越好）
                best_restricted = min([s for (_, s) in restricted_scored], default=None)
                best_global = min([s for (_, s) in global_scored], default=None)

                # 记录调试信息：展示前3个候选及其距离
                if restricted_scored:
                    top_r = restricted_scored[: min(3, len(restricted_scored))]
                    logger.info(
                        "Restricted top candidates: "
                        + ", ".join(_format_scored_candidate(d, s) for d, s in top_r)
                    )
                if global_scored:
                    top_g = global_scored[: min(3, len(global_scored))]
                    logger.info(
                        "Global top candidates: "
                        + ", ".join(_format_scored_candidate(d, s) for d, s in top_g)
                    )

                should_fallback = False
                if best_restricted is None and best_global is not None:
                    should_fallback = True
                elif best_restricted is not None and best_global is not None:
                    # 如果全库最优明显优于限定范围（留出安全边际），则回退
                    margin = getattr(settings, "relevance_fallback_margin", 0.25)
                    if best_global + margin < best_restricted:
                        should_fallback = True

                if should_fallback:
                    logger.info(
                        f"Fallback to global: best_restricted={best_restricted}, "
                        f"best_global={best_global}, "
                        f"threshold={settings.relevance_fallback_threshold}"
                    )
                    used_document_id = None
                    # 使用全库阈值过滤后的文档作为上下文（若无则退回无过滤的简单检索）
                    if len(global_scored) > 0:
                        relevant_docs = [doc for doc, _ in global_scored][:global_k]
                        fallback_note = "提示：在您选定的文档中未检索到更相关的内容，已自动在全库中扩大检索范围。"
                    else:
                        relevant_docs = self.get_relevant_documents(
                            question, global_k, None
                        )
                        fallback_note = (
                            "提示：在您选定的文档以及全库中均未检索到相关内容。"
                        )
                else:
                    # 使用限定范围内阈值过滤后的文档作为上下文
                    relevant_docs = [doc for doc, _ in restricted_scored][:scoped_k]
            else:
                # 全库预检（保持原行为即可）
                relevant_docs = self.get_relevant_documents(question, global_k, None)

            # 基于最终采用的上下文计算hash
            context_hash = cache_manager.get_context_hash(relevant_docs)

            # 获取模型配置用于缓存key（使用生效的配置，避免与默认配置混淆）
            model_cfg = self._effective_model_config or settings.get_model_config()
            base = (model_cfg["api_base_url"] or "https://api.openai.com/v1").rstrip(
                "/"
            )
            model_name = f"{model_cfg['provider']}/{model_cfg['chat_model']}@{base}"

            # 检查QA缓存
            cached_result = cache_manager.get_qa_cache(
                question, context_hash, model_name
            )
            if cached_result:
                processing_time = time.time() - start_time
                logger.info(f"Question answered from cache in {processing_time:.2f}s")
                cached_sources = [
                    SourceDocument(**src) for src in cached_result["sources"]
                ]
                visible_sources = cached_sources[:user_source_limit]
                return QuestionResponse(
                    answer=cached_result["answer"],
                    sources=visible_sources,
                    processing_time=round(processing_time, 2),
                    from_cache=True,
                )

            # 缓存未命中，执行RAG查询（为本次请求构建 retriever，防止跨文档混入）
            k_effective = scoped_k if used_document_id else global_k
            search_kwargs: Dict[str, Any] = {"k": k_effective}
            if used_document_id:
                search_kwargs["filter"] = {"document_id": used_document_id}
            # 构建 retriever：全库检索使用 MMR 增强多样性，降低单文档“淹没”其他文档的情况
            if used_document_id:
                retriever = self.vector_store.as_retriever(search_kwargs=search_kwargs)
                logger.info(
                    "QAEngine.ask retrieval_mode=scoped "
                    f"user_source_limit={user_source_limit} precheck_k={precheck_k} "
                    f"k_effective={k_effective} document_id={used_document_id}"
                )
            else:
                mmr_kwargs = {
                    **search_kwargs,
                    "fetch_k": global_fetch_k,
                    "lambda_mult": mmr_lambda_mult,
                }
                retriever = self.vector_store.as_retriever(
                    search_type="mmr", search_kwargs=mmr_kwargs
                )
                logger.info(
                    "QAEngine.ask retrieval_mode=global "
                    f"user_source_limit={user_source_limit} precheck_k={precheck_k} "
                    f"k_effective={k_effective} fetch_k={global_fetch_k} "
                    f"lambda_mult={mmr_lambda_mult}"
                )

            qa_chain = self._build_qa_chain(retriever=retriever)
            result = qa_chain.invoke({"query": question})

            # 处理答案
            answer = result.get("result", "抱歉，我无法找到相关信息来回答这个问题。")
            if fallback_note:
                answer = f"{fallback_note}\n\n" + answer
            source_docs = result.get("source_documents", [])
            # 防御性过滤：若指定了 document_id，确保来源文档仅来自该文档
            if used_document_id:
                before = len(source_docs)
                source_docs = [
                    d
                    for d in source_docs
                    if d.metadata.get("document_id") == used_document_id
                ]
                after = len(source_docs)
                if after < before:
                    logger.info(
                        "Filtered source documents by document_id="
                        f"{used_document_id}: {before} -> {after}"
                    )

            # 处理源文档
            sources = self._process_source_documents(source_docs)

            # 缓存结果
            sources_dict = [src.model_dump() for src in sources]
            cache_manager.set_qa_cache(
                question, context_hash, answer, sources_dict, model_name
            )

            # 计算处理时间
            processing_time = time.time() - start_time
            visible_sources = sources[:user_source_limit]
            response = QuestionResponse(
                answer=answer,
                sources=visible_sources,
                processing_time=round(processing_time, 2),
                from_cache=False,
            )

            logger.info(f"Question answered successfully in {processing_time:.2f}s")
            return response

        except Exception as e:
            processing_time = time.time() - start_time
            error_msg = f"抱歉，处理您的问题时发生了错误：{str(e)}"

            logger.error(f"Error answering question: {str(e)}")

            return QuestionResponse(
                answer=error_msg,
                sources=[],
                processing_time=round(processing_time, 2),
                from_cache=False,
            )

    def _process_source_documents(
        self, source_docs: List[Document]
    ) -> List[SourceDocument]:
        """处理源文档信息"""
        sources = []

        for doc in source_docs:
            try:
                # 获取文档元数据
                metadata = doc.metadata
                filename = metadata.get("filename", "Unknown")
                content = doc.page_content

                # 截断过长的内容
                if len(content) > 300:
                    content = content[:300] + "..."

                source = SourceDocument(
                    document_name=filename,
                    content=content,
                    similarity_score=1.0,  # ChromaDB不直接返回分数，这里使用默认值
                    page_number=metadata.get("page", None),
                )

                sources.append(source)

            except Exception as e:
                logger.warning(f"Error processing source document: {str(e)}")
                continue

        return sources

    def get_relevant_documents(
        self, question: str, k: Optional[int] = None, document_id: Optional[str] = None
    ) -> List[Document]:
        """获取相关文档（不生成答案）"""
        try:
            k = k or settings.max_sources

            # 构建过滤条件
            filter_dict = None
            if document_id:
                filter_dict = {"document_id": document_id}
                logger.info(f"Filtering documents by document_id: {document_id}")

            relevant_docs = self.vector_store.similarity_search(
                query=question, k=k, filter_dict=filter_dict
            )

            logger.info(f"Retrieved {len(relevant_docs)} relevant documents")
            return relevant_docs

        except Exception as e:
            logger.error(f"Error getting relevant documents: {str(e)}")
            return []

    def health_check(
        self, deep: Optional[bool] = None, with_qa: Optional[bool] = None
    ) -> Dict[str, Any]:
        """健康检查"""
        try:
            # 检查向量存储
            vector_health = self.vector_store.health_check(deep=deep)
            llm_status, qa_status = "skipped", "skipped"
            collection_info = self.vector_store.get_collection_info()
            if deep is True:
                if self.llm:
                    self.llm.predict("Hello")
                    llm_status = "connected"
                else:
                    llm_status = "not_initialized"

                if with_qa is True:
                    try:
                        qa_status = (
                            "working" if self.ask("测试问题", 1).answer else "failed"
                        )
                    except Exception as e:
                        logger.error(f"QA chain health check failed: {str(e)}")
                        qa_status = "failed"

            overall = (
                "healthy"
                if (
                    vector_health.get("status") == "healthy"
                    and llm_status in ("connected", "skipped")
                    and qa_status in ("working", "skipped")
                )
                else "degraded"
            )
            return {
                "status": overall,
                "llm": llm_status,
                "vector_store": vector_health.get("status", "unknown"),
                "qa_chain": qa_status,
                "collection_info": collection_info,
            }
        except Exception as e:
            logger.error(f"Health check failed: {str(e)}")
            return {"status": "unhealthy", "error": str(e)}

    def get_conversation_context(
        self, conversation_history: List[Dict[str, str]]
    ) -> str:
        """构建对话上下文（为多轮对话预留）"""
        context_parts = []

        for turn in conversation_history[-3:]:  # 保留最近3轮对话
            question = turn.get("question", "")
            answer = turn.get("answer", "")

            if question and answer:
                context_parts.append(f"Q: {question}")
                context_parts.append(f"A: {answer}")

        return "\n".join(context_parts) if context_parts else ""
