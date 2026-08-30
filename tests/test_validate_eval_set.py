import json

from langchain_core.documents import Document

from eval import validate_eval_set as validator

SPLITTER = {
    "name": "test-splitter",
    "chunk_size": 100,
    "chunk_overlap": 10,
    "separators": ["\n", ""],
}


def _chunk(text, filename="a.md", chunk_index=0):
    return Document(
        page_content=text,
        metadata={"filename": filename, "chunk_index": chunk_index},
    )


def _question(**overrides):
    item = {
        "id": "q1",
        "question": "Where is the evidence?",
        "type": "exact",
        "answerable": True,
        "match": {"required": ["alpha"]},
    }
    item.update(overrides)
    return item


def _validate(items, chunks, require_explicit=True):
    return validator.validate_eval_set(
        items,
        chunks,
        eval_set_sha256="eval-hash",
        corpus_hash="corpus-hash",
        require_explicit_answerable=require_explicit,
        splitter=SPLITTER,
    )


def _codes(report, key="errors"):
    return [issue["code"] for issue in report[key]]


def test_reports_dead_snippet_and_query_leak():
    items = [
        _question(
            question="Does the answer contain missing evidence?",
            match={"required": ["missing evidence"]},
        )
    ]

    report = _validate(items, [_chunk("alpha only")])

    assert "E1" in _codes(report)
    assert "E2" in _codes(report)


def test_rejects_degenerate_multihop_in_one_document():
    item = _question(
        type="multihop",
        match={"required": ["alpha", "beta"]},
    )
    chunks = [
        _chunk("alpha", chunk_index=0),
        _chunk("beta", chunk_index=1),
    ]

    report = _validate([item], chunks)

    assert "E3" in _codes(report)
    cover = report["questions"][0]["minimum_covers"][0]
    assert cover["chunk_count"] == 2
    assert cover["document_count"] == 1


def test_accepts_cross_document_multihop():
    item = _question(
        type="multihop",
        gold_docs=["a.md", "b.md"],
        match={"required": ["alpha", "beta"]},
    )
    chunks = [_chunk("alpha"), _chunk("beta", filename="b.md")]

    report = _validate([item], chunks)

    assert report["errors"] == []
    assert report["warnings"] == []
    assert report["questions"][0]["minimum_covers"][0]["document_count"] == 2


def test_reports_schema_errors_for_duplicate_id_type_and_empty_match():
    items = [
        _question(),
        _question(type="other", match={}),
    ]

    report = _validate(items, [_chunk("alpha")])

    messages = [issue["message"] for issue in report["errors"]]
    assert sum(code == "E4" for code in _codes(report)) >= 3
    assert any("unique" in message for message in messages)
    assert any("type" in message for message in messages)
    assert any("require required or any_of" in message for message in messages)


def test_v3_requires_explicit_answerable_but_legacy_accepts_default():
    item = _question()
    item.pop("answerable")

    v3_report = _validate([item], [_chunk("alpha")], require_explicit=True)
    legacy_report = _validate([item], [_chunk("alpha")], require_explicit=False)

    assert "E4" in _codes(v3_report)
    assert legacy_report["errors"] == []
    assert legacy_report["questions"][0]["answerable"] is True


def test_reports_unsupported_unanswerable():
    item = _question(answerable=False, match={})

    report = _validate([item], [_chunk("unrelated")])

    assert _codes(report) == ["E5"]


def test_reports_all_warning_types():
    repeated = [
        _chunk("shared common", filename=f"{name}.md") for name in ("a", "b", "c", "d")
    ]
    warning_items = [
        _question(match={"required": ["common"]}),
        _question(
            id="q2",
            match={"required": ["shared", "common"]},
        ),
        _question(
            id="q3",
            type="semantic",
            match={"required": ["left", "right"]},
        ),
        _question(
            id="q4",
            type="multihop",
            gold_docs=["wrong.md"],
            match={"required": ["left", "right"]},
        ),
    ]
    chunks = repeated + [
        _chunk("left", filename="left.md"),
        _chunk("right", filename="right.md"),
    ]

    report = _validate(warning_items, chunks)

    assert {"W1", "W2", "W3", "W4"} <= set(_codes(report, "warnings"))


def test_redundant_evidence_includes_nested_owner_sets():
    item = _question(match={"required": ["broad", "narrow"]})
    chunks = [
        _chunk("broad narrow", filename="a.md"),
        _chunk("broad", filename="b.md"),
    ]

    report = _validate([item], chunks)

    assert "W2" in _codes(report, "warnings")


def test_minimum_cover_honors_required_and_any_of_and_returns_all_solutions():
    item = _question(
        type="multihop",
        match={
            "required": ["alpha"],
            "any_of": ["beta", "gamma"],
            "any_of_min": 1,
        },
    )
    chunks = [
        _chunk("alpha beta", filename="a.md"),
        _chunk("alpha gamma", filename="b.md"),
        _chunk("beta gamma", filename="c.md"),
    ]

    report = _validate([item], chunks)
    covers = report["questions"][0]["minimum_covers"]

    assert len(covers) == 2
    assert {cover["documents"][0] for cover in covers} == {"a.md", "b.md"}
    assert all(cover["chunk_count"] == 1 for cover in covers)
    assert "E3" in _codes(report)


def test_json_report_has_stable_refs_and_hashes_without_chunk_text():
    secret_body = "alpha highly private chunk body"

    report = _validate([_question()], [_chunk(secret_body)])
    serialized = json.dumps(report, ensure_ascii=False)
    owner = report["questions"][0]["snippets"][0]["owners"][0]

    assert report["derived"] is True
    assert report["report_type"] == "derived_evidence_owners"
    assert report["eval_set_sha256"] == "eval-hash"
    assert report["corpus_hash"] == "corpus-hash"
    assert report["chunk_manifest_hash"]
    assert report["chunk_ref_version"] == 1
    assert report["matcher_version"] == 1
    assert owner["chunk_ref"].startswith("cr1:")
    assert owner["text_sha256"]
    assert "page_content" not in serialized
    assert secret_body not in serialized
