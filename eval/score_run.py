"""Score a saved retrieval run without querying the retrieval system."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

sys.path.append(str(Path(__file__).resolve().parents[1]))

from langchain_core.documents import Document  # noqa: E402

from eval import harness, scoring  # noqa: E402

SCORE_SCHEMA_VERSION = 1


def _relative_to_root(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(harness.ROOT).as_posix()
    except ValueError:
        return str(resolved)


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _validate_manifest(manifest: Any) -> dict[str, Mapping[str, Any]]:
    if not isinstance(manifest, dict):
        raise ValueError("run.json has no chunk_manifest")
    if manifest.get("chunk_ref_version") != harness.CHUNK_REF_VERSION:
        raise ValueError("run.json uses an unsupported chunk_ref_version")
    expected_hash = harness.chunk_manifest_hash(manifest)
    if manifest.get("chunk_manifest_hash") != expected_hash:
        raise ValueError("run.json chunk_manifest_hash is invalid")
    entries = manifest.get("chunks")
    if not isinstance(entries, list) or len(entries) != manifest.get("chunk_count"):
        raise ValueError("run.json chunk manifest count is invalid")
    by_ref = {}
    locations = set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("chunk_ref"), str):
            raise ValueError("run.json contains an invalid chunk manifest entry")
        try:
            expected_ref = harness.make_chunk_ref(
                entry["filename"], entry["chunk_index"], entry["text_sha256"]
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                "run.json contains an invalid chunk manifest entry"
            ) from exc
        if entry["chunk_ref"] != expected_ref:
            raise ValueError("run.json contains an invalid chunk_ref")
        if entry["chunk_ref"] in by_ref:
            raise ValueError("run.json contains duplicate chunk_ref values")
        location = (entry["filename"], entry["chunk_index"])
        if location in locations:
            raise ValueError("run.json contains duplicate chunk locations")
        locations.add(location)
        by_ref[entry["chunk_ref"]] = entry
    return by_ref


def _contexts_as_documents(
    retrieval: Mapping[str, Any],
    manifest_by_ref: Mapping[str, Mapping[str, Any]],
) -> list[Document]:
    contexts = retrieval.get("contexts")
    k_max = retrieval.get("k_max")
    if not isinstance(contexts, list) or not isinstance(k_max, int):
        raise ValueError(f"retrieval {retrieval.get('id')!r} is malformed")
    if len(contexts) < k_max:
        raise ValueError(f"retrieval {retrieval.get('id')!r} has too few contexts")

    documents = []
    for expected_rank, context in enumerate(contexts, start=1):
        if not isinstance(context, dict) or context.get("rank") != expected_rank:
            raise ValueError(
                f"retrieval {retrieval.get('id')!r} has non-contiguous ranks"
            )
        text = context.get("text")
        chunk_ref = context.get("chunk_ref")
        chunk_id = context.get("chunk_id")
        if not isinstance(text, str) or not text:
            raise ValueError(f"context at rank {expected_rank} has empty text")
        if not isinstance(chunk_id, str) or not chunk_id:
            raise ValueError(f"context at rank {expected_rank} has no chunk_id")
        if chunk_ref not in manifest_by_ref:
            raise ValueError(f"context at rank {expected_rank} has unknown chunk_ref")
        entry = manifest_by_ref[chunk_ref]
        digest = harness.text_sha256(text)
        expected_fields = {
            "text_sha256": digest,
            "filename": entry["filename"],
            "chunk_index": entry["chunk_index"],
        }
        if digest != entry["text_sha256"] or any(
            context.get(key) != value for key, value in expected_fields.items()
        ):
            raise ValueError(
                f"context at rank {expected_rank} differs from its manifest entry"
            )
        documents.append(
            Document(
                page_content=text,
                metadata={
                    "chunk_id": chunk_id,
                    "chunk_ref": chunk_ref,
                    "text_sha256": digest,
                    "filename": entry["filename"],
                    "chunk_index": entry["chunk_index"],
                    "rank": expected_rank,
                },
            )
        )
    return documents


def build_score_artifact(
    run_artifact: Mapping[str, Any],
    eval_set: Sequence[Mapping[str, Any]],
    *,
    source_run_path: Path,
    eval_set_path: Path,
) -> dict[str, Any]:
    """Replay snippet scoring from a run artifact without retrieval access."""
    if run_artifact.get("schema_version") != 1:
        raise ValueError("unsupported run.json schema_version")
    manifest = run_artifact.get("chunk_manifest")
    manifest_by_ref = _validate_manifest(manifest)
    retriever_name = run_artifact.get("retriever")
    if not isinstance(retriever_name, str) or not retriever_name:
        raise ValueError("run.json has no retriever name")
    corpus = run_artifact.get("corpus")
    if not isinstance(corpus, dict) or not isinstance(corpus.get("corpus_hash"), str):
        raise ValueError("run.json has no corpus_hash")

    k_values = run_artifact.get("k_values")
    if (
        not isinstance(k_values, list)
        or not k_values
        or any(isinstance(k, bool) or not isinstance(k, int) or k < 1 for k in k_values)
    ):
        raise ValueError("run.json has invalid k_values")
    if k_values != sorted(set(k_values)):
        raise ValueError("run.json k_values must be sorted and unique")

    retrieval_list = run_artifact.get("retrievals")
    if not isinstance(retrieval_list, list):
        raise ValueError("run.json has no retrievals")
    retrievals = {}
    for retrieval in retrieval_list:
        if not isinstance(retrieval, dict) or not isinstance(retrieval.get("id"), str):
            raise ValueError("run.json contains a malformed retrieval")
        if retrieval["id"] in retrievals:
            raise ValueError("run.json contains duplicate retrieval IDs")
        retrievals[retrieval["id"]] = retrieval

    eval_ids = [item.get("id") for item in eval_set]
    if len(eval_ids) != len(set(eval_ids)) or set(eval_ids) != set(retrievals):
        raise ValueError("eval set IDs do not match run.json retrieval IDs")

    pools = {}
    for item in eval_set:
        retrieval = retrievals[item["id"]]
        if item.get("question") != retrieval.get("question"):
            raise ValueError(
                f"eval question {item['id']!r} differs from the retrieval query"
            )
        retrieval_k_max = retrieval.get("k_max")
        if (
            isinstance(retrieval_k_max, bool)
            or not isinstance(retrieval_k_max, int)
            or retrieval_k_max < max(k_values)
        ):
            raise ValueError(f"retrieval {item['id']!r} has insufficient k_max")
        pools[item["id"]] = _contexts_as_documents(retrieval, manifest_by_ref)

    results = []
    for k in k_values:
        rows = [scoring.score_question(item, pools[item["id"]], k) for item in eval_set]
        results.append({"k": k, "by_type": scoring.aggregate(rows), "rows": rows})

    return {
        "schema_version": SCORE_SCHEMA_VERSION,
        "source_run": {
            "run_id": run_artifact.get("run_id"),
            "path": _relative_to_root(source_run_path),
        },
        "retriever": retriever_name,
        "eval_set": {
            "path": _relative_to_root(eval_set_path),
            "sha256": harness.file_sha256(eval_set_path),
        },
        "corpus_hash": corpus["corpus_hash"],
        "chunk_manifest_hash": manifest["chunk_manifest_hash"],
        "chunk_ref_version": manifest["chunk_ref_version"],
        "scorer_version": scoring.SCORER_VERSION,
        "results": results,
    }


def _fmt_sub_cov(value: float, applicable: bool) -> str:
    return "-" if not applicable else str(value)


def print_report(results: Sequence[Mapping[str, Any]], artifact_path: Path) -> None:
    """Print aggregate metrics and per-question retrieval diagnostics."""
    for result in results:
        k = result["k"]
        for question_type, entry in result["by_type"].items():
            fields = [
                f"n={entry['n']}",
                f"Hit@{k}={entry['Hit']}",
                f"MRR@{k}={entry['MRR']}",
                f"Coverage@{k}={entry['Coverage']}",
            ]
            if question_type == "multihop":
                fields.extend(
                    [
                        f"FullyCovered@{k}={entry['FullyCovered']}",
                        f"MeanHopSpread@{k}={entry['MeanHopSpread']}",
                        f"MeanWitnessChunks@{k}={entry['MeanWitnessChunks']}",
                        f"MultiDocRate@{k}={entry['MultiDocRate']}",
                    ]
                )
            print(f"[{question_type}] " + "  ".join(fields))

    max_result = max(results, key=lambda result: result["k"])
    print(f"\nPer question (k={max_result['k']}):")
    print(
        f"{'id':<4} {'type':<9} {'hit':<5} {'rank':<5} "
        f"{'cov':<6} {'req':<6} {'any':<6}"
    )
    for row in max_result["rows"]:
        print(
            f"{row['id']:<4} {row['type']:<9} {str(row['hit']):<5} "
            f"{row['completion_rank'] or '-':<5} {row['coverage']:<6} "
            f"{_fmt_sub_cov(row['cov_required'], row['has_required']):<6} "
            f"{_fmt_sub_cov(row['cov_any_of'], row['has_any_of']):<6}"
        )
        if row["type"] == "multihop":
            witness_refs = [
                witness.get("chunk_ref") or witness.get("chunk_id") or "-"
                for witness in row["witness_chunks"]
            ]
            print(
                f"     snippets={row['snippet_ranks']} "
                f"witnesses={witness_refs} docs={row['witness_doc_count']} "
                f"spread={row['hop_spread']}"
            )
    print(f"\nScore artifact: {artifact_path}")


def score_run(
    run_path: Path,
    eval_set_path: Path | None = None,
    output_path: Path | None = None,
) -> Path:
    """Load, score, and deterministically write one run artifact."""
    run_path = run_path.resolve()
    run_artifact = _load_json(run_path)
    if eval_set_path is None:
        run_eval = run_artifact.get("eval_set")
        if not isinstance(run_eval, dict) or not isinstance(run_eval.get("path"), str):
            raise ValueError("run.json has no eval_set path")
        candidate = Path(run_eval["path"])
        eval_set_path = (
            candidate if candidate.is_absolute() else harness.ROOT / candidate
        )
    eval_set_path = eval_set_path.resolve()
    eval_set = harness.load_eval_set(eval_set_path)
    artifact = build_score_artifact(
        run_artifact,
        eval_set,
        source_run_path=run_path,
        eval_set_path=eval_set_path,
    )
    output_path = (output_path or run_path.with_name("score.json")).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Score artifact: {output_path}")
    return output_path


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_path", type=Path)
    parser.add_argument("--eval-set", type=Path, dest="eval_set_path")
    parser.add_argument("--output", type=Path, dest="output_path")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    score_run(args.run_path, args.eval_set_path, args.output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
