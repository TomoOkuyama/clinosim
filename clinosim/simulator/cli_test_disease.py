"""CLI subcommand handlers: `clinosim test-disease`.

Split from `clinosim/simulator/cli.py` (session 82) — see PR K.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from clinosim.simulator.cli_common import _print_debug_record, _print_summary, _run_exports
from clinosim.simulator.engine import run_forced
from clinosim.types.config import ForcedScenario, PatientProfile, SimulatorConfig

# `test-disease` legacy CLI defaults. These are the argparse defaults for
# --count / --seed / --country, hoisted to module scope so
# `_resolve_test_disease_defaults` can distinguish "flag omitted (== default)"
# from "flag explicitly set to same value as default" when resolving against
# a --patient-profile.
_TD_DEFAULT_COUNT = 3
_TD_DEFAULT_SEED = 42
_TD_DEFAULT_COUNTRY = "US"


def _resolve_test_disease_defaults(args: Any) -> None:
    """Apply legacy test-disease defaults to omitted CLI flags (non-profile path).

    adv-1 F-2: argparse defaults for -n/--seed/--country are None; this restores
    the pre-F-2 defaults (3 / 42 / US) so non-profile behavior is byte-identical.
    """
    if args.count is None:
        args.count = _TD_DEFAULT_COUNT
    if args.seed is None:
        args.seed = _TD_DEFAULT_SEED
    if args.country is None:
        args.country = _TD_DEFAULT_COUNTRY


def _run_test_disease(args: Any) -> None:
    """test-disease dispatch (AD-65 Phase 4 / Task 16).

    -o omitted (default): original stdout debug print, unchanged.
    -o set: mini-generate (N patients of one disease) through the full 3-stage
    pipeline (structural CIF + template narrative + FHIR/CSV export) so a bug
    can be verified in ~10s without regenerating a full cohort.
    """
    if args.output:
        _run_test_disease_generate(args)
        return
    _run_test_disease_debug(args)


def _run_test_disease_debug(args: Any) -> None:
    """Original test-disease behavior: simulate + print debug record per patient."""
    _resolve_test_disease_defaults(args)
    scenario = ForcedScenario(
        disease_id=args.disease_id,
        count=args.count,
        severity=args.severity,
        archetype=args.archetype,
    )
    config = SimulatorConfig(random_seed=args.seed, country=args.country)
    print(f"clinosim test-disease: {args.disease_id} x{args.count}, country={args.country}")
    dataset = run_forced(scenario, config)

    for i, record in enumerate(dataset.patients):
        _print_debug_record(record, i + 1)


def _apply_profile_cli_overrides(args: Any, profile: PatientProfile) -> PatientProfile:
    """Resolve explicit CLI values against a loaded PatientProfile (adv-1 F-2).

    Resolution order: explicit CLI value (stderr WARN when it overrides a
    differing profile value) > profile value. Because the argparse defaults for
    -n/--seed/--country are None, an explicit `--seed 42` overrides a profile
    with random_seed=99 even though 42 equals the legacy default (Bug D lesson:
    explicit user input wins, and must be distinguishable from "omitted").
    """
    overrides: list[tuple[str, str, Any]] = [
        ("positional disease_id", "disease_id", args.disease_id),
        ("--severity", "severity", args.severity),
        ("--archetype", "archetype", args.archetype),
        ("--seed", "random_seed", args.seed),
        ("--country", "country", args.country),
        ("-n/--count", "count", args.count),
    ]
    for label, field, cli_value in overrides:
        if cli_value is None:
            continue
        profile_value = getattr(profile, field)
        if cli_value != profile_value:
            print(
                f"WARN: {label}={cli_value!r} differs from profile {field}={profile_value!r}; using {label}",
                file=sys.stderr,
            )
            profile = profile.model_copy(update={field: cli_value})
    return profile


def _run_test_disease_generate(args: Any) -> None:
    """Mini-generate: N patients of a specific disease + CIF + narrative + FHIR/CSV.

    Produces the same on-disk layout as `clinosim generate` (cif/structural,
    cif/narratives/template, fhir_r4/*.ndjson, csv/*) but scoped to one disease and
    a tiny cohort — the AD-65 Phase 4 dev facility for 10-second targeted verify.

    AD-66 α-min-2c: when --patient-profile is set, the profile YAML feeds
    ForcedScenario + SimulatorConfig; CLI args override profile fields with
    stderr WARN (Bug D lesson — explicit user input wins).
    """
    from clinosim.modules.document.narrative.passes import TemplateNarrativePass
    from clinosim.modules.output.cif_writer import write_cif
    from clinosim.types.config import load_patient_profile

    cif_dir = os.path.join(args.output, "cif")

    profile: PatientProfile | None = None
    if getattr(args, "patient_profile", None):
        try:
            profile = load_patient_profile(args.patient_profile)
        except FileNotFoundError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(2)
        except Exception as e:
            print(f"ERROR: invalid patient profile: {e}", file=sys.stderr)
            sys.exit(2)

        # Explicit CLI value > profile value, with stderr WARN (adv-1 F-2;
        # Bug D lesson: explicit CLI > implicit YAML)
        profile = _apply_profile_cli_overrides(args, profile)

        scenario = profile.to_forced_scenario()
        config = SimulatorConfig(
            random_seed=profile.random_seed,
            country=profile.country,
            hospital_scale=profile.hospital_scale,
            catchment_population=profile.count,
        )
        effective_disease_id = profile.disease_id
        effective_count = profile.count
        effective_country = profile.country
    else:
        if not args.disease_id:
            print(
                "ERROR: either positional disease_id or --patient-profile must be provided",
                file=sys.stderr,
            )
            sys.exit(2)
        _resolve_test_disease_defaults(args)
        scenario = ForcedScenario(
            disease_id=args.disease_id,
            count=args.count,
            severity=args.severity,
            archetype=args.archetype,
        )
        config = SimulatorConfig(
            random_seed=args.seed,
            country=args.country,
            catchment_population=args.count,
        )
        effective_disease_id = args.disease_id
        effective_count = args.count
        effective_country = args.country

    print(
        f"clinosim test-disease (generate): {effective_disease_id} x{effective_count}, "
        f"country={effective_country} -> {args.output}"
    )
    dataset = run_forced(scenario, config)

    write_cif(dataset, cif_dir)

    # Stage 2 (AD-65): always run the template narrative pass, mirroring `generate`'s
    # auto-invoke, so the mini-cohort is emit-ready regardless of which export
    # format(s) were requested.
    effective_seed = profile.random_seed if profile is not None else args.seed
    TemplateNarrativePass(
        cif_dir=cif_dir,
        version_id="template",
        country=effective_country,
        rng_seed=effective_seed,
    ).run()
    os.makedirs(os.path.join(cif_dir, "narratives"), exist_ok=True)
    with open(os.path.join(cif_dir, "narratives", "current_version.txt"), "w") as f:
        f.write("template")

    # Format exports via the adapter registry (AD-58) — reuse the same `_run_exports`
    # dispatch as `generate` (single edit point for adding a new output format).
    formats = args.format or []
    if "all" in formats:
        formats = ["fhir-r4", "csv"]
    _run_exports(formats, cif_dir, args.output, effective_country)

    _print_summary(dataset, args.output)
