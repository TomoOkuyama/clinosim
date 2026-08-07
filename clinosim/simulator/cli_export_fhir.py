"""CLI subcommand handler: `clinosim export-fhir`.

Split from `clinosim/simulator/cli.py` (session 82) — see PR K.
"""

from __future__ import annotations

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
            with open(path) as f:
                line_count = sum(1 for _ in f)
            print(f"    {name:35s} {line_count:>7d} lines  ({size:>10,} B)")
        else:
            print(f"    {name:35s} {'':>7s}        ({size:>10,} B)")
