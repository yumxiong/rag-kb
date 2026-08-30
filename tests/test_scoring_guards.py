import pytest
from langchain_core.documents import Document

from eval import scoring


def _chunk(text="evidence"):
    return Document(page_content=text, metadata={})


@pytest.mark.parametrize(
    "item",
    [
        {"id": "q-empty", "type": "exact", "answerable": True, "match": {}},
        {"id": "q-empty", "type": "exact", "answerable": True},
        {"id": "q-legacy-empty", "type": "exact", "match": {}},
    ],
)
def test_score_question_rejects_empty_match(item):
    with pytest.raises(
        ValueError, match="empty match is not scoreable by the snippet scorer"
    ):
        scoring.score_question(item, [_chunk()], k=1)


def test_score_question_rejects_unanswerable_before_match_validation():
    item = {
        "id": "q-reject",
        "type": "exact",
        "answerable": False,
        "match": {},
    }

    with pytest.raises(
        scoring.UnsupportedQuestionError,
        match="unanswerable/reject scoring is not implemented",
    ):
        scoring.score_question(item, [_chunk()], k=1)


def test_score_question_rejects_non_boolean_answerable():
    item = {
        "id": "q-invalid",
        "type": "exact",
        "answerable": "true",
        "match": {"required": ["evidence"]},
    }

    with pytest.raises(ValueError, match="answerable must be boolean"):
        scoring.score_question(item, [_chunk()], k=1)


def test_legacy_question_without_answerable_still_scores_as_true():
    item = {
        "id": "q-legacy",
        "type": "exact",
        "match": {"required": ["evidence"]},
    }

    row = scoring.score_question(item, [_chunk()], k=1)

    assert row["hit"] is True
    assert row["completion_rank"] == 1
