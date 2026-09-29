"""Regression checks for missing evidence and empty/cached model answers."""

from unittest.mock import Mock, patch

import pytest
from langchain_core.documents import Document

from app.core.config import settings
from app.core.global_budget import offline_provider_access
from app.core.qa_engine import EvidenceRetriever, QAEngine


@pytest.fixture(autouse=True)
def offline_scope():
    with offline_provider_access(reason="isolated retrieval unit tests"):
        yield


def test_nearest_evidence_survives_diversity_and_duplicates():
    a = Document(page_content="upload limit", metadata={"document_id": "one"})
    b = Document(page_content="error meaning", metadata={"document_id": "two"})
    c = Document(page_content="duplicate detection", metadata={"document_id": "one"})
    retriever = EvidenceRetriever(
        nearest=Mock(invoke=Mock(return_value=[a, b])),
        diverse=Mock(invoke=Mock(return_value=[a, c, b])),
        k=3,
    )
    assert retriever.invoke("question") == [a, b, c]


def test_disabled_cache_and_empty_answer(monkeypatch):
    monkeypatch.setattr(settings, "enable_qa_cache", False)
    engine = QAEngine.__new__(QAEngine)
    engine.vector_store = Mock()
    engine.vector_store.as_retriever.return_value.invoke.return_value = []
    engine._effective_model_config = settings.get_model_config()
    engine.get_relevant_documents = Mock(return_value=[])
    chain = Mock()
    chain.invoke.return_value = {"result": "", "source_documents": []}
    engine._build_qa_chain = Mock(return_value=chain)
    with patch("app.core.qa_engine.cache_manager") as cache:
        result = engine.ask("question")
        assert result.answer
        assert not result.from_cache
        cache.get_qa_cache.assert_not_called()
        cache.set_qa_cache.assert_not_called()
        chain.invoke.return_value = {"result": "An answer", "source_documents": []}
        assert engine.ask("question").answer == "An answer"
        cache.get_qa_cache.assert_not_called()
        cache.set_qa_cache.assert_not_called()


def test_deepseek_uses_configured_budget_without_thinking(monkeypatch):
    monkeypatch.setattr(settings, "llm_max_tokens", 800)
    monkeypatch.setattr(settings, "llm_temperature", 0.1)
    engine = QAEngine.__new__(QAEngine)
    engine._overrides = {"api_key": "test-only"}
    with patch.object(
        type(settings),
        "get_model_config",
        return_value={
            "provider": "deepseek",
            "chat_model": "deepseek-flash",
            "api_base_url": "https://api.deepseek.com",
        },
    ), patch("app.core.qa_engine.ChatOpenAI") as llm:
        engine._initialize_llm()
    assert llm.call_args.kwargs["max_tokens"] == 800
    assert llm.call_args.kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
