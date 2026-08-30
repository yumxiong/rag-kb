import copy
import json

import pytest

from eval import compare_runs


def _row(
    question_id,
    *,
    hit,
    rank,
    coverage,
    question_type="exact",
    hop_spread=None,
):
    return {
        "id": question_id,
        "type": question_type,
        "hit": hit,
        "completion_rank": rank,
        "first_rank": rank,
        "coverage": coverage,
        "hop_spread": hop_spread,
    }


def _score(rows, *, retriever="vector", run_id="run-a"):
    return {
        "schema_version": 1,
        "source_run": {"run_id": run_id, "path": f"{run_id}/run.json"},
        "retriever": retriever,
        "eval_set": {"path": "eval/eval_set_v3.json", "sha256": "eval-hash"},
        "corpus_hash": "corpus-hash",
        "chunk_manifest_hash": "manifest-hash",
        "chunk_ref_version": 1,
        "scorer_version": 2,
        "results": [{"k": 5, "by_type": {}, "rows": rows}],
    }


@pytest.mark.parametrize(
    "rescued,harmed,expected",
    [
        (0, 0, 1.0),
        (5, 2, 0.453125),
        (7, 1, 0.0703125),
        (8, 1, 0.0390625),
        (10, 2, 0.03857421875),
    ],
)
def test_exact_mcnemar_reference_values(rescued, harmed, expected):
    assert compare_runs.exact_mcnemar(rescued, harmed) == expected


def test_paired_bootstrap_is_deterministic_and_preserves_pairing():
    first = compare_runs.paired_bootstrap([0.0, 1.0], [0.1, 1.1])
    second = compare_runs.paired_bootstrap([0.0, 1.0], [0.1, 1.1])

    assert first == second
    assert first["delta"] == pytest.approx(0.1)
    assert first["ci95"] == pytest.approx([0.1, 0.1])
    assert first["statistically_distinguishable"] is True


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("eval_set", {"sha256": "other"}, "eval_set.sha256 mismatch"),
        ("corpus_hash", "other", "corpus_hash mismatch"),
        ("chunk_manifest_hash", "other", "chunk_manifest_hash mismatch"),
        ("scorer_version", 99, "scorer_version mismatch"),
    ],
)
def test_comparison_rejects_incompatible_scores(field, value, message):
    row = _row("q1", hit=True, rank=1, coverage=1.0)
    score_a = _score([row])
    score_b = copy.deepcopy(score_a)
    score_b[field] = value

    with pytest.raises(ValueError, match=message):
        compare_runs.compare_scores(score_a, score_b)


def test_same_score_self_check_has_zero_deltas_and_small_sample_warning():
    rows = [
        _row(f"q{i}", hit=i % 2 == 0, rank=1 if i % 2 == 0 else None, coverage=0.5)
        for i in range(1, 9)
    ]
    score = _score(rows)

    report = compare_runs.compare_scores(score, score)

    assert report["n"] == 8
    assert report["small_sample"] is True
    assert report["metrics"]["mrr"]["delta"] == 0.0
    assert report["metrics"]["mrr"]["ci95"] == [0.0, 0.0]
    assert report["metrics"]["coverage"]["ci95"] == [0.0, 0.0]
    assert report["metrics"]["hit"]["rescued"] == 0
    assert report["metrics"]["hit"]["harmed"] == 0
    assert report["metrics"]["hit"]["p_value"] == 1.0


def test_comparison_pairs_rows_by_id_and_uses_completion_rank_for_mrr():
    rows_a = [
        _row("q1", hit=True, rank=2, coverage=0.5),
        _row("q2", hit=False, rank=None, coverage=0.0),
    ]
    rows_b = [
        _row("q2", hit=True, rank=4, coverage=1.0),
        _row("q1", hit=True, rank=1, coverage=1.0),
    ]
    rows_a[0]["first_rank"] = 1

    report = compare_runs.compare_scores(_score(rows_a), _score(rows_b))

    assert report["metrics"]["hit"]["rescued"] == 1
    assert report["metrics"]["hit"]["harmed"] == 0
    assert report["metrics"]["mrr"]["mean_a"] == 0.25
    assert report["metrics"]["mrr"]["mean_b"] == 0.625
    assert report["metrics"]["mrr"]["delta"] == 0.375


def test_hop_spread_compares_only_jointly_hit_multihop_questions():
    rows_a = [
        _row(
            "q1",
            hit=True,
            rank=3,
            coverage=1.0,
            question_type="multihop",
            hop_spread=2,
        ),
        _row(
            "q2",
            hit=False,
            rank=None,
            coverage=0.5,
            question_type="multihop",
        ),
    ]
    rows_b = [
        _row(
            "q1",
            hit=True,
            rank=2,
            coverage=1.0,
            question_type="multihop",
            hop_spread=1,
        ),
        _row(
            "q2",
            hit=True,
            rank=4,
            coverage=1.0,
            question_type="multihop",
            hop_spread=3,
        ),
    ]

    report = compare_runs.compare_scores(_score(rows_a), _score(rows_b))

    assert report["metrics"]["hop_spread"]["n"] == 1
    assert report["metrics"]["hop_spread"]["delta"] == -1.0


def test_cli_highlights_one_metric_and_labels_diagnostics(tmp_path, capsys):
    rows = [_row("q1", hit=True, rank=1, coverage=1.0)]
    score_a = _score(rows, retriever="vector", run_id="run-a")
    score_b = _score(rows, retriever="bm25", run_id="run-b")
    path_a = tmp_path / "a.json"
    path_b = tmp_path / "b.json"
    path_a.write_text(json.dumps(score_a), encoding="utf-8")
    path_b.write_text(json.dumps(score_b), encoding="utf-8")

    assert (
        compare_runs.main(
            [str(path_a), str(path_b), "--k", "5", "--headline", "coverage"]
        )
        == 0
    )
    output = capsys.readouterr().out

    assert output.count("HEADLINE") == 1
    assert "HEADLINE\n  Coverage:" in output
    assert "DIAGNOSTICS" in output
    assert "rescued=0 harmed=0 McNemar p=1.000" in output
    assert "95% CI=[0.000, 0.000]" in output
    assert "WARNING: small sample (n=1 < 30)" in output


def test_cli_rejects_manifest_mismatch_with_clear_error(tmp_path, capsys):
    rows = [_row("q1", hit=True, rank=1, coverage=1.0)]
    score_a = _score(rows)
    score_b = copy.deepcopy(score_a)
    score_b["chunk_manifest_hash"] = "different-manifest"
    path_a = tmp_path / "a.json"
    path_b = tmp_path / "b.json"
    path_a.write_text(json.dumps(score_a), encoding="utf-8")
    path_b.write_text(json.dumps(score_b), encoding="utf-8")

    assert compare_runs.main([str(path_a), str(path_b)]) == 1
    error = capsys.readouterr().err

    assert "ERROR: chunk_manifest_hash mismatch" in error
