"""Run retrieval once, score the saved contexts, and print the v3 report."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from eval import run_retrieval, score_run  # noqa: E402


def run() -> Path:
    """Execute the reproducible run -> score -> report pipeline."""
    run_path = run_retrieval.run()
    score_path = score_run.score_run(run_path)
    with score_path.open("r", encoding="utf-8") as handle:
        score_artifact = json.load(handle)
    score_run.print_report(score_artifact["results"], score_path)
    return score_path


if __name__ == "__main__":
    run()
