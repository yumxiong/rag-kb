import hashlib
from types import SimpleNamespace

import pytest
from langchain_core.documents import Document

from eval import harness

SPLITTER = {
    "name": "RecursiveCharacterTextSplitter",
    "chunk_size": 1000,
    "chunk_overlap": 200,
    "separators": ["\n\n", "\n", " ", ""],
}


def _chunk(text, filename="notes.md", chunk_index=0, **metadata):
    return Document(
        page_content=text,
        metadata={
            "filename": filename,
            "chunk_index": chunk_index,
            **metadata,
        },
    )


def test_chunk_text_hash_normalizes_only_line_endings():
    windows_text = "first\r\nsecond\rthird  line"
    normalized_text = "first\nsecond\nthird  line"

    assert harness.normalize_chunk_text(windows_text) == normalized_text
    assert harness.text_sha256(windows_text) == harness.text_sha256(normalized_text)
    assert harness.text_sha256("a b") != harness.text_sha256("ab")


def test_chunk_ref_uses_filename_index_and_text_digest():
    digest = harness.text_sha256("evidence")
    expected_identity = f"notes.md\0{2}\0{digest}".encode("utf-8")
    expected = "cr1:" + hashlib.sha256(expected_identity).hexdigest()

    assert harness.make_chunk_ref("notes.md", 2, digest) == expected
    assert harness.make_chunk_ref("notes.md", 3, digest) != expected
    assert harness.make_chunk_ref("other.md", 2, digest) != expected


def test_manifest_is_order_independent_and_ignores_runtime_ids():
    first = _chunk(
        "first evidence",
        filename="a.md",
        chunk_index=0,
        chunk_id="runtime-a",
        document_id="document-a",
        processed_at="yesterday",
    )
    second = _chunk(
        "second evidence",
        filename="b.md",
        chunk_index=1,
        chunk_id="runtime-b",
        document_id="document-b",
        processed_at="today",
    )
    rebuilt_first = _chunk(
        "first evidence",
        filename="a.md",
        chunk_index=0,
        chunk_id="new-runtime-a",
        document_id="new-document-a",
        processed_at="tomorrow",
    )
    rebuilt_second = _chunk(
        "second evidence",
        filename="b.md",
        chunk_index=1,
        chunk_id="new-runtime-b",
        document_id="new-document-b",
        processed_at="tomorrow",
    )

    original = harness.build_chunk_manifest([second, first], SPLITTER)
    rebuilt = harness.build_chunk_manifest(
        [rebuilt_first, rebuilt_second], dict(reversed(list(SPLITTER.items())))
    )

    assert original == rebuilt
    assert original["chunk_count"] == 2
    assert [entry["filename"] for entry in original["chunks"]] == ["a.md", "b.md"]
    assert "chunk_id" not in str(original)
    assert "document_id" not in str(original)
    assert "first evidence" not in str(original)
    assert original["chunk_manifest_hash"] == harness.chunk_manifest_hash(original)


@pytest.mark.parametrize(
    "changed_chunks,changed_splitter",
    [
        ([_chunk("changed text")], SPLITTER),
        ([_chunk("original text", chunk_index=1)], SPLITTER),
        ([_chunk("original text", filename="other.md")], SPLITTER),
        (
            [_chunk("original text")],
            {**SPLITTER, "chunk_size": SPLITTER["chunk_size"] + 1},
        ),
        (
            [_chunk("original text")],
            {**SPLITTER, "chunk_overlap": SPLITTER["chunk_overlap"] + 1},
        ),
        (
            [_chunk("original text")],
            {**SPLITTER, "name": "DifferentSplitter"},
        ),
        (
            [_chunk("original text")],
            {**SPLITTER, "separators": ["\n", ""]},
        ),
    ],
)
def test_manifest_hash_changes_with_chunk_or_splitter_identity(
    changed_chunks, changed_splitter
):
    original = harness.build_chunk_manifest([_chunk("original text")], SPLITTER)
    changed = harness.build_chunk_manifest(changed_chunks, changed_splitter)

    assert changed["chunk_manifest_hash"] != original["chunk_manifest_hash"]


def test_manifest_rejects_duplicate_filename_and_chunk_index():
    chunks = [_chunk("first"), _chunk("second")]

    with pytest.raises(ValueError, match="duplicate chunk location"):
        harness.build_chunk_manifest(chunks, SPLITTER)


@pytest.mark.parametrize(
    "chunk,error",
    [
        (Document(page_content="text", metadata={"chunk_index": 0}), "filename"),
        (_chunk("text", filename="bad\0name.md"), "must not contain NUL"),
        (_chunk("text", chunk_index="0"), "integer chunk_index"),
        (_chunk("text", chunk_index=-1), "non-negative"),
        (
            SimpleNamespace(
                page_content=None,
                metadata={"filename": "notes.md", "chunk_index": 0},
            ),
            "chunk text must be a string",
        ),
    ],
)
def test_manifest_rejects_invalid_chunk_identity(chunk, error):
    with pytest.raises((TypeError, ValueError), match=error):
        harness.build_chunk_manifest([chunk], SPLITTER)
