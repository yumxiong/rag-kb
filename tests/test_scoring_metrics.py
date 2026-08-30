from langchain_core.documents import Document

from eval import score_run, scoring


def _chunk(text, filename, index, chunk_ref):
    return Document(
        page_content=text,
        metadata={
            "filename": filename,
            "chunk_index": index,
            "chunk_ref": chunk_ref,
        },
    )


def _item(match, question_type="multihop"):
    return {
        "id": "q-metrics",
        "question": "unused",
        "type": question_type,
        "match": match,
    }


def test_multihop_diagnostics_track_ranks_spread_and_stable_witnesses():
    item = _item({"required": ["alpha", "beta"]})
    chunks = [
        _chunk("alpha evidence", "a.md", 0, "cr1:a"),
        _chunk("unrelated", "x.md", 0, "cr1:x"),
        _chunk("beta evidence", "b.md", 0, "cr1:b"),
    ]

    row = scoring.score_question(item, chunks, k=3)

    assert row["snippet_ranks"] == {"alpha": 1, "beta": 3}
    assert row["completion_rank"] == 3
    assert row["first_rank"] == row["completion_rank"]
    assert row["earliest_evidence_rank"] == 1
    assert row["hop_spread"] == 2
    assert row["witness_doc_count"] == 2
    assert row["witness_chunks"] == [
        {
            "rank": 1,
            "chunk_ref": "cr1:a",
            "filename": "a.md",
            "chunk_index": 0,
            "snippets": ["alpha"],
        },
        {
            "rank": 3,
            "chunk_ref": "cr1:b",
            "filename": "b.md",
            "chunk_index": 0,
            "snippets": ["beta"],
        },
    ]


def test_snippet_ranks_continue_after_witness_set_is_complete():
    item = _item(
        {"any_of": ["alpha", "beta", "gamma"], "any_of_min": 1},
        question_type="semantic",
    )
    chunks = [
        _chunk("alpha", "a.md", 0, "cr1:a"),
        _chunk("beta", "b.md", 0, "cr1:b"),
        _chunk("gamma", "c.md", 0, "cr1:c"),
    ]

    row = scoring.score_question(item, chunks, k=3)

    assert row["snippet_ranks"] == {"alpha": 1, "beta": 2, "gamma": 3}
    assert row["completion_rank"] == 1
    assert row["hop_spread"] == 0
    assert [witness["chunk_ref"] for witness in row["witness_chunks"]] == ["cr1:a"]


def test_uncompleted_question_keeps_partial_evidence_diagnostics():
    item = _item({"required": ["alpha", "missing"]})
    chunks = [
        _chunk("unrelated", "x.md", 0, "cr1:x"),
        _chunk("alpha", "a.md", 0, "cr1:a"),
    ]

    row = scoring.score_question(item, chunks, k=2)

    assert row["hit"] is False
    assert row["snippet_ranks"] == {"alpha": 2, "missing": None}
    assert row["completion_rank"] is None
    assert row["first_rank"] is None
    assert row["earliest_evidence_rank"] == 2
    assert row["hop_spread"] is None
    assert len(row["witness_chunks"]) == 1
    assert row["witness_doc_count"] == 1


def test_one_chunk_can_be_the_complete_witness_for_multiple_snippets():
    item = _item({"required": ["alpha", "beta"]})
    chunk = _chunk("alpha and beta", "a.md", 0, "cr1:a")

    row = scoring.score_question(item, [chunk], k=1)

    assert row["completion_rank"] == 1
    assert row["earliest_evidence_rank"] == 1
    assert row["hop_spread"] == 0
    assert len(row["witness_chunks"]) == 1
    assert row["witness_chunks"][0]["snippets"] == ["alpha", "beta"]
    assert row["witness_doc_count"] == 1


def test_aggregate_reports_mrr_for_all_types_and_multihop_health_metrics():
    hit = scoring.score_question(
        _item({"required": ["alpha", "beta"]}),
        [
            _chunk("alpha", "a.md", 0, "cr1:a"),
            _chunk("unrelated", "x.md", 0, "cr1:x"),
            _chunk("beta", "b.md", 0, "cr1:b"),
        ],
        k=3,
    )
    miss = scoring.score_question(
        _item({"required": ["alpha", "missing"]}),
        [_chunk("alpha", "a.md", 0, "cr1:a")],
        k=1,
    )
    exact = scoring.score_question(
        _item({"required": ["alpha"]}, question_type="exact"),
        [_chunk("alpha", "a.md", 0, "cr1:a")],
        k=1,
    )

    aggregate = scoring.aggregate([hit, miss, exact])

    assert aggregate["exact"]["MRR"] == 1.0
    assert aggregate["multihop"] == {
        "n": 2,
        "Hit": 0.5,
        "Coverage": 0.75,
        "FullyCovered": 0.5,
        "MRR": 0.167,
        "MeanHopSpread": 2.0,
        "MeanWitnessChunks": 1.5,
        "MultiDocRate": 0.5,
    }


def test_aggregate_mrr_uses_completion_rank_not_compatibility_alias():
    row = scoring.score_question(
        _item({"required": ["alpha"]}, question_type="exact"),
        [
            _chunk("unrelated", "x.md", 0, "cr1:x"),
            _chunk("alpha", "a.md", 0, "cr1:a"),
        ],
        k=2,
    )
    row["first_rank"] = 1

    aggregate = scoring.aggregate([row])

    assert aggregate["exact"]["MRR"] == 0.5


def test_terminal_report_includes_multihop_metrics_and_witness_refs(capsys, tmp_path):
    row = scoring.score_question(
        _item({"required": ["alpha", "beta"]}),
        [
            _chunk("alpha", "a.md", 0, "cr1:a"),
            _chunk("beta", "b.md", 0, "cr1:b"),
        ],
        k=2,
    )
    results = [
        {
            "k": 2,
            "by_type": scoring.aggregate([row]),
            "rows": [row],
        }
    ]

    score_run.print_report(results, tmp_path / "score.json")
    output = capsys.readouterr().out

    assert "MRR@2=" in output
    assert "MeanHopSpread@2=" in output
    assert "MeanWitnessChunks@2=" in output
    assert "MultiDocRate@2=" in output
    assert "snippets={'alpha': 1, 'beta': 2}" in output
    assert "witnesses=['cr1:a', 'cr1:b']" in output
