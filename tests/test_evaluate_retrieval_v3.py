from eval import evaluate_retrieval_v3


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
