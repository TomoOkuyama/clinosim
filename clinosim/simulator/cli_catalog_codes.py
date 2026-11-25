"""``clinosim catalog-codes``: the catalog of every code a release can emit (Issue #3763)."""

from __future__ import annotations

import argparse
import json
from typing import Any


def register(sub: argparse._SubParsersAction) -> None:
    cc = sub.add_parser(
        "catalog-codes",
        help=(
            "Write the catalog of every code this version can emit for a country "
            "(same format as a dataset's catalog/codes-used.ndjson)"
        ),
    )
    cc.add_argument("--country", required=True, choices=["US", "JP"], help="Country whose codes are listed")
    cc.add_argument("-o", "--output", required=True, help="Output NDJSON file")
    cc.add_argument("--previous", default=None, help="The same country's catalog of the previous release, to compare")
    cc.add_argument("--diff-label", default="the previous release", help="Name of the previous release in the diff")
    cc.add_argument("--diff-output", default=None, help="Write the comparison with --previous here, as Markdown")
    cc.set_defaults(handler=run)


def run(args: Any, parser: argparse.ArgumentParser) -> None:
    from clinosim.modules.output.fhir_r4.release_catalog import build_release_catalog, diff_catalogs, format_diff

    if args.diff_output and not args.previous:
        parser.error("--diff-output needs --previous")
    catalog = build_release_catalog(args.country)
    n = catalog.write(args.output)
    print(f"clinosim catalog-codes: {n} codes for {args.country} -> {args.output}")
    if args.previous:
        with open(args.previous, encoding="utf-8") as f:
            old = [json.loads(line) for line in f if line.strip()]
        diff = diff_catalogs(old, catalog.lines())
        text = format_diff(args.country, args.diff_label, diff)
        if args.diff_output:
            with open(args.diff_output, "w", encoding="utf-8") as f:
                f.write(text)
        else:
            print(text)
