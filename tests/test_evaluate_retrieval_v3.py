from langchain_core.documents import Document

from eval import evaluate_retrieval_v3


def _chunk(text):
    return Document(page_content=text, metadata={})


def _item(match, question_type="exact"):
    return {
        "id": "q-test",
        "question": "unused by the scorer",
        "type": question_type,
        "match": match,
    }


def test_corpus_info_excludes_unsupported_files(tmp_path, monkeypatch):
    supported = tmp_path / "document.md"
    supported.write_text("test content", encoding="utf-8")
    (tmp_path / ".gitkeep").touch()
    (tmp_path / "notes.unsupported").write_text("ignored", encoding="utf-8")
    (tmp_path / "nested.md").mkdir()

    monkeypatch.setattr(evaluate_retrieval_v3, "CORPUS_DIR", tmp_path)

    info = evaluate_retrieval_v3.corpus_info()

    assert [entry["name"] for entry in info["files"]] == [supported.name]
    assert info["files"][0]["bytes"] == len("test content")
    assert info["files"][0]["sha256"] == evaluate_retrieval_v3.file_sha256(supported)


def test_required_evidence_accumulates_across_ranked_chunks_and_respects_k():
    item = _item({"required": ["证据甲", "证据乙"]})
    chunks = [_chunk("这里有证据甲"), _chunk("无关内容"), _chunk("这里有证据乙")]

    before_completion = evaluate_retrieval_v3.score_question(item, chunks, k=2)
    completed = evaluate_retrieval_v3.score_question(item, chunks, k=3)

    assert before_completion["hit"] is False
    assert before_completion["first_rank"] is None
    assert before_completion["coverage"] == 0.5
    assert before_completion["cov_required"] == 0.5
    assert before_completion["fully_covered"] is False

    assert completed["hit"] is True
    assert completed["first_rank"] == 3
    assert completed["coverage"] == 1.0
    assert completed["cov_required"] == 1.0
    assert completed["fully_covered"] is True


def test_any_of_defaults_to_one_match_and_counts_the_group_as_complete():
    item = _item({"any_of": ["方法甲", "方法乙", "方法丙"]}, "semantic")

    result = evaluate_retrieval_v3.score_question(
        item, [_chunk("笔记建议采用方法乙")], k=1
    )

    assert result["hit"] is True
    assert result["first_rank"] == 1
    assert result["coverage"] == 1.0
    assert result["cov_required"] == 1.0
    assert result["cov_any_of"] == 1.0
    assert result["has_required"] is False
    assert result["has_any_of"] is True


def test_any_of_min_uses_the_threshold_for_hit_and_coverage():
    item = _item(
        {
            "any_of": ["方法甲", "方法乙", "方法丙"],
            "any_of_min": 2,
        }
    )
    chunks = [_chunk("先采用方法甲"), _chunk("再补充方法丙")]

    below_threshold = evaluate_retrieval_v3.score_question(item, chunks, k=1)
    at_threshold = evaluate_retrieval_v3.score_question(item, chunks, k=2)

    assert below_threshold["hit"] is False
    assert below_threshold["first_rank"] is None
    assert below_threshold["coverage"] == 0.5
    assert below_threshold["cov_any_of"] == 0.5

    assert at_threshold["hit"] is True
    assert at_threshold["first_rank"] == 2
    assert at_threshold["coverage"] == 1.0
    assert at_threshold["cov_any_of"] == 1.0


def test_required_and_any_of_groups_must_both_be_satisfied():
    item = _item(
        {
            "required": ["问题原因"],
            "any_of": ["方法甲", "方法乙"],
            "any_of_min": 1,
        },
        "semantic",
    )
    chunks = [_chunk("建议使用方法甲"), _chunk("问题原因在这里")]

    only_any_of = evaluate_retrieval_v3.score_question(item, chunks, k=1)
    both_groups = evaluate_retrieval_v3.score_question(item, chunks, k=2)

    assert only_any_of["hit"] is False
    assert only_any_of["first_rank"] is None
    assert only_any_of["cov_required"] == 0.0
    assert only_any_of["cov_any_of"] == 1.0
    assert only_any_of["coverage"] == 0.5

    assert both_groups["hit"] is True
    assert both_groups["first_rank"] == 2
    assert both_groups["coverage"] == 1.0


def test_matching_normalizes_only_whitespace_and_case():
    snippets = ["MRR @ K"]

    equivalent = evaluate_retrieval_v3.hits_in_chunk(
        _chunk("The metric is mrr@k."), snippets
    )
    paraphrase = evaluate_retrieval_v3.hits_in_chunk(
        _chunk("使用前 K 项平均倒数排名"), snippets
    )

    assert equivalent == {"MRR @ K"}
    assert paraphrase == set()
    assert evaluate_retrieval_v3._norm(" MRR \n@\tK ") == "mrr@k"


def test_coverage_averages_required_and_any_of_group_progress_before_rounding():
    match = {
        "required": ["必需甲", "必需乙", "必需丙"],
        "any_of": ["可选甲", "可选乙", "可选丙"],
        "any_of_min": 2,
    }
    found = {"必需甲", "可选乙"}

    coverage = evaluate_retrieval_v3.coverage_scores(found, match)

    assert coverage == {"required": 0.333, "any_of": 0.5, "overall": 0.417}


def test_one_chunk_can_contribute_multiple_required_snippets():
    item = _item({"required": ["RRF", "1/(k+rank)"]})

    result = evaluate_retrieval_v3.score_question(
        item, [_chunk("RRF 的公式是 1/(k+rank)")], k=1
    )

    assert result["hit"] is True
    assert result["first_rank"] == 1
    assert result["coverage"] == 1.0


def test_evaluate_sweep_retrieves_once_at_max_k_and_scores_ranked_prefixes():
    item = _item({"required": ["证据甲", "证据乙"]})
    calls = []

    def retriever(question, k):
        calls.append((question, k))
        return [_chunk("证据甲"), _chunk("无关内容"), _chunk("证据乙")]

    results = evaluate_retrieval_v3.evaluate_sweep(retriever, [item], [1, 3])

    assert calls == [(item["question"], 3)]
    assert [result["k"] for result in results] == [1, 3]
    assert results[0]["rows"][0]["hit"] is False
    assert results[0]["rows"][0]["first_rank"] is None
    assert results[1]["rows"][0]["hit"] is True
    assert results[1]["rows"][0]["first_rank"] == 3
