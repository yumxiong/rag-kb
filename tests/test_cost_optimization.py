"""Cost optimization endpoint unit tests."""

from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException

from app.api import cost_optimization


def _stats(embedding_entries=2, embedding_hits=5, qa_entries=1, qa_hits=3):
    return {
        "embedding_cache": {
            "entries": embedding_entries,
            "total_hits": embedding_hits,
        },
        "qa_cache": {"entries": qa_entries, "total_hits": qa_hits},
    }


@pytest.mark.asyncio
async def test_get_cache_stats_calculates_savings():
    stats = _stats()
    with patch.object(cost_optimization.cache_manager, "get_cache_stats") as get_stats:
        get_stats.return_value = stats

        result = await cost_optimization.get_cache_stats()

    assert result["cost_savings"] == {
        "embedding_savings_usd": 0.0005,
        "qa_savings_usd": 0.003,
        "total_savings_usd": 0.0035,
        "total_requests": 3,
        "total_cache_hits": 8,
    }


@pytest.mark.asyncio
async def test_get_cache_stats_wraps_dependency_error():
    with patch.object(
        cost_optimization.cache_manager,
        "get_cache_stats",
        side_effect=RuntimeError("cache unavailable"),
    ):
        with pytest.raises(HTTPException, match="cache unavailable") as exc_info:
            await cost_optimization.get_cache_stats()

    assert exc_info.value.status_code == 500


@pytest.mark.asyncio
async def test_get_embedding_stats_reports_cache_metrics():
    vector_store = Mock()
    vector_store.embeddings.get_cache_stats.return_value = {"cache_hit_rate": 75.0}
    with patch.object(cost_optimization, "VectorStore", return_value=vector_store):
        result = await cost_optimization.get_embedding_stats()

    assert result["success"] is True
    assert result["embedding_stats"]["cache_hit_rate"] == 75.0
    assert result["message"] == "Cache hit rate: 75.0%"


@pytest.mark.asyncio
async def test_get_embedding_stats_handles_unavailable_metrics():
    vector_store = Mock()
    vector_store.embeddings = None
    with patch.object(cost_optimization, "VectorStore", return_value=vector_store):
        result = await cost_optimization.get_embedding_stats()

    assert result == {
        "success": False,
        "message": "Embedding cache stats not available",
    }


@pytest.mark.asyncio
async def test_get_embedding_stats_wraps_initialization_error():
    with patch.object(
        cost_optimization, "VectorStore", side_effect=RuntimeError("init failed")
    ):
        with pytest.raises(HTTPException, match="init failed") as exc_info:
            await cost_optimization.get_embedding_stats()

    assert exc_info.value.status_code == 500


@pytest.mark.asyncio
async def test_cleanup_expired_cache_success_and_failure():
    with patch.object(
        cost_optimization.cache_manager, "cleanup_expired_cache"
    ) as cleanup:
        result = await cost_optimization.cleanup_expired_cache()

    cleanup.assert_called_once_with()
    assert result.success is True

    with patch.object(
        cost_optimization.cache_manager,
        "cleanup_expired_cache",
        side_effect=OSError("locked"),
    ):
        with pytest.raises(HTTPException, match="locked") as exc_info:
            await cost_optimization.cleanup_expired_cache()
    assert exc_info.value.status_code == 500


@pytest.mark.asyncio
async def test_recommendations_flag_low_cache_usage():
    with patch.object(
        cost_optimization.cache_manager,
        "get_cache_stats",
        return_value=_stats(
            embedding_entries=0, embedding_hits=0, qa_entries=0, qa_hits=0
        ),
    ):
        result = await cost_optimization.get_optimization_recommendations()

    assert [item["type"] for item in result["recommendations"]] == [
        "embedding_cache",
        "qa_cache",
    ]
    assert result["generated_at"]


@pytest.mark.asyncio
async def test_recommendations_report_healthy_cache():
    with patch.object(
        cost_optimization.cache_manager,
        "get_cache_stats",
        return_value=_stats(
            embedding_entries=2, embedding_hits=4, qa_entries=2, qa_hits=4
        ),
    ):
        result = await cost_optimization.get_optimization_recommendations()

    assert result["recommendations"][0]["type"] == "general"
    assert result["cache_summary"]["qa_cache"]["entries"] == 2


@pytest.mark.asyncio
async def test_recommendations_wrap_stats_error():
    with patch.object(
        cost_optimization.cache_manager,
        "get_cache_stats",
        side_effect=ValueError("bad stats"),
    ):
        with pytest.raises(HTTPException, match="bad stats") as exc_info:
            await cost_optimization.get_optimization_recommendations()

    assert exc_info.value.status_code == 500
