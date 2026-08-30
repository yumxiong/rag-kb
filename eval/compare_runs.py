"""Compare two paired retrieval score artifacts.

The comparison direction is always ``B - A``. Hit uses the exact two-sided
McNemar/binomial test; MRR, coverage, and hop spread use a paired bootstrap
with shared resampled question indices.

Useful exact-McNemar reference points (rescued:harmed -> p-value) are 5:2 ->
0.453, 7:1 -> 0.070, 8:1 -> 0.039, and 10:2 -> 0.039. Small evaluation sets
should be treated as pipeline checks, not as strong evidence of improvement.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

CONSISTENCY_FIELDS = (
    "eval_set.sha256",
    "corpus_hash",
    "chunk_manifest_hash",
    "scorer_version",
)
HEADLINES = ("mrr", "hit", "coverage")
BOOTSTRAP_SAMPLES = 10_000
BOOTSTRAP_SEED = 0


def _nested_get(value: Mapping[str, Any], dotted_path: str) -> Any:
    current: Any = value
    for part in dotted_path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            raise ValueError(f"score artifact is missing {dotted_path}")
        current = current[part]
    return current


def validate_compatibility(
    score_a: Mapping[str, Any], score_b: Mapping[str, Any]
) -> None:
    """Reject score artifacts that are not valid paired experiment inputs."""
    for field in CONSISTENCY_FIELDS:
        value_a = _nested_get(score_a, field)
        value_b = _nested_get(score_b, field)
        if field == "scorer_version":
            valid = (
                not isinstance(value_a, bool)
                and isinstance(value_a, int)
                and value_a >= 1
                and not isinstance(value_b, bool)
                and isinstance(value_b, int)
                and value_b >= 1
            )
        else:
            valid = (
                isinstance(value_a, str)
                and bool(value_a)
                and isinstance(value_b, str)
                and bool(value_b)
            )
        if not valid:
            raise ValueError(f"invalid compatibility field: {field}")
        if value_a != value_b:
            raise ValueError(f"{field} mismatch: A={value_a!r}, B={value_b!r}")


def exact_mcnemar(rescued: int, harmed: int) -> float:
    """Return the exact two-sided McNemar p-value for discordant pairs."""
    if (
        isinstance(rescued, bool)
        or isinstance(harmed, bool)
        or not isinstance(rescued, int)
        or not isinstance(harmed, int)
        or rescued < 0
        or harmed < 0
    ):
        raise ValueError("rescued and harmed must be non-negative integers")
    discordant = rescued + harmed
    if discordant == 0:
        return 1.0
    lower = min(rescued, harmed)
    tail = sum(math.comb(discordant, i) for i in range(lower + 1))
    return min(1.0, 2.0 * tail / (2**discordant))


def _percentile(sorted_values: Sequence[float], probability: float) -> float:
    if not sorted_values:
        raise ValueError("cannot compute a percentile of an empty sample")
    position = probability * (len(sorted_values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    fraction = position - lower
    return sorted_values[lower] * (1.0 - fraction) + sorted_values[upper] * fraction


def paired_bootstrap(
    values_a: Sequence[float],
    values_b: Sequence[float],
    *,
    samples: int = BOOTSTRAP_SAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Estimate the paired mean difference and percentile confidence interval."""
    if len(values_a) != len(values_b) or not values_a:
        raise ValueError("paired bootstrap requires equal non-empty samples")
    if isinstance(samples, bool) or not isinstance(samples, int) or samples < 1:
        raise ValueError("samples must be a positive integer")
    pairs = []
    for value_a, value_b in zip(values_a, values_b):
        if (
            isinstance(value_a, bool)
            or isinstance(value_b, bool)
            or not isinstance(value_a, (int, float))
            or not isinstance(value_b, (int, float))
            or not math.isfinite(value_a)
            or not math.isfinite(value_b)
        ):
            raise ValueError("paired bootstrap values must be finite numbers")
        pairs.append((float(value_a), float(value_b)))

    deltas = [value_b - value_a for value_a, value_b in pairs]
    observed = sum(deltas) / len(deltas)
    rng = random.Random(seed)
    bootstrap_means = []
    for _ in range(samples):
        bootstrap_means.append(
            sum(deltas[rng.randrange(len(deltas))] for _ in deltas) / len(deltas)
        )
    bootstrap_means.sort()
    low = _percentile(bootstrap_means, 0.025)
    high = _percentile(bootstrap_means, 0.975)
    return {
        "n": len(deltas),
        "mean_a": sum(value_a for value_a, _ in pairs) / len(pairs),
        "mean_b": sum(value_b for _, value_b in pairs) / len(pairs),
        "delta": observed,
        "ci95": [low, high],
        "statistically_distinguishable": low > 0.0 or high < 0.0,
        "samples": samples,
        "seed": seed,
    }


def _result_at_k(score: Mapping[str, Any], k: int, label: str) -> Mapping[str, Any]:
    results = score.get("results")
    if not isinstance(results, list):
        raise ValueError(f"score {label} has no results")
    matches = [
        result
        for result in results
        if isinstance(result, dict) and result.get("k") == k
    ]
    if len(matches) != 1:
        raise ValueError(f"score {label} must contain exactly one result for k={k}")
    return matches[0]


def _rows_by_id(result: Mapping[str, Any], label: str) -> dict[str, Mapping[str, Any]]:
    rows = result.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"score {label} has no per-question rows")
    by_id = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise ValueError(f"score {label} contains a malformed row")
        if row["id"] in by_id:
            raise ValueError(f"score {label} contains duplicate question IDs")
        by_id[row["id"]] = row
    return by_id


def _number(row: Mapping[str, Any], field: str, label: str) -> float:
    value = row.get(field)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError(f"row {label} has invalid {field}")
    return float(value)


def _hit(row: Mapping[str, Any], label: str) -> bool:
    value = row.get("hit")
    if not isinstance(value, bool):
        raise ValueError(f"row {label} has invalid hit")
    return value


def _mrr(row: Mapping[str, Any], label: str) -> float:
    hit = _hit(row, label)
    completion_rank = row.get("completion_rank")
    if completion_rank is None:
        if hit:
            raise ValueError(f"row {label} is hit but has no completion_rank")
        return 0.0
    if (
        isinstance(completion_rank, bool)
        or not isinstance(completion_rank, int)
        or completion_rank < 1
    ):
        raise ValueError(f"row {label} has invalid completion_rank")
    if not hit:
        raise ValueError(f"row {label} has completion_rank but is not hit")
    return 1.0 / completion_rank


def _coverage(row: Mapping[str, Any], label: str) -> float:
    value = _number(row, "coverage", label)
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"row {label} has coverage outside [0, 1]")
    return value


def _hop_spread(row: Mapping[str, Any], label: str) -> float:
    value = _number(row, "hop_spread", label)
    if value < 0.0:
        raise ValueError(f"row {label} has negative hop_spread")
    return value


def _continuous_metric(
    ids: Sequence[str],
    rows_a: Mapping[str, Mapping[str, Any]],
    rows_b: Mapping[str, Mapping[str, Any]],
    extractor: Callable[[Mapping[str, Any], str], float],
    *,
    samples: int,
    seed: int,
) -> dict[str, Any]:
    values_a = [extractor(rows_a[qid], f"A/{qid}") for qid in ids]
    values_b = [extractor(rows_b[qid], f"B/{qid}") for qid in ids]
    return paired_bootstrap(values_a, values_b, samples=samples, seed=seed)


def compare_scores(
    score_a: Mapping[str, Any],
    score_b: Mapping[str, Any],
    *,
    k: int = 5,
    headline: str = "mrr",
    bootstrap_samples: int = BOOTSTRAP_SAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Return a deterministic paired comparison report for one k value."""
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError("k must be a positive integer")
    if headline not in HEADLINES:
        raise ValueError(f"headline must be one of {', '.join(HEADLINES)}")
    validate_compatibility(score_a, score_b)
    rows_a = _rows_by_id(_result_at_k(score_a, k, "A"), "A")
    rows_b = _rows_by_id(_result_at_k(score_b, k, "B"), "B")
    if set(rows_a) != set(rows_b):
        raise ValueError("score question IDs do not match")
    ids = sorted(rows_a)
    for qid in ids:
        if rows_a[qid].get("type") != rows_b[qid].get("type"):
            raise ValueError(f"question type mismatch for {qid}")

    hits_a = [_hit(rows_a[qid], f"A/{qid}") for qid in ids]
    hits_b = [_hit(rows_b[qid], f"B/{qid}") for qid in ids]
    rescued = sum(not value_a and value_b for value_a, value_b in zip(hits_a, hits_b))
    harmed = sum(value_a and not value_b for value_a, value_b in zip(hits_a, hits_b))
    hit_a = sum(hits_a) / len(ids)
    hit_b = sum(hits_b) / len(ids)
    metrics: dict[str, Any] = {
        "hit": {
            "n": len(ids),
            "mean_a": hit_a,
            "mean_b": hit_b,
            "delta": hit_b - hit_a,
            "rescued": rescued,
            "harmed": harmed,
            "discordant": rescued + harmed,
            "p_value": exact_mcnemar(rescued, harmed),
        },
        "mrr": _continuous_metric(
            ids,
            rows_a,
            rows_b,
            _mrr,
            samples=bootstrap_samples,
            seed=seed,
        ),
        "coverage": _continuous_metric(
            ids,
            rows_a,
            rows_b,
            _coverage,
            samples=bootstrap_samples,
            seed=seed,
        ),
    }

    joint_multihop_hits = [
        qid
        for qid, hit_value_a, hit_value_b in zip(ids, hits_a, hits_b)
        if rows_a[qid].get("type") == "multihop" and hit_value_a and hit_value_b
    ]
    if joint_multihop_hits:
        metrics["hop_spread"] = _continuous_metric(
            joint_multihop_hits,
            rows_a,
            rows_b,
            _hop_spread,
            samples=bootstrap_samples,
            seed=seed,
        )

    return {
        "k": k,
        "n": len(ids),
        "headline": headline,
        "direction": "B - A",
        "system_a": {
            "retriever": score_a.get("retriever"),
            "run_id": _nested_get(score_a, "source_run.run_id"),
        },
        "system_b": {
            "retriever": score_b.get("retriever"),
            "run_id": _nested_get(score_b, "source_run.run_id"),
        },
        "metrics": metrics,
        "small_sample": len(ids) < 30,
    }


def _fmt(value: float) -> str:
    return f"{value:.3f}"


def _metric_line(name: str, metric: Mapping[str, Any]) -> str:
    prefix = (
        f"{name}: A={_fmt(metric['mean_a'])} B={_fmt(metric['mean_b'])} "
        f"delta={_fmt(metric['delta'])}"
    )
    if name == "Hit":
        return (
            prefix
            + f" rescued={metric['rescued']} harmed={metric['harmed']} "
            + f"McNemar p={_fmt(metric['p_value'])}"
        )
    return (
        prefix
        + f" 95% CI=[{_fmt(metric['ci95'][0])}, {_fmt(metric['ci95'][1])}] "
        + f"paired_n={metric['n']}"
    )


def print_report(report: Mapping[str, Any]) -> None:
    """Print one predeclared headline and clearly labeled diagnostics."""
    system_a = report["system_a"]
    system_b = report["system_b"]
    print(
        f"Paired comparison @ k={report['k']} (B - A), n={report['n']}\n"
        f"A: {system_a['retriever']}  run={system_a['run_id']}\n"
        f"B: {system_b['retriever']}  run={system_b['run_id']}"
    )
    if report["small_sample"]:
        print(
            f"WARNING: small sample (n={report['n']} < 30); intervals are "
            "unstable and are only for pipeline validation."
        )

    display_names = {
        "hit": "Hit",
        "mrr": "MRR",
        "coverage": "Coverage",
        "hop_spread": "HopSpread",
    }
    headline = report["headline"]
    print("\nHEADLINE")
    print("  " + _metric_line(display_names[headline], report["metrics"][headline]))
    print("\nDIAGNOSTICS")
    for name in ("hit", "mrr", "coverage", "hop_spread"):
        if name != headline and name in report["metrics"]:
            print("  " + _metric_line(display_names[name], report["metrics"][name]))


def _load_score(path: Path) -> Mapping[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"score artifact must be a JSON object: {path}")
    return value


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("score_a", type=Path)
    parser.add_argument("score_b", type=Path)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--headline", choices=HEADLINES, default="mrr")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        report = compare_scores(
            _load_score(args.score_a),
            _load_score(args.score_b),
            k=args.k,
            headline=args.headline,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
