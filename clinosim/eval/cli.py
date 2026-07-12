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
        help="Cohort root directory (contains fhir_r4/ NDJSON).",
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


def dispatch_eval(args: argparse.Namespace) -> int:
    engine = EvalEngine(cohort_dir=args.cohort_dir, countries=args.country)
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
