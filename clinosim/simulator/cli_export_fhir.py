"""CLI subcommand handler: `clinosim export-fhir`.

Split from `clinosim/simulator/cli.py` — see PR K.
"""

from __future__ import annotations

import argparse
import os
from typing import Any


def _run_export_fhir(args: Any) -> None:
    """Stage 3 handler: convert an existing CIF (+narrative) into FHIR NDJSON."""
    from clinosim.modules.output.adapter import OutputContext, get_adapter

    cif_dir = args.cif_dir
    if not os.path.isdir(os.path.join(cif_dir, "structural", "patients")):
        print(f"❌ CIF directory not valid: {cif_dir} (missing structural/patients/)")
        return

    # Preserve export-fhir's original output semantics: --output is the FHIR directory
    # itself (not a root); default is <cif parent>/fhir_r4.
    if args.output:
        output_dir = args.output
    else:
        parent = os.path.dirname(os.path.abspath(cif_dir))
        output_dir = os.path.join(parent, "fhir_r4")

    narrative_version = getattr(args, "narrative_version", "current")
    print("clinosim export-fhir:")
    print(f"  CIF directory:      {cif_dir}")
    print(f"  Output:             {output_dir}")
    print(f"  Country:            {args.country}")
    print(f"  Narrative version:  {narrative_version}")

    get_adapter("fhir-r4").convert(
        cif_dir,
        output_dir,
        OutputContext(
            country=getattr(args, "country", "US"),
            narrative_version=narrative_version,
        ),
    )

    # Summarize output
    if not os.path.isdir(output_dir):
        return
    files = sorted(f for f in os.listdir(output_dir) if f.endswith(".ndjson") or f == "manifest.json")
    print("\n  === FHIR Export Summary ===")
    for name in files:
        path = os.path.join(output_dir, name)
        size = os.path.getsize(path)
        if name.endswith(".ndjson"):
            with open(path, encoding="utf-8") as f:
                line_count = sum(1 for _ in f)
            print(f"    {name:35s} {line_count:>7d} lines  ({size:>10,} B)")
        else:
            print(f"    {name:35s} {'':>7s}        ({size:>10,} B)")


def register(sub: argparse._SubParsersAction) -> None:
    # === export-fhir: Stage 3 — convert CIF to FHIR NDJSON ===
    ef = sub.add_parser(
        "export-fhir",
        help="Convert an existing CIF directory to FHIR R4 Bulk Data NDJSON",
    )
    ef.add_argument("--cif-dir", required=True, help="Path to an existing CIF directory")
    ef.add_argument(
        "-o",
        "--output",
        default=None,
        help="FHIR output directory (default: <cif-dir>/../fhir_r4)",
    )
    ef.add_argument("--country", default="US", help="Country code (US or JP)")
    ef.add_argument(
        "--narrative-version",
        default="current",
        help="Narrative version to select (default: current from pointer file)",
    )
    ef.set_defaults(handler=run)


def run(args: Any, parser: argparse.ArgumentParser) -> None:
    _run_export_fhir(args)
