import copy
import json

import pytest
from langchain_core.documents import Document

from eval import run_retrieval, score_run


def _chunk(text, filename, chunk_index, chunk_id):
    return Document(
        page_content=text,
        metadata={
            "filename": filename,
            "chunk_index": chunk_index,
            "chunk_id": chunk_id,
        },
    )


@pytest.fixture
def run_fixture(tmp_path):
    alpha = _chunk("alpha evidence", "a.md", 0, "runtime-a")
    beta = _chunk("beta evidence", "b.md", 0, "runtime-b")
    unrelated = _chunk("unrelated private body", "c.md", 0, "runtime-c")
    chunks = [alpha, beta, unrelated]
    eval_set = [
        {
            "id": "q1",
            "question": "question one",
            "type": "exact",
            "answerable": True,
            "match": {"required": ["alpha", "beta"]},
        },
        {
            "id": "q2",
            "question": "question two",
            "type": "semantic",
            "answerable": True,
            "match": {"any_of": ["beta"]},
        },
    ]
    eval_path = tmp_path / "eval_set.json"
    eval_path.write_text(json.dumps(eval_set), encoding="utf-8")
    ranked = {
        "question one": [alpha, beta],
        "question two": [unrelated, beta],
    }

    artifact = run_retrieval.build_run_artifact(
        eval_set=eval_set,
        eval_set_path=eval_path,
        collection_chunks=chunks,
        retriever=lambda question, k: ranked[question][:k],
        retriever_name="fixture-retriever",
        k_values=[2, 1, 2],
        run_id="test-run",
        timestamp="2026-08-30T12:00:00+08:00",
        git={"commit": "abc123", "dirty": True},
        env={"collection_count": 3},
        corpus={"corpus_hash": "corpus-hash"},
    )
    run_path = tmp_path / "test-run" / "run.json"
    run_path.parent.mkdir()
    run_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return artifact, run_path, eval_path


def test_run_artifact_contains_replayable_contexts_and_manifest(run_fixture):
    artifact, _, _ = run_fixture

    assert artifact["k_values"] == [1, 2]
    assert artifact["chunk_manifest"]["chunk_count"] == 3
    assert len(artifact["retrievals"]) == 2
    assert all(len(item["contexts"]) == 2 for item in artifact["retrievals"])
    context = artifact["retrievals"][0]["contexts"][0]
    assert set(context) == {
        "rank",
        "chunk_id",
        "chunk_ref",
        "text_sha256",
        "filename",
        "chunk_index",
        "text",
    }
    assert context["chunk_ref"].startswith("cr1:")
    assert context["text"] == "alpha evidence"


def test_collect_retrievals_rejects_short_results(run_fixture):
    artifact, _, _ = run_fixture
    eval_set = [{"id": "q1", "question": "question one"}]

    with pytest.raises(RuntimeError, match="expected at least 2"):
        run_retrieval.collect_retrievals(
            eval_set,
            lambda question, k: [],
            2,
            artifact["chunk_manifest"],
        )


def test_score_run_is_deterministic_and_contains_no_context_text(run_fixture):
    _, run_path, eval_path = run_fixture
    score_path = run_path.with_name("score.json")

    score_run.score_run(run_path, eval_path, score_path)
    first_bytes = score_path.read_bytes()
    score_run.score_run(run_path, eval_path, score_path)
    second_bytes = score_path.read_bytes()
    score = json.loads(second_bytes)

    assert first_bytes == second_bytes
    assert score["source_run"]["run_id"] == "test-run"
    assert score["retriever"] == "fixture-retriever"
    assert score["corpus_hash"] == "corpus-hash"
    assert score["chunk_manifest_hash"]
    assert score["chunk_ref_version"] == 1
    assert score["scorer_version"] == 2
    assert score["results"][1]["rows"][0]["hit"] is True
    assert score["results"][1]["rows"][0]["first_rank"] == 2
    assert score["results"][1]["rows"][0]["completion_rank"] == 2
    assert score["results"][1]["rows"][0]["witness_chunks"][0]["chunk_ref"].startswith(
        "cr1:"
    )
    serialized = second_bytes.decode("utf-8")
    assert "alpha evidence" not in serialized
    assert "unrelated private body" not in serialized
    assert '"text"' not in serialized


def test_score_can_replay_new_match_rules_without_retrieval(run_fixture, tmp_path):
    artifact, run_path, eval_path = run_fixture
    eval_set = json.loads(eval_path.read_text(encoding="utf-8"))
    eval_set[0]["match"] = {"required": ["missing"]}
    rescored_eval_path = tmp_path / "rescored_eval.json"
    rescored_eval_path.write_text(json.dumps(eval_set), encoding="utf-8")

    score = score_run.build_score_artifact(
        artifact,
        eval_set,
        source_run_path=run_path,
        eval_set_path=rescored_eval_path,
    )

    assert score["results"][1]["rows"][0]["hit"] is False


@pytest.mark.parametrize("tamper", ["text", "chunk_ref", "manifest_hash"])
def test_score_rejects_tampered_run(run_fixture, tamper):
    artifact, run_path, eval_path = run_fixture
    tampered = copy.deepcopy(artifact)
    if tamper == "text":
        tampered["retrievals"][0]["contexts"][0]["text"] = "changed body"
    elif tamper == "chunk_ref":
        tampered["retrievals"][0]["contexts"][0]["chunk_ref"] = "cr1:unknown"
    else:
        tampered["chunk_manifest"]["chunk_manifest_hash"] = "0" * 64

    with pytest.raises(ValueError):
        score_run.build_score_artifact(
            tampered,
            json.loads(eval_path.read_text(encoding="utf-8")),
            source_run_path=run_path,
            eval_set_path=eval_path,
        )


def test_score_rejects_question_changes(run_fixture):
    artifact, run_path, eval_path = run_fixture
    changed_eval = json.loads(eval_path.read_text(encoding="utf-8"))
    changed_eval[0]["question"] = "a new retrieval query"

    with pytest.raises(ValueError, match="differs from the retrieval query"):
        score_run.build_score_artifact(
            artifact,
            changed_eval,
            source_run_path=run_path,
            eval_set_path=eval_path,
        )
