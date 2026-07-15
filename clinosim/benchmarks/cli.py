"""`clinosim benchmark` CLI subcommand — session 48 P2-15.

Reads a generated CIF directory and prints baseline reports for the requested
task. Deterministic: same CIF input → same report.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import asdict
from pathlib import Path

from clinosim.benchmarks import (
    creatinine_delta_baseline,
    extract_aki_labels,
    extract_sepsis_labels,
    lactate_threshold_baseline,
    majority_baseline,
)

TASKS = ("sepsis", "aki")


def add_benchmark_subparser(subparsers: argparse._SubParsersAction) -> None:
    """`clinosim benchmark <task>` を simulator/cli.py に登録する。"""
    p = subparsers.add_parser(
        "benchmark",
        help="Run reproducible baseline benchmarks on a CIF cohort (sepsis / aki prediction floor numbers)",
    )
    p.add_argument("task", choices=TASKS, help="Which prediction task to score")
    p.add_argument(
        "--cif-dir",
        required=True,
        help="Path to CIF root directory (contains structural/patients/)",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output instead of the human-readable summary",
    )


def dispatch_benchmark(args: argparse.Namespace) -> int:
    """Return non-zero on missing / empty CIF; 0 on success."""
    cif_dir = Path(args.cif_dir)
    if not cif_dir.is_dir():
        print(
            f"clinosim benchmark: CIF directory not found: {cif_dir}",
            file=sys.stderr,
        )
        return 2

    if args.task == "sepsis":
        labels = extract_sepsis_labels(cif_dir)
        reports = [
            majority_baseline(labels),
            lactate_threshold_baseline(labels),
        ]
    elif args.task == "aki":
        labels = extract_aki_labels(cif_dir)
        reports = [
            majority_baseline(labels),
            creatinine_delta_baseline(labels),
        ]
    else:  # pragma: no cover — argparse choices gate
        print(f"clinosim benchmark: unknown task {args.task}", file=sys.stderr)
        return 2

    if not labels:
        print(
            f"clinosim benchmark: no records found under {cif_dir}",
            file=sys.stderr,
        )
        return 3

    if args.json:
        import json as _json

        payload = {
            "task": args.task,
            "cif_dir": str(cif_dir),
            "n_records": len(labels),
            "n_positive": sum(r.label for r in labels),
            "baselines": [asdict(r) for r in reports],
        }
        print(_json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(
        f"clinosim benchmark: task={args.task}, n={len(labels)}, "
        f"prevalence={sum(r.label for r in labels) / len(labels):.4f}"
    )
    for r in reports:
        print(f"  == baseline: {r.name} ==")
        print(f"     AUROC     = {r.auroc:.4f}")
        print(f"     accuracy  = {r.accuracy:.4f}")
        print(f"     +pred rate = {r.positive_predicted_rate:.4f}")
        print(f"     rationale: {r.rationale}")
    return 0
