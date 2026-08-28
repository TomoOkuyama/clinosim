"""CLI subcommand handlers: `clinosim test-encounter`.

Split from `clinosim/simulator/cli.py` — see PR K.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from clinosim import __version__ as _clinosim_version
from clinosim import determinism
from clinosim.modules.patient.activator import activate_patient
from clinosim.modules.staff.engine import generate_roster
from clinosim.simulator.cli_common import _print_debug_record, _print_summary, _run_exports
from clinosim.simulator.emergency import _simulate_ed_visit
from clinosim.types.config import SimulatorConfig
from clinosim.types.output import CIFDataset, CIFMetadata, CIFPatientRecord

# ---------------------------------------------------------------------------
# Test-encounter default sampling ranges (Issue #637)
# Pinned so `clinosim test-encounter` output is reproducible across time —
# a floating today() would silently shift patient ages and visit dates on
# every rerun and break the CLI's smoke-test golden-comparison contract.
# ---------------------------------------------------------------------------

TEST_ENCOUNTER_AGE_MIN: int = 30
"""Inclusive lower bound of the ``--age``-fallback random age draw for
``clinosim test-encounter``. 30 skips pediatric edge cases (which the
simulator does not model) while keeping the young-adult presentation
in range."""

TEST_ENCOUNTER_AGE_MAX_EXCLUSIVE: int = 85
"""Exclusive upper bound of the ``--age``-fallback random age draw
(yields ages 30-84)."""

TEST_ENCOUNTER_REFERENCE_YEAR: int = 2024
"""Reference year for the synthetic visit datetime — pinned for
reproducibility across time."""

TEST_ENCOUNTER_REFERENCE_MONTH: int = 6
"""Reference month for the synthetic visit datetime (mid-year, June)."""

TEST_ENCOUNTER_REFERENCE_DAY: int = 15
"""Reference day-of-month for the synthetic visit datetime (mid-month)
— places the timestamp far from any month/quarter/year boundary that
could interact with seasonal or calendar-based enrichers."""

TEST_ENCOUNTER_VISIT_HOUR_MIN: int = 8
"""Inclusive lower bound of the visit-hour draw (8 AM). Matches
typical clinic opening / ED daytime peak."""

TEST_ENCOUNTER_VISIT_HOUR_MAX_EXCLUSIVE: int = 20
"""Exclusive upper bound of the visit-hour draw (8 PM). Yields
hours 8-19."""


def _run_test_encounter(args: Any) -> None:
    """test-encounter dispatch (AD-65 Phase 4 / Task 17).

    -o omitted (default): original stdout debug print, unchanged.
    -o set: mini-generate (N patients of one encounter condition) through the full
    3-stage pipeline (structural CIF + template narrative + FHIR/CSV export) so a
    bug can be verified in ~10s without regenerating a full cohort.
    """
    if args.output:
        _run_test_encounter_generate(args)
        return
    _run_test_encounter_debug(args)


def _run_test_encounter_debug(args: Any) -> None:
    """Original test-encounter behavior: simulate + print debug record per patient."""
    from clinosim.modules.encounter.protocol import load_encounter_condition
    from clinosim.modules.population.engine import PersonRecord

    rng = determinism.default_rng(args.seed)
    roster = generate_roster("medium", args.country, rng)

    # Load protocol
    try:
        protocol = load_encounter_condition(args.condition_id)
    except FileNotFoundError:
        print(f"❌ Encounter condition '{args.condition_id}' not found.")
        print("Run 'clinosim list-diseases' to see available conditions.")
        return

    enc_type = protocol.get("encounter_type", "emergency")
    print(f"\n{'=' * 60}")
    print(f"  test-encounter: {args.condition_id}")
    print(f"  Type: {enc_type} | Dept: {protocol.get('department', '?')}")
    print(f"  Chief: {protocol.get('chief_complaint', '?')}")
    print(f"{'=' * 60}")

    from clinosim.locale.loader import load_demographics as _ld

    _demo = _ld(args.country)
    for i in range(args.count):
        # Create patient
        age = args.age or int(rng.integers(TEST_ENCOUNTER_AGE_MIN, TEST_ENCOUNTER_AGE_MAX_EXCLUSIVE))
        sex = args.sex or str(rng.choice(["M", "F"]))
        person = PersonRecord(
            person_id=f"TEST-{i + 1:04d}",
            household_id=f"HH-TEST-{i + 1:04d}",
            age=age,
            sex=sex,
            date_of_birth=__import__("datetime").date(2024 - age, 1, 1),
        )
        patient = activate_patient(person, rng, _demo)

        visit_time = datetime(
            TEST_ENCOUNTER_REFERENCE_YEAR,
            TEST_ENCOUNTER_REFERENCE_MONTH,
            TEST_ENCOUNTER_REFERENCE_DAY,
            int(rng.integers(TEST_ENCOUNTER_VISIT_HOUR_MIN, TEST_ENCOUNTER_VISIT_HOUR_MAX_EXCLUSIVE)),
            int(rng.integers(0, 60)),
        )
        record = _simulate_ed_visit(patient, protocol, visit_time, roster, rng, country=args.country)

        _print_debug_record(record, i + 1)


def _run_test_encounter_generate(args: Any) -> None:
    """Mini-generate: N patients of a specific encounter condition + CIF + narrative + FHIR/CSV.

    Produces the same on-disk layout as `clinosim generate` (cif/structural,
    cif/narratives/template, fhir_r4/*.ndjson, csv/*) but scoped to one encounter
    condition and a tiny cohort — the AD-65 Phase 4 dev facility for 10-second
    targeted verify.
    """
    from clinosim.locale.loader import load_demographics as _ld
    from clinosim.modules.document.narrative.passes import TemplateNarrativePass
    from clinosim.modules.encounter.protocol import load_encounter_condition
    from clinosim.modules.output.cif_writer import write_cif
    from clinosim.modules.population.engine import PersonRecord
    from clinosim.simulator.enrichers import register_builtin_enrichers

    # F-2 fix (adv-1): enricher registry only fills up on demand — full
    # `run_beta` orchestrator calls this, but the mini test-encounter path
    # bypasses run_beta. Without this, POST_ENCOUNTER runs zero enrichers
    # even with a config passed to _simulate_ed_visit.
    register_builtin_enrichers()

    cif_dir = os.path.join(args.output, "cif")

    rng = determinism.default_rng(args.seed)
    roster = generate_roster("medium", args.country, rng)

    # Load protocol
    try:
        protocol = load_encounter_condition(args.condition_id)
    except FileNotFoundError:
        print(f"❌ Encounter condition '{args.condition_id}' not found.")
        print("Run 'clinosim list-diseases' to see available conditions.")
        return

    print(
        f"clinosim test-encounter (generate): {args.condition_id} x{args.count}, "
        f"country={args.country} -> {args.output}"
    )

    _demo = _ld(args.country)

    # F-2 fix (adv-1): mirror _run_test_disease_generate — build a
    # SimulatorConfig so _simulate_ed_visit runs the POST_ENCOUNTER stage
    # (triage_enricher + document_enricher). Without a config the ED-only
    # POST_ENCOUNTER gate in emergency.py:276 short-circuits, producing
    # zero triage_data and zero ED_NOTE / ED_TRIAGE_NOTE documents on the
    # generated CIF — exactly the α-min-2 gap this dev facility exists to
    # catch, silently reintroduced.
    config = SimulatorConfig(
        random_seed=args.seed,
        country=args.country,
        catchment_population=args.count,
    )

    records: list[CIFPatientRecord] = []
    for i in range(args.count):
        # Create patient
        age = args.age or int(rng.integers(TEST_ENCOUNTER_AGE_MIN, TEST_ENCOUNTER_AGE_MAX_EXCLUSIVE))
        sex = args.sex or str(rng.choice(["M", "F"]))
        person = PersonRecord(
            person_id=f"TEST-{i + 1:04d}",
            household_id=f"HH-TEST-{i + 1:04d}",
            age=age,
            sex=sex,
            date_of_birth=__import__("datetime").date(2024 - age, 1, 1),
        )
        patient = activate_patient(person, rng, _demo)

        visit_time = datetime(
            TEST_ENCOUNTER_REFERENCE_YEAR,
            TEST_ENCOUNTER_REFERENCE_MONTH,
            TEST_ENCOUNTER_REFERENCE_DAY,
            int(rng.integers(TEST_ENCOUNTER_VISIT_HOUR_MIN, TEST_ENCOUNTER_VISIT_HOUR_MAX_EXCLUSIVE)),
            int(rng.integers(0, 60)),
        )
        record = _simulate_ed_visit(
            patient,
            protocol,
            visit_time,
            roster,
            rng,
            country=args.country,
            config=config,
        )
        records.append(record)

    # Build CIFDataset for this encounter cohort
    dataset = CIFDataset(
        metadata=CIFMetadata(
            clinosim_version=_clinosim_version,
            generation_timestamp=datetime.now(),
            random_seed=args.seed,
            country=args.country,
            hospital_scale="medium",
            total_patients_generated=len(records),
        ),
        patients=records,
        hospital_roster=list(roster.members),
        hospital_config={},
    )

    write_cif(dataset, cif_dir)

    # Stage 2 (AD-65): always run the template narrative pass, mirroring `generate`'s
    # auto-invoke, so the mini-cohort is emit-ready regardless of which export
    # format(s) were requested.
    TemplateNarrativePass(
        cif_dir=cif_dir,
        version_id="template",
        country=args.country,
        rng_seed=args.seed,
    ).run()
    os.makedirs(os.path.join(cif_dir, "narratives"), exist_ok=True)
    with open(os.path.join(cif_dir, "narratives", "current_version.txt"), "w") as f:
        f.write("template")

    # Format exports via the adapter registry (AD-58) — reuse the same `_run_exports`
    # dispatch as `generate` (single edit point for adding a new output format).
    formats = args.format or []
    if "all" in formats:
        formats = ["fhir-r4", "csv"]
    _run_exports(formats, cif_dir, args.output, args.country)

    _print_summary(dataset, args.output)
