"""CLI subcommand handler: `clinosim enumerate`.

Split from `clinosim/simulator/cli.py` — see PR K.
"""

from __future__ import annotations

import argparse
from typing import Any

from clinosim.simulator.cli_common import _print_summary, _run_exports


def _run_enumerate(args: Any) -> None:
    """enumerate dispatch (Issue #345).

    Discovers every disease/encounter YAML, expands cases at the requested
    coverage level, and emits CIF + FHIR (and optionally CSV) for every
    combination. Purpose: comprehensive debug + validation coverage that
    population-driven sampling cannot guarantee at any P.

    Writes:
      <output>/cif/                        — structural CIF per patient
      <output>/cif/narratives/template/    — Stage 2 narrative
      <output>/fhir_r4/                    — FHIR NDJSON per resource type
      <output>/enumeration_manifest.json   — patient_id → scenario map
    """
    import os as _os

    from clinosim.modules.document.narrative.passes import TemplateNarrativePass
    from clinosim.modules.output.cif_writer import write_cif
    from clinosim.simulator.enumerate import CoverageExplosionError, plan_enumeration, run_enumeration

    countries = ["JP", "US"] if args.include_both_countries else [args.country]

    try:
        plan = plan_enumeration(
            level=args.level,
            countries=countries,
            base_seed=args.seed,
            bypass_size_guard=args.yes_large,
        )
    except CoverageExplosionError as e:
        print(f"❌ {e}")
        return

    disease_count = sum(1 for c in plan.cases if c.kind == "disease")
    encounter_count = sum(1 for c in plan.cases if c.kind == "encounter")
    print(f"clinosim enumerate: level={args.level}, countries={countries}, seed={args.seed}")
    print(f"  total cases: {len(plan.cases)} ({disease_count} disease + {encounter_count} encounter)")

    if args.dry_run:
        print("  --dry-run: plan-only, not simulating")
        for c in plan.cases[:5]:
            print(f"    {c.case_key}")
        if len(plan.cases) > 5:
            print(f"    ... ({len(plan.cases) - 5} more)")
        return

    print(f"  → {args.output}")
    dataset, manifest = run_enumeration(plan)

    cif_dir = _os.path.join(args.output, "cif")
    write_cif(dataset, cif_dir)

    # Manifest — sibling to fhir_r4/ so downstream consumers can locate the
    # patient_id → scenario map without walking the CIF.
    _os.makedirs(args.output, exist_ok=True)
    manifest_path = _os.path.join(args.output, "enumeration_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(manifest.to_json())
    print(f"  wrote {manifest_path}")

    # Stage 2 narrative + FHIR export — mirror test-encounter pattern.
    # Country: when both countries are requested, run Stage 2 per country
    # subset would require CIF partitioning; for now the manifest carries
    # the per-case country and Stage 2 uses the first country for rendering
    # (documented limitation, future extension).
    render_country = countries[0]
    TemplateNarrativePass(
        cif_dir=cif_dir,
        version_id="template",
        country=render_country,
        rng_seed=args.seed,
    ).run()
    _os.makedirs(_os.path.join(cif_dir, "narratives"), exist_ok=True)
    with open(_os.path.join(cif_dir, "narratives", "current_version.txt"), "w", encoding="utf-8") as f:
        f.write("template")

    formats = args.format or []
    if "all" in formats:
        formats = ["fhir-r4", "csv"]
    _run_exports(formats, cif_dir, args.output, render_country)

    _print_summary(dataset, args.output)


# test-disease legacy defaults (adv-1 F-2). Kept out of the argparse defaults so
# an explicit `--seed 42` / `--country US` / `-n 3` is distinguishable from
# "flag omitted" when resolving against a --patient-profile.
_TD_DEFAULT_COUNT = 3
_TD_DEFAULT_SEED = 42
_TD_DEFAULT_COUNTRY = "US"


def register(sub: argparse._SubParsersAction) -> None:
    # === enumerate: exhaustive debug enumeration (Issue #345) ===
    # Generates exactly one patient per (disease × severity × course_archetype)
    # plus per (encounter × severity). Purpose: comprehensive FHIR validation
    # coverage and pattern regression detection — population-driven sampling
    # can leave rare patterns unfired even at large P, but enumeration
    # deterministically covers every combination.
    en = sub.add_parser(
        "enumerate",
        help="Exhaustively enumerate all clinical scenarios (debug: 1 patient per pattern)",
    )
    en.add_argument(
        "-o",
        "--output",
        required=True,
        help="Output directory (writes cif/, cif/narratives/template/, fhir_r4/, enumeration_manifest.json)",
    )
    en.add_argument(
        "--level",
        default="full",
        choices=["basic", "severity", "full"],
        help=(
            "Coverage level. basic=1 per scenario, severity=1 per (scenario × severity), "
            "full=1 per (disease × severity × course_archetype) + (encounter × severity). "
            "Default: full."
        ),
    )
    en.add_argument(
        "--country",
        default="US",
        choices=["JP", "US"],
        help="Country locale (single). Default: US (Issue #570 convention).",
    )
    en.add_argument(
        "--include-both-countries",
        action="store_true",
        help="Emit both JP and US patients in one run (approximately doubles the case count).",
    )
    en.add_argument("--seed", type=int, default=42, help="Base seed for deterministic sub-seed derivation.")
    en.add_argument(
        "--yes-large",
        action="store_true",
        help=(
            "Bypass the coverage-explosion guard (threshold 2000 patients). Required if "
            "the case count would exceed the threshold."
        ),
    )
    en.add_argument(
        "--format",
        nargs="+",
        default=["cif", "fhir-r4"],
        choices=["cif", "fhir-r4", "csv", "all"],
        help="Output formats. Default: cif + fhir-r4.",
    )
    en.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan only — print discovered scenarios and case count, do not simulate or write output.",
    )
    en.set_defaults(handler=run)


def run(args: Any, parser: argparse.ArgumentParser) -> None:
    _run_enumerate(args)
