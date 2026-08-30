"""Validate evaluation questions against the persisted evaluation chunks.

The generated owner report is derived from snippet substring matching. It is
useful input for later human qrels annotation, but is not itself gold qrels.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

sys.path.append(str(Path(__file__).resolve().parents[1]))

import chromadb  # noqa: E402
from langchain_core.documents import Document  # noqa: E402

from app.core.config import settings  # noqa: E402
from eval import harness, scoring  # noqa: E402

SCHEMA_VERSION = 1
REPORT_TYPE = "derived_evidence_owners"
QUESTION_TYPES = {"exact", "semantic", "multihop"}


@dataclass(frozen=True)
class ChunkRecord:
    """A chunk plus its stable, text-free report identity."""

    document: Any
    chunk_ref: str
    filename: str
    chunk_index: int
    text_sha256: str

    def owner(self) -> dict[str, Any]:
        return {
            "chunk_ref": self.chunk_ref,
            "filename": self.filename,
            "chunk_index": self.chunk_index,
            "text_sha256": self.text_sha256,
        }


def _issue(code: str, question_id: str, message: str) -> dict[str, str]:
    return {"code": code, "question_id": question_id, "message": message}


def _stable_records(
    chunks: Sequence[Any], manifest: Mapping[str, Any]
) -> list[ChunkRecord]:
    entries = {
        (entry["filename"], entry["chunk_index"]): entry for entry in manifest["chunks"]
    }
    records = []
    for chunk in chunks:
        metadata = chunk.metadata
        location = (metadata["filename"], metadata["chunk_index"])
        entry = entries[location]
        records.append(
            ChunkRecord(
                document=chunk,
                chunk_ref=entry["chunk_ref"],
                filename=entry["filename"],
                chunk_index=entry["chunk_index"],
                text_sha256=entry["text_sha256"],
            )
        )
    return sorted(records, key=lambda record: record.chunk_ref)


def _valid_snippet_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and all(isinstance(item, str) and bool(item.strip()) for item in value)
        and len(value) == len(set(value))
    )


def _schema_errors(
    item: Any,
    index: int,
    seen_ids: set[str],
    require_explicit_answerable: bool,
) -> tuple[str, bool, list[str], list[str], int, list[dict[str, str]]]:
    fallback_id = f"<item-{index}>"
    if not isinstance(item, dict):
        return (
            fallback_id,
            True,
            [],
            [],
            1,
            [_issue("E4", fallback_id, "question must be a JSON object")],
        )

    raw_id = item.get("id")
    question_id = raw_id if isinstance(raw_id, str) and raw_id else fallback_id
    errors = []
    if not isinstance(raw_id, str) or not raw_id:
        errors.append(_issue("E4", question_id, "id must be a non-empty string"))
    elif raw_id in seen_ids:
        errors.append(_issue("E4", question_id, "id must be unique"))
    else:
        seen_ids.add(raw_id)

    if not isinstance(item.get("question"), str) or not item["question"].strip():
        errors.append(_issue("E4", question_id, "question must be a non-empty string"))
    if item.get("type") not in QUESTION_TYPES:
        errors.append(
            _issue(
                "E4",
                question_id,
                "type must be one of exact, semantic, or multihop",
            )
        )

    has_answerable = "answerable" in item
    answerable = item.get("answerable", True)
    if require_explicit_answerable and not has_answerable:
        errors.append(_issue("E4", question_id, "answerable must be explicit in v3"))
    if has_answerable and not isinstance(answerable, bool):
        errors.append(_issue("E4", question_id, "answerable must be boolean"))
        answerable = True

    match = item.get("match")
    if not isinstance(match, dict):
        errors.append(_issue("E4", question_id, "match must be an object"))
        match = {}
    required = match.get("required", [])
    any_of = match.get("any_of", [])
    if not _valid_snippet_list(required):
        errors.append(
            _issue(
                "E4",
                question_id,
                "match.required must be a list of unique non-empty strings",
            )
        )
        required = []
    if not _valid_snippet_list(any_of):
        errors.append(
            _issue(
                "E4",
                question_id,
                "match.any_of must be a list of unique non-empty strings",
            )
        )
        any_of = []

    any_of_min = match.get("any_of_min", 1)
    if (
        isinstance(any_of_min, bool)
        or not isinstance(any_of_min, int)
        or any_of_min < 1
        or (any_of and any_of_min > len(any_of))
        or (not any_of and "any_of_min" in match)
    ):
        errors.append(
            _issue(
                "E4",
                question_id,
                "any_of_min must be between 1 and the number of any_of snippets",
            )
        )
        any_of_min = 1

    if answerable and not required and not any_of:
        errors.append(
            _issue(
                "E4",
                question_id,
                "answerable questions require required or any_of snippets",
            )
        )
    if answerable is False:
        errors.append(
            _issue(
                "E5",
                question_id,
                "answerable=false is not supported by the current scorer",
            )
        )

    return question_id, answerable, required, any_of, any_of_min, errors


def _minimum_covers(
    required: Sequence[str],
    any_of: Sequence[str],
    any_of_min: int,
    owners: Mapping[str, frozenset[str]],
) -> list[frozenset[str]]:
    """Return every minimum-cardinality chunk set satisfying snippet rules."""
    if any(not owners.get(snippet) for snippet in [*required, *any_of]):
        return []

    candidate_refs = sorted(set().union(*(owners[snippet] for snippet in owners)))
    required_set = set(required)
    any_of_set = set(any_of)
    required_by_ref = {
        ref: {snippet for snippet in required if ref in owners[snippet]}
        for ref in candidate_refs
    }
    any_by_ref = {
        ref: {snippet for snippet in any_of if ref in owners[snippet]}
        for ref in candidate_refs
    }
    best_size: int | None = None
    solutions: set[frozenset[str]] = set()
    visited: set[frozenset[str]] = set()

    def search(selected: frozenset[str]) -> None:
        nonlocal best_size, solutions
        if selected in visited:
            return
        visited.add(selected)

        found_required = set().union(*(required_by_ref[ref] for ref in selected), set())
        found_any = set().union(*(any_by_ref[ref] for ref in selected), set())
        satisfied = required_set <= found_required and (
            not any_of or len(found_any) >= any_of_min
        )
        if satisfied:
            size = len(selected)
            if best_size is None or size < best_size:
                best_size = size
                solutions = {selected}
            elif size == best_size:
                solutions.add(selected)
            return
        if best_size is not None and len(selected) >= best_size:
            return

        missing_required = required_set - found_required
        if missing_required:
            target = min(
                missing_required,
                key=lambda snippet: (len(owners[snippet] - selected), snippet),
            )
            next_refs = owners[target] - selected
        else:
            missing_any = any_of_set - found_any
            next_refs = {
                ref
                for snippet in missing_any
                for ref in owners[snippet]
                if ref not in selected
            }
        for ref in sorted(next_refs):
            search(selected | {ref})

    search(frozenset())
    return sorted(solutions, key=lambda cover: tuple(sorted(cover)))


def validate_eval_set(
    eval_set: Sequence[Any],
    chunks: Sequence[Any],
    *,
    eval_set_sha256: str,
    corpus_hash: str,
    require_explicit_answerable: bool,
    splitter: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate questions and return a text-free derived owner report."""
    manifest = harness.build_chunk_manifest(chunks, splitter)
    records = _stable_records(chunks, manifest)
    record_by_ref = {record.chunk_ref: record for record in records}
    normalized_chunks = {
        record.chunk_ref: scoring._norm(record.document.page_content)
        for record in records
    }
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    questions = []
    seen_ids: set[str] = set()

    for index, item in enumerate(eval_set):
        (
            question_id,
            answerable,
            required,
            any_of,
            any_of_min,
            item_errors,
        ) = _schema_errors(item, index, seen_ids, require_explicit_answerable)
        errors.extend(item_errors)
        question_type = item.get("type") if isinstance(item, dict) else None
        question = item.get("question", "") if isinstance(item, dict) else ""
        snippets = [("required", value) for value in required]
        snippets += [("any_of", value) for value in any_of]
        owner_refs: dict[str, frozenset[str]] = {}
        snippet_reports = []

        for kind, snippet in snippets:
            normalized = scoring._norm(snippet)
            refs = frozenset(
                ref
                for ref, content in normalized_chunks.items()
                if normalized in content
            )
            owner_refs[snippet] = refs
            if not refs:
                errors.append(
                    _issue("E1", question_id, f"snippet_not_found: {snippet!r}")
                )
            if normalized in scoring._norm(question):
                errors.append(_issue("E2", question_id, f"query_leak: {snippet!r}"))
            if len(refs) > 3:
                warnings.append(
                    _issue(
                        "W1",
                        question_id,
                        f"low_specificity: {snippet!r} has {len(refs)} owners",
                    )
                )
            snippet_reports.append(
                {
                    "kind": kind,
                    "snippet": snippet,
                    "owner_count": len(refs),
                    "owners": [record_by_ref[ref].owner() for ref in sorted(refs)],
                }
            )

        for left_index, left in enumerate(required):
            for right in required[left_index + 1 :]:
                left_owners = owner_refs.get(left, frozenset())
                right_owners = owner_refs.get(right, frozenset())
                if (
                    left_owners
                    and right_owners
                    and (left_owners <= right_owners or right_owners <= left_owners)
                ):
                    warnings.append(
                        _issue(
                            "W2",
                            question_id,
                            f"redundant_evidence: {left!r} and {right!r} "
                            "have identical or nested owner sets",
                        )
                    )

        covers = (
            _minimum_covers(required, any_of, any_of_min, owner_refs)
            if answerable and snippets and all(owner_refs.values())
            else []
        )
        cover_reports = []
        for cover in covers:
            cover_records = [record_by_ref[ref] for ref in sorted(cover)]
            documents = sorted({record.filename for record in cover_records})
            cover_reports.append(
                {
                    "chunk_refs": [record.chunk_ref for record in cover_records],
                    "chunk_count": len(cover_records),
                    "documents": documents,
                    "document_count": len(documents),
                }
            )

        if covers and question_type == "multihop":
            if len(covers[0]) < 2 or any(
                cover["document_count"] < 2 for cover in cover_reports
            ):
                errors.append(
                    _issue(
                        "E3",
                        question_id,
                        "multihop_degenerate: every minimum cover must use at "
                        "least 2 chunks across at least 2 documents",
                    )
                )
        if covers and question_type in {"exact", "semantic"} and len(covers[0]) > 1:
            warnings.append(
                _issue(
                    "W3",
                    question_id,
                    f"bucket_mismatch: minimum cover uses {len(covers[0])} chunks",
                )
            )

        if isinstance(item, dict) and "gold_docs" in item and covers:
            declared = item["gold_docs"]
            declared_set = (
                set(declared)
                if isinstance(declared, list)
                and all(isinstance(value, str) for value in declared)
                else set()
            )
            actual_sets = [set(cover["documents"]) for cover in cover_reports]
            if not declared_set or any(
                actual != declared_set for actual in actual_sets
            ):
                warnings.append(
                    _issue(
                        "W4",
                        question_id,
                        "gold_docs_mismatch: declared documents differ from a "
                        "minimum-cover document set",
                    )
                )

        questions.append(
            {
                "id": question_id,
                "type": question_type,
                "answerable": answerable,
                "snippets": snippet_reports,
                "minimum_covers": cover_reports,
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "report_type": REPORT_TYPE,
        "derived": True,
        "notice": (
            "Automatically derived from snippet substring owners; not human-"
            "reviewed gold qrels and must not be used directly as qrels_hit. "
            "It may be used as candidate input for provisional qrels annotation. "
            "Regenerate whenever a hash or version changes."
        ),
        "eval_set_sha256": eval_set_sha256,
        "corpus_hash": corpus_hash,
        "chunk_manifest_hash": manifest["chunk_manifest_hash"],
        "chunk_ref_version": harness.CHUNK_REF_VERSION,
        "matcher_version": scoring.MATCHER_VERSION,
        "summary": {
            "questions": len(eval_set),
            "errors": len(errors),
            "warnings": len(warnings),
        },
        "errors": errors,
        "warnings": warnings,
        "questions": questions,
    }


def print_report(report: Mapping[str, Any]) -> None:
    """Print the validation result using stable chunk references."""
    errors_by_question: dict[str, list[Mapping[str, Any]]] = {}
    warnings_by_question: dict[str, list[Mapping[str, Any]]] = {}
    for issue in report["errors"]:
        errors_by_question.setdefault(issue["question_id"], []).append(issue)
    for issue in report["warnings"]:
        warnings_by_question.setdefault(issue["question_id"], []).append(issue)

    for question in report["questions"]:
        question_id = question["id"]
        print(
            f"{question_id}  {question['type']}  "
            f"answerable={str(question['answerable']).lower()}"
        )
        for snippet in question["snippets"]:
            locations = ", ".join(
                f"{owner['filename']}#{owner['chunk_index']} {owner['chunk_ref']}"
                for owner in snippet["owners"]
            )
            print(
                f"  [{snippet['kind'].upper()}] {snippet['snippet']}  "
                f"n={snippet['owner_count']}  {locations or '-'}"
            )
        covers = question["minimum_covers"]
        if covers:
            print(f"  minimum covers ({len(covers)}):")
            for cover in covers:
                print(
                    "    "
                    + ", ".join(cover["chunk_refs"])
                    + f"  chunks={cover['chunk_count']} docs={cover['document_count']}"
                )
        else:
            print("  minimum covers: none")
        for issue in errors_by_question.get(question_id, []):
            print(f"  ERROR {issue['code']}: {issue['message']}")
        for issue in warnings_by_question.get(question_id, []):
            print(f"  WARNING {issue['code']}: {issue['message']}")

    summary = report["summary"]
    print(
        f"\nSummary: {summary['questions']} questions, "
        f"{summary['errors']} errors, {summary['warnings']} warnings"
    )


def _load_collection_chunks() -> tuple[list[Document], dict[str, Any]]:
    corpus = harness.corpus_info()
    client = chromadb.PersistentClient(path=settings.chroma_db_path)
    collection = client.get_collection(harness.EVAL_COLLECTION)
    harness.validate_collection(SimpleNamespace(_collection=collection), corpus)
    raw = collection.get(include=["documents", "metadatas"])
    documents = raw.get("documents") or []
    metadatas = raw.get("metadatas") or []
    chunks = [
        Document(page_content=text, metadata=metadata)
        for text, metadata in zip(documents, metadatas)
    ]
    return chunks, corpus


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-set", required=True, type=Path)
    parser.add_argument("--json", type=Path, dest="json_path")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    eval_set_path = args.eval_set.resolve()
    eval_set = harness.load_eval_set(eval_set_path)
    chunks, corpus = _load_collection_chunks()
    report = validate_eval_set(
        eval_set,
        chunks,
        eval_set_sha256=harness.file_sha256(eval_set_path),
        corpus_hash=corpus["corpus_hash"],
        require_explicit_answerable=eval_set_path.name == "eval_set_v3.json",
    )
    print_report(report)
    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"JSON report: {args.json_path}")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
