"""``clinosim diff``: FHIR Bundle transaction between two snapshot outputs (F3)."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from typing import Any


def register(sub: argparse._SubParsersAction) -> None:
    # === diff: F3 snapshot diff → Bundle transaction ===
    df = sub.add_parser(
        "diff",
        help="Generate FHIR Bundle transaction from 2 snapshot outputs (F3)",
    )
    df.add_argument("--old", required=True, help="Previous snapshot's FHIR output directory")
    df.add_argument("--new", required=True, help="Current snapshot's FHIR output directory")
    df.add_argument("--output-bundle", required=True, help="Output path for the Bundle transaction JSON")
    df.add_argument("--output-summary", default=None, help="Output path for the summary text (stdout if omitted)")
    df.add_argument(
        "--old-cursor",
        default=None,
        help="Previous snapshot's cursor date (for the summary; defaults to the --old dir name)",
    )
    df.add_argument(
        "--new-cursor",
        default=None,
        help="Current snapshot's cursor date (for the summary; defaults to the --new dir name)",
    )
    df.set_defaults(handler=run)


def run(args: Any, parser: argparse.ArgumentParser) -> None:
    from pathlib import Path

    from clinosim.simulator.diff import build_diff_bundle, format_summary

    old_dir = Path(args.old)
    new_dir = Path(args.new)
    bundle_path = Path(args.output_bundle)

    old_cursor = args.old_cursor or old_dir.name
    new_cursor = args.new_cursor or new_dir.name

    bundle_id = f"clinosim-diff-{old_cursor}-to-{new_cursor}"
    last_updated = datetime.now().isoformat(timespec="seconds")

    bundle = build_diff_bundle(old_dir, new_dir, bundle_id, last_updated)
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    summary = format_summary(bundle, old_cursor, new_cursor)
    if args.output_summary:
        summary_path = Path(args.output_summary)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(summary, encoding="utf-8")
    else:
        print(summary)
    return
