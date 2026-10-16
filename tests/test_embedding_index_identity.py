"""Real local Chroma collections; synthetic vectors and no provider calls."""

from unittest.mock import Mock, patch

import pytest

from app.core.cached_embeddings import CachedEmbeddings
from app.core.config import Settings
from app.core.global_budget import offline_provider_access
from app.core.vector_store import IndexIdentityError, VectorStore


@pytest.fixture
def index(tmp_path):
    config = {
        "embedding_provider": "qwen",
        "embedding_model": "text-embedding-v3",
        "embedding_api_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "embedding_dimensions": 1024,
        "embedding_index_version": 1,
    }
    VectorStore._instance = None
    with patch("app.core.vector_store.settings") as settings:
        settings.chroma_db_path = str(tmp_path / "index")
        settings.get_model_config.side_effect = lambda: dict(config)
        store = VectorStore()
        try:
            yield store, config, settings
        finally:
            if store.chroma_client is not None:
                store.chroma_client._system.stop()
            VectorStore._instance = None


def test_persisted_identity_and_reopen(index):
    store, config, settings = index
    store._ensure_chroma_client_only()
    collection = store.chroma_client.get_collection("rag_documents")
    collection.add(ids=["one"], embeddings=[[0.1] * 1024], documents=["synthetic"])
    VectorStore._instance = None
    reopened = VectorStore()
    reopened._ensure_chroma_client_only()
    assert reopened._checked_collection("rag_documents").count() == 1
    settings.get_embedding_api_key.assert_not_called()


@pytest.mark.parametrize(
    "key,value",
    [
        ("embedding_model", "qwen3.7-text-embedding"),
        ("embedding_dimensions", 768),
        ("embedding_provider", "openai"),
        ("embedding_api_base_url", "https://different.invalid/v1"),
        ("embedding_index_version", 2),
    ],
)
def test_mismatch_refuses_before_provider_and_preserves_index(index, key, value):
    store, config, settings = index
    store._ensure_chroma_client_only()
    collection = store.chroma_client.get_collection("rag_documents")
    collection.add(ids=["one"], embeddings=[[0.1] * 1024], documents=["synthetic"])
    before = collection.get(include=["embeddings", "documents"])
    metadata = dict(collection.metadata)
    config[key] = value
    with pytest.raises(IndexIdentityError):
        store._ensure_initialized()
    settings.get_embedding_api_key.assert_not_called()
    assert collection.metadata == metadata
    after = collection.get(include=["embeddings", "documents"])
    assert after["ids"] == before["ids"]
    assert after["documents"] == before["documents"]
    assert (after["embeddings"] == before["embeddings"]).all()


def test_legacy_and_named_collection_not_relabelled(index):
    store, config, settings = index
    store._ensure_chroma_client_only()
    legacy = store.chroma_client.create_collection("legacy")
    with pytest.raises(IndexIdentityError):
        store._checked_collection("legacy")
    assert store.chroma_client.get_collection("legacy").metadata is None
    # A named evaluation collection must obey the same guard.
    store._initialized = True
    store.embeddings = Mock()
    with pytest.raises(IndexIdentityError):
        store.get_chroma("legacy")
    store.embeddings.embed_query.assert_not_called()
    assert legacy.count() == 0


def test_new_model_separate_directory_preserves_old_index(index, tmp_path):
    store, config, settings = index
    store._ensure_chroma_client_only()
    old = store.chroma_client.get_collection("rag_documents")
    config["embedding_model"] = "qwen3.7-text-embedding"
    settings.chroma_db_path = str(tmp_path / "new-index")
    VectorStore._instance = None
    new = VectorStore()
    try:
        new._ensure_chroma_client_only()
        assert (
            new._checked_collection("rag_documents").metadata["rag_embedding_model"]
            == "qwen3.7-text-embedding"
        )
        assert old.metadata["rag_embedding_model"] == "text-embedding-v3"
    finally:
        new.chroma_client._system.stop()


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "bad"])
def test_invalid_dimensions_rejected(value):
    with pytest.raises(ValueError):
        Settings(_env_file=None, embedding_dimensions=value)


def test_cache_identity_includes_dimensions(index):
    store, config, settings = index
    settings.get_embedding_api_key.return_value = "synthetic"
    with patch("app.core.vector_store.OpenAIEmbeddings"), patch(
        "app.core.vector_store.CachedEmbeddings"
    ) as cached:
        store._initialize_embeddings()
        first = cached.call_args.kwargs["model_name"]
        config["embedding_dimensions"] = 768
        store._initialize_embeddings()
        assert first != cached.call_args.kwargs["model_name"]


def test_new_model_real_chroma_add_and_query(index):
    store, config, settings = index
    config["embedding_model"] = "qwen3.7-text-embedding"
    settings.get_embedding_api_key.return_value = "synthetic"
    settings.embedding_timeout_seconds = 15
    with patch("app.core.vector_store.OpenAIEmbeddings") as factory, patch(
        "app.core.cached_embeddings.cache_manager"
    ) as cache:
        cache.get_embedding_cache.return_value = None
        factory.return_value.embed_documents.return_value = [[0.1] * 1024]
        factory.return_value.embed_query.return_value = [0.1] * 1024
        with offline_provider_access(reason="synthetic Chroma integration"):
            store._ensure_initialized()
            store.vectorstore.add_texts(["synthetic retrieval document"], ids=["one"])
            result = store.similarity_search("synthetic", k=1)
        assert result[0].page_content == "synthetic retrieval document"
        assert store._checked_collection("rag_documents").count() == 1
        assert factory.call_args.kwargs["dimensions"] == 1024


def test_incomplete_batch_is_not_cached():
    provider = Mock()
    provider.embed_documents.return_value = []
    embeddings = CachedEmbeddings(provider, "synthetic", dimensions=1024)
    with patch("app.core.cached_embeddings.cache_manager") as cache:
        cache.get_embedding_cache.return_value = None
        with offline_provider_access(reason="synthetic batch test"):
            with pytest.raises(ValueError, match="count"):
                embeddings.embed_documents(["synthetic"])
        cache.set_embedding_cache.assert_not_called()


@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("query", [False, True])
def test_bad_dimensions_never_reach_index_or_cache(cached, query):
    provider = Mock()
    provider.embed_query.return_value = [0.1] * 768
    provider.embed_documents.return_value = [[0.1] * 768]
    embeddings = CachedEmbeddings(provider, "synthetic", dimensions=1024)
    with patch("app.core.cached_embeddings.cache_manager") as cache:
        cache.get_embedding_cache.return_value = [0.1] * 768 if cached else None
        with offline_provider_access(reason="synthetic dimension test"):
            with pytest.raises(ValueError, match="dimension"):
                if query:
                    embeddings.embed_query("synthetic")
                else:
                    embeddings.embed_documents(["synthetic"])
        cache.set_embedding_cache.assert_not_called()
        if cached:
            provider.embed_query.assert_not_called()
            provider.embed_documents.assert_not_called()
