"""``clinosim eval`` CLI wiring."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from clinosim.eval.engine import EvalEngine
from clinosim.eval.report import render_markdown, write_json, write_markdown


def add_eval_subparser(subparsers: argparse._SubParsersAction) -> None:
    ev = subparsers.add_parser(
        "eval",
        help="Score a generated cohort on structural / clinical / locale axes.",
    )
    ev.add_argument(
        "-d", "--cohort-dir", required=True, type=Path,
        help=(
            "Cohort root directory (contains fhir_r4/ NDJSON), OR a "
            "Synthea `fhir/` output directory containing per-patient "
            "Bundle JSONs — Synthea layout is auto-detected and "
            "normalized in-place under `<cohort-dir>/../synthea-normalized/`. "
            "Override the normalization target with --synthea-normalize."
        ),
    )
    ev.add_argument(
        "--json", type=Path, default=None,
        help="Write JSON report to PATH.",
    )
    ev.add_argument(
        "--md", type=Path, default=None,
        help="Write Markdown report to PATH.",
    )
    ev.add_argument(
        "--country", action="append", default=None,
        help="Limit to one or more country subdirs (repeat flag). Default: all discovered.",
    )
    ev.add_argument(
        "--strict", action="store_true",
        help="Exit 1 if any axis has a FAIL check. Default: exit 0 regardless.",
    )
    ev.add_argument(
        "--synthea-normalize", type=Path, default=None,
        help=(
            "When --cohort-dir points at Synthea output, write the "
            "normalized per-resourceType NDJSON layout to this "
            "directory before scoring. Default: `<cohort-dir>/../synthea-normalized/`."
        ),
    )


def dispatch_eval(args: argparse.Namespace) -> int:
    # Synthea layout detection — if `--cohort-dir` looks like a Synthea
    # per-patient-Bundle directory, normalize it into a clinosim-shaped
    # layout first, then evaluate.
    from clinosim.eval.synthea_adapter import (
        bundle_dir_to_ndjson_layout,
        looks_like_synthea_output,
    )
    cohort_dir = args.cohort_dir
    if looks_like_synthea_output(cohort_dir):
        target = args.synthea_normalize or (cohort_dir.parent / "synthea-normalized")
        print(f"clinosim eval: detected Synthea layout — normalizing into {target}",
              file=sys.stderr)
        counts = bundle_dir_to_ndjson_layout(cohort_dir, target, overwrite=True)
        total = sum(counts.values())
        print(f"clinosim eval: wrote {total} resources across {len(counts)} ResourceType(s)",
              file=sys.stderr)
        cohort_dir = target

    engine = EvalEngine(cohort_dir=cohort_dir, countries=args.country)
    try:
        report = engine.run()
    except FileNotFoundError as exc:
        print(f"clinosim eval: {exc}", file=sys.stderr)
        return 2

    # Always print the Markdown to stdout — it's the human-friendly default.
    print(render_markdown(report))

    if args.json:
        write_json(report, args.json)
        print(f"\n[wrote JSON: {args.json}]")
    if args.md:
        write_markdown(report, args.md)
        print(f"[wrote MD:   {args.md}]")

    if args.strict and report.overall_status == "FAIL":
        return 1
    return 0
