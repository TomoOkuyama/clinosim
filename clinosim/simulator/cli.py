"""CLI entry point for clinosim."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from typing import Any

import numpy as np

from clinosim.modules._shared import is_jp
from clinosim.modules.patient.activator import activate_patient
from clinosim.modules.staff.engine import generate_roster
from clinosim.simulator.emergency import _simulate_ed_visit
from clinosim.simulator.engine import run_beta, run_forced
from clinosim.simulator.helpers import _load_all_disease_protocols
from clinosim.types.config import ForcedScenario, PatientProfile, SimulatorConfig
from clinosim.types.encounter import EncounterType
from clinosim.types.output import CIFDataset, CIFMetadata, CIFPatientRecord


def main() -> None:
    """CLI entry point: clinosim [command] [options]"""
    import argparse

    parser = argparse.ArgumentParser(
        prog="clinosim",
        description="Clinically Realistic Hospital Data Simulator",
    )
    sub = parser.add_subparsers(dest="command", help="Command to run")

    # === generate: population-driven simulation ===
    gen = sub.add_parser("generate", help="Generate patient data from population simulation")
    gen.add_argument("-o", "--output", default="./output", help="Output directory")
    gen.add_argument(
        "-p",
        "--population",
        type=int,
        default=argparse.SUPPRESS,
        help="Catchment population (default: hospital recommended)",
    )
    gen.add_argument("-s", "--seed", type=int, default=42, help="Random seed")
    gen.add_argument("--country", default="US", help="Country code (US or JP)")
    gen.add_argument(
        "--start",
        default=None,
        help="Simulation start date YYYY-MM-DD (default: 1 year before --end)",
    )
    gen.add_argument(
        "--end",
        default=None,
        help="Simulation end date / snapshot date YYYY-MM-DD (default: today). Inpatients still admitted on this date have no discharge.",
    )
    gen.add_argument(
        "--format",
        nargs="+",
        default=["cif"],
        help="Output formats: cif, csv, fhir-r4 (alias: fhir). "
        "Add more by registering an OutputAdapter (AD-58).",
    )
    gen.add_argument(
        "--hospital-config",
        default=None,
        help="Hospital operations YAML (default: config/hospital_operations.yaml)",
    )
    gen.add_argument(
        "--jp-insurance",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="(JP only) Include Japanese insurance enrollment / 被保険者番号 "
        "(emitted as FHIR Coverage). Use --no-jp-insurance to omit. "
        "Ignored for non-JP countries.",
    )

    # === test-disease: generate specific disease/archetype ===
    td = sub.add_parser("test-disease", help="Generate data for a specific disease and archetype")
    td.add_argument(
        "disease_id",
        nargs="?",
        default=None,
        help="Disease ID (e.g., bacterial_pneumonia); optional when --patient-profile is set",
    )
    td.add_argument(
        "--patient-profile",
        default=None,
        help="Patient profile fixture name or path (AD-66); "
        "CLI args override profile fields with stderr WARN",
    )
    # adv-1 F-2: -n/--seed/--country default to None (not 3/42/US) so an EXPLICIT
    # value equal to the old default is distinguishable from "flag omitted" when
    # resolving against a --patient-profile. Legacy defaults are applied in
    # _resolve_test_disease_defaults when the flag is omitted and no profile
    # supplies a value — non-profile behavior is unchanged.
    td.add_argument(
        "-n", "--count", type=int, default=None,
        help="Number of patients (default: 3, or profile count)",
    )
    td.add_argument("--severity", default=None, help="Force severity: mild/moderate/severe")
    td.add_argument("--archetype", default=None, help="Force archetype name")
    td.add_argument(
        "-s", "--seed", type=int, default=None,
        help="Random seed (default: 42, or profile random_seed)",
    )
    td.add_argument(
        "--country", default=None,
        help="Country code (US or JP; default: US, or profile country)",
    )
    # AD-65 Phase 4 (Task 16): when -o is set, run the full 3-stage pipeline
    # (structural + narrative + FHIR/CSV) for a tiny disease-specific cohort — a
    # 10-second targeted verify without regenerating a full cohort. When -o is
    # omitted (default), the original stdout debug print is unchanged.
    td.add_argument(
        "--format",
        nargs="+",
        default=None,
        choices=["cif", "fhir-r4", "csv", "all"],
        help="Output formats (requires -o/--output; if omitted, stdout debug only)",
    )
    td.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output directory (required when --format is set)",
    )

    # === validate: run quality checks on generated data ===
    val = sub.add_parser("validate", help="Run data quality checks on generated data")
    val.add_argument("-p", "--population", type=int, default=5_000, help="Population size")
    val.add_argument("-s", "--seed", type=int, default=42, help="Random seed")
    val.add_argument("--country", default="US", help="Country code")

    # === list-diseases: show available disease protocols ===
    sub.add_parser("list-diseases", help="List all available disease protocols")

    # === narrate: Stage 2 template narrative generation (AD-65) ===
    nr = sub.add_parser(
        "narrate",
        help="Generate narrative CIF from a structural CIF directory (AD-65 Stage 2)",
    )
    nr.add_argument("--cif-dir", required=True, help="Path to structural CIF directory")
    nr.add_argument(
        "--provider",
        default="template",
        choices=["template", "bedrock", "ollama", "mock"],
        help=(
            "Narrative generator: 'template' (default, deterministic) or an "
            "LLM provider run through LLMNarrativePass — 'bedrock' / 'ollama' "
            "(configured via config/llm_service*.yaml or --llm-config) or "
            "'mock' (deterministic MockProvider, dev/test only)"
        ),
    )
    nr.add_argument(
        "--llm-config",
        default=None,
        help=(
            "Path to an LLM service YAML (see clinosim/config/llm_service*.yaml). "
            "Default: bedrock -> config/llm_service.bedrock.yaml, "
            "ollama -> config/llm_service.yaml, mock -> in-code MockProvider"
        ),
    )
    nr.add_argument(
        "--version-id",
        default=None,
        help="Narrative version directory name (default: provider name)",
    )
    nr.add_argument(
        "--tasks", default=None, help="Comma-separated LLMTaskType filter (default: all)"
    )
    nr.add_argument("--country", default="US")
    nr.add_argument(
        "--set-current",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Update current_version.txt to point to the new version. "
            "Default: yes for --provider template, no for LLM providers "
            "(bedrock/ollama/mock) so a trial run cannot silently repoint "
            "production exports (M-3, N-chain adv-1). Explicit "
            "--set-current / --no-set-current always wins"
        ),
    )
    nr.add_argument("--seed", type=int, default=42, help="RNG seed for determinism")
    nr.add_argument(
        "--patient-filter",
        default=None,
        help=(
            "Regex over patient filename stem / patient_id — narrate only "
            "matching patients (remote per-patient iteration, chain 1b T3). "
            "The version manifest records the filter. Default: all patients"
        ),
    )

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

    # === test-encounter: debug single encounter condition ===
    te = sub.add_parser(
        "test-encounter", help="Simulate one patient for an encounter condition (debug)"
    )
    te.add_argument(
        "condition_id", help="Condition ID (e.g., chest_pain_noncardiac, flu_vaccination)"
    )
    te.add_argument("-n", "--count", type=int, default=1, help="Number of patients")
    te.add_argument("-s", "--seed", type=int, default=42, help="Random seed")
    te.add_argument("--country", default="US", help="Country code")
    te.add_argument("--age", type=int, default=None, help="Force patient age")
    te.add_argument("--sex", default=None, help="Force patient sex (M/F)")
    # AD-65 Phase 4 (Task 17): mirrors test-disease pattern — when -o is set, run the
    # full 3-stage pipeline (structural CIF + template narrative + FHIR/CSV) for a tiny
    # encounter-specific cohort. When -o is omitted (default), original stdout debug
    # print is unchanged.
    te.add_argument(
        "--format",
        nargs="+",
        default=None,
        choices=["cif", "fhir-r4", "csv", "all"],
        help="Output formats (requires -o/--output; if omitted, stdout debug only)",
    )
    te.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output directory (required when --format is set)",
    )

    # === regenerate-goldens: AD-66 α-min-2c golden narrative bootstrap ===
    rg = sub.add_parser(
        "regenerate-goldens",
        help="Regenerate narrative goldens for canonical patient profiles (AD-66)",
    )
    rg_group = rg.add_mutually_exclusive_group(required=True)
    rg_group.add_argument(
        "--profile",
        default=None,
        help="Regenerate a single profile by name",
    )
    rg_group.add_argument(
        "--all",
        action="store_true",
        help="Regenerate goldens for all profiles in the fixtures dir",
    )
    # β-JP-1 chain 1b T1: LLM parallel goldens. template (default) keeps the
    # historical <name>.golden.json naming; LLM providers write
    # <name>.llm-<tag>.golden.json via a `narrate --provider` subprocess step.
    rg.add_argument(
        "--provider",
        default="template",
        choices=["template", "mock", "bedrock", "ollama"],
        help=(
            "Narrative generator for the golden run: 'template' (default, "
            "writes <name>.golden.json — unchanged) or an LLM provider "
            "(mock/bedrock/ollama, writes <name>.llm-<tag>.golden.json)"
        ),
    )
    rg.add_argument(
        "--llm-config",
        default=None,
        help="LLM service YAML passed through to narrate (LLM providers only)",
    )
    rg.add_argument(
        "--model-tag",
        default=None,
        help=(
            "Filename tag for LLM goldens: <name>.llm-<tag>.golden.json "
            "(default: provider name, e.g. mock). LLM providers only"
        ),
    )
    # T3 guard: declared ONLY so that combining it with regenerate-goldens is
    # rejected loudly (goldens must always cover the full profile cohort —
    # a partial golden would silently pass byte-diff on the subset).
    rg.add_argument(
        "--patient-filter",
        default=None,
        help="NOT allowed here — goldens must never be partial. Use `narrate --patient-filter`",
    )

    # === check-narratives: β-JP-1 chain 1b T2 semantic check ===
    cn = sub.add_parser(
        "check-narratives",
        help=(
            "Semantic check of a narrative version (5 axes; the LLM-output "
            "gate where byte-diff does not apply). Exit 0 = pass, 1 = findings"
        ),
    )
    cn.add_argument("--cif-dir", required=True, help="Path to a CIF directory")
    cn.add_argument(
        "--version", required=True,
        help="Narrative version id to check (e.g. llm-mock, ollama)",
    )
    cn.add_argument(
        "--profile",
        default=None,
        help=(
            "Patient profile name — resolves expectations to "
            "tests/fixtures/patient_profiles/<name>.llm-expectations.yaml"
        ),
    )
    cn.add_argument(
        "--expectations",
        default=None,
        help="Explicit expectations YAML path (overrides --profile resolution)",
    )
    cn.add_argument(
        "--report",
        default=None,
        help="Write the full SemanticCheckReport as JSON to this path",
    )

    # === audit: verification framework ===
    from clinosim.audit.cli import add_audit_subparser

    add_audit_subparser(sub)

    args = parser.parse_args()

    if args.command == "audit":
        import sys

        from clinosim.audit.cli import dispatch_audit

        sys.exit(dispatch_audit(args))

    if args.command == "list-diseases":
        protocols = _load_all_disease_protocols()
        print(f"\n{len(protocols)} inpatient disease protocols:")
        for name in sorted(protocols.keys()):
            p = protocols[name]
            print(f"  {name:35s} | {p.chief_complaint[:50]}")

        from clinosim.modules.encounter.protocol import load_all_encounter_conditions

        ed_conditions = load_all_encounter_conditions()
        print(f"\n{len(ed_conditions)} ED/outpatient encounter conditions:")
        for name in sorted(ed_conditions.keys()):
            c = ed_conditions[name]
            print(f"  {name:35s} | {c.get('chief_complaint', '')[:50]}")
        return

    if args.command == "test-encounter":
        if args.format and not args.output:
            parser.error("--format requires -o/--output to be set")
        _run_test_encounter(args)
        return

    if args.command == "test-disease":
        if args.format and not args.output:
            parser.error("--format requires -o/--output to be set")
        _run_test_disease(args)
        return

    if args.command == "regenerate-goldens":
        _run_regenerate_goldens(args)
        return

    if args.command == "narrate":
        _run_narrate(args)
        return

    if args.command == "check-narratives":
        _run_check_narratives(args)
        return

    if args.command == "export-fhir":
        _run_export_fhir(args)
        return

    if args.command == "validate":
        config = SimulatorConfig(
            catchment_population=args.population,
            random_seed=args.seed,
            country=args.country,
        )
        print(f"clinosim validate: pop={args.population}, country={args.country}")
        dataset = run_beta(config)
        _run_quality_checks(dataset)
        return

    if args.command == "generate":
        _validate_formats(args.format, parser)  # fail fast on bad --format (AD-58)
        from datetime import date
        from datetime import timedelta as _td

        # Default end = today, default start = end - 1 year
        end_date = datetime.strptime(args.end, "%Y-%m-%d").date() if args.end else date.today()
        start_date = (
            datetime.strptime(args.start, "%Y-%m-%d").date()
            if args.start
            else end_date - _td(days=365)
        )
        end = end_date.strftime("%Y-%m-%d")
        start = start_date.strftime("%Y-%m-%d")
        # Bug D fix: -p uses argparse.SUPPRESS as default, so args.population is only
        # present when the user explicitly passed -p/--population. None → engine.py
        # resolves to the hospital's recommended_population; never a silent sentinel.
        population_arg = getattr(args, "population", None)
        config = SimulatorConfig(
            catchment_population=population_arg,
            time_range=(start, end),
            random_seed=args.seed,
            country=args.country,
            snapshot_date=end,
            jp_insurance_numbers=args.jp_insurance,
        )
        hospital_cfg = getattr(args, "hospital_config", None)
        pop_label = str(population_arg) if population_arg is not None else "hospital recommended"
        print(
            f"clinosim generate: population={pop_label}, seed={args.seed}, country={args.country}, period={start}~{end}"
        )
        if is_jp(args.country):
            status = "on" if args.jp_insurance else "off"
            print(f"  JP insurance numbers (被保険者番号): {status}")
        if hospital_cfg:
            print(f"  Hospital config: {hospital_cfg}")
        dataset = run_beta(config, hospital_config_path=hospital_cfg)

    else:
        parser.print_help()
        return

    # Output
    from clinosim.modules.output.cif_writer import write_cif

    cif_dir = os.path.join(args.output, "cif")
    write_cif(dataset, cif_dir)

    # Stage 2 (AD-65): auto-invoke the template narrative pass so cohorts are
    # always emit-ready. `clinosim narrate` remains available to regenerate
    # (or LLM-narrate, once β-JP-1 lands) on top of an existing structural CIF.
    from clinosim.modules.document.narrative.passes import TemplateNarrativePass

    _narrative_pass = TemplateNarrativePass(
        cif_dir=cif_dir,
        version_id="template",
        country=args.country,
        rng_seed=args.seed,
    )
    _narrative_pass.run()
    os.makedirs(os.path.join(cif_dir, "narratives"), exist_ok=True)
    with open(os.path.join(cif_dir, "narratives", "current_version.txt"), "w") as f:
        f.write("template")

    # Format exports via the adapter registry (AD-58). Add a format = register an adapter.
    # DocumentReference resources are emitted from record.documents (Stage 1 enricher).
    _run_exports(
        args.format,
        cif_dir,
        args.output,
        getattr(args, "country", "US"),
    )

    # Summary
    _print_summary(dataset, args.output)


# Back-compat alias: legacy "--format fhir" means FHIR R4.
_FORMAT_ALIASES = {"fhir": "fhir-r4"}


def _validate_formats(formats: list[str], parser: Any) -> None:
    """Fail fast with a clean parser error on an unknown --format, before generation runs."""
    from clinosim.modules.output.adapter import get_adapter

    for fmt in formats:
        resolved = _FORMAT_ALIASES.get(fmt, fmt)
        if resolved == "cif":
            continue
        try:
            get_adapter(resolved)
        except KeyError as e:
            parser.error(str(e))


def _run_exports(
    formats: list[str],
    cif_dir: str,
    output_root: str,
    country: str,
) -> None:
    """Run each requested export format through the adapter registry (AD-58).

    CIF is assumed already written. "cif" is a no-op (CIF-only). Unknown formats raise
    ValueError. Output goes to <output_root>/<adapter.subdir>.
    """
    from clinosim.modules.output.adapter import OutputContext, get_adapter

    ctx = OutputContext(country=country)
    for fmt in formats:
        fmt = _FORMAT_ALIASES.get(fmt, fmt)
        if fmt == "cif":
            continue
        try:
            adapter = get_adapter(fmt)
        except KeyError as e:
            raise ValueError(str(e)) from e
        adapter.convert(cif_dir, os.path.join(output_root, adapter.subdir), ctx)


def _print_summary(dataset: CIFDataset, output_dir: str) -> None:
    """Print a summary report of generated data."""
    from collections import Counter, defaultdict

    all_records = dataset.patients
    inpatients = [
        r
        for r in all_records
        if r.encounters and r.encounters[0].encounter_type.value == "inpatient"
    ]
    outpatients = [
        r
        for r in all_records
        if r.encounters and r.encounters[0].encounter_type.value == "outpatient"
    ]
    readmits = [r for r in inpatients if r.is_readmission]
    deceased = [r for r in all_records if r.deceased]

    print(f"\n{'=' * 50}")
    print("  clinosim generation complete")
    print(f"{'=' * 50}")
    print(f"  Total records:  {len(all_records)}")
    print(f"    Inpatient:    {len(inpatients)} ({len(readmits)} readmissions)")
    print(f"    Outpatient:   {len(outpatients)}")
    print(f"    Deceased:     {len(deceased)}")
    print("  Data volume:")
    print(f"    Lab results:  {sum(len(r.lab_results) for r in all_records):,}")
    print(f"    Vital signs:  {sum(len(r.vital_signs) for r in all_records):,}")
    print(f"    MAR entries:  {sum(len(r.medication_administrations) for r in all_records):,}")
    print(f"    I/O records:  {sum(len(r.intake_output_records) for r in all_records):,}")
    print(f"    Orders:       {sum(len(r.orders) for r in all_records):,}")

    # Disease distribution (inpatient only)
    by_disease = Counter()
    los_by_disease = defaultdict(list)
    for r in inpatients:
        d = (
            r.condition_event.ground_truth_diseases[0]
            if r.condition_event.ground_truth_diseases
            else "?"
        )
        by_disease[d] += 1
        los_by_disease[d].append(len(r.physiological_states) - 1)

    if by_disease:
        print("\n  Disease distribution (inpatient):")
        for d, n in by_disease.most_common(10):
            avg_los = sum(los_by_disease[d]) / len(los_by_disease[d])
            print(f"    {d:30s} {n:4d}  (LOS avg {avg_los:.1f}d)")

    print(f"\n  Output: {output_dir}/")


def _run_quality_checks(dataset: CIFDataset) -> None:
    """Run comprehensive quality checks on generated data."""
    from collections import Counter

    records = dataset.patients
    inpatients = [
        r
        for r in records
        if r.encounters and r.encounters[0].encounter_type == EncounterType.INPATIENT
    ]
    outpatients = [
        r
        for r in records
        if r.encounters and r.encounters[0].encounter_type == EncounterType.OUTPATIENT
    ]
    ed_visits = [
        r
        for r in records
        if r.encounters and r.encounters[0].encounter_type == EncounterType.EMERGENCY
    ]

    print(f"\n{'=' * 50}")
    print("  Data Quality Report")
    print(f"{'=' * 50}")
    print(
        f"  Records: {len(records)} (inp={len(inpatients)}, opd={len(outpatients)}, ed={len(ed_visits)})"
    )

    issues = 0

    # Check: labs have units
    no_unit = sum(1 for r in records for l in r.lab_results if not l.unit)
    if no_unit:
        print(f"  ❌ Labs missing units: {no_unit}")
        issues += 1
    else:
        print("  ✅ All labs have units")

    # Check: all records have diagnosis
    no_dx = sum(1 for r in records if not r.clinical_diagnosis.discharge_diagnosis_code)
    if no_dx:
        print(f"  ❌ Records missing diagnosis: {no_dx}")
        issues += 1
    else:
        print("  ✅ All records have diagnosis codes")

    # Check: inpatients have vitals, labs, MARs
    inp_no_vitals = sum(1 for r in inpatients if not r.vital_signs)
    inp_no_labs = sum(1 for r in inpatients if not r.lab_results)
    inp_no_mars = sum(1 for r in inpatients if not r.medication_administrations)
    for name, count in [("vitals", inp_no_vitals), ("labs", inp_no_labs), ("MARs", inp_no_mars)]:
        if count:
            print(f"  ❌ Inpatients missing {name}: {count}")
            issues += 1
        else:
            print(f"  ✅ All inpatients have {name}")

    # Check: ward/bed
    inp_no_ward = sum(1 for r in inpatients if not r.encounters[0].ward_id)
    print(
        f"  {'❌' if inp_no_ward else '✅'} Ward/bed assignment: {len(inpatients) - inp_no_ward}/{len(inpatients)}"
    )
    if inp_no_ward:
        issues += 1

    # Check: pain scores
    vitals_with_pain = sum(1 for r in records for v in r.vital_signs if v.pain_score is not None)
    total_vitals = sum(len(r.vital_signs) for r in records)
    pct = vitals_with_pain / total_vitals * 100 if total_vitals else 0
    print(f"  ✅ Pain scores: {pct:.0f}% of vitals")

    # Check: ADL for inpatients
    adl_count = sum(len(r.adl_assessments) for r in inpatients)
    print(
        f"  ✅ ADL assessments: {adl_count} (avg {adl_count / len(inpatients):.1f}/patient)"
        if inpatients
        else "  - No inpatients"
    )

    # Check: I/O for inpatients
    io_count = sum(len(r.intake_output_records) for r in inpatients)
    print(f"  ✅ I/O records: {io_count}")

    # Check: diet orders
    diet_count = sum(1 for r in inpatients if any(o.order_type.value == "diet" for o in r.orders))
    print(f"  ✅ Diet orders: {diet_count}/{len(inpatients)} inpatients")

    # Disease distribution
    by_disease = Counter()
    for r in inpatients:
        d = (
            r.condition_event.ground_truth_diseases[0]
            if r.condition_event.ground_truth_diseases
            else "?"
        )
        by_disease[d] += 1
    print(f"\n  Disease distribution ({len(by_disease)} types):")
    for d, n in by_disease.most_common(5):
        print(f"    {d:30s} {n:4d}")
    if len(by_disease) > 5:
        print(f"    ... and {len(by_disease) - 5} more")

    # Readmission check
    readmits = sum(1 for r in inpatients if r.is_readmission)
    rate = readmits / (len(inpatients) - readmits) * 100 if len(inpatients) > readmits else 0
    print(f"\n  Readmission rate: {rate:.1f}% ({readmits} readmissions)")

    # Mortality
    deceased = sum(1 for r in records if r.deceased)
    mort_rate = deceased / len(inpatients) * 100 if inpatients else 0
    print(f"  Mortality rate: {mort_rate:.1f}% ({deceased} deaths)")

    print(f"\n  {'✅ ALL CHECKS PASSED' if issues == 0 else f'⚠ {issues} ISSUES FOUND'}")


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

    rng = np.random.default_rng(args.seed)
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
        age = args.age or int(rng.integers(30, 85))
        sex = args.sex or str(rng.choice(["M", "F"]))
        person = PersonRecord(
            person_id=f"TEST-{i + 1:04d}",
            household_id=f"HH-TEST-{i + 1:04d}",
            age=age,
            sex=sex,
            date_of_birth=__import__("datetime").date(2024 - age, 1, 1),
        )
        patient = activate_patient(person, rng, _demo)

        visit_time = datetime(2024, 6, 15, int(rng.integers(8, 20)), int(rng.integers(0, 60)))
        record = _simulate_ed_visit(
            patient, protocol, visit_time, roster, rng, country=args.country
        )

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

    rng = np.random.default_rng(args.seed)
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
        age = args.age or int(rng.integers(30, 85))
        sex = args.sex or str(rng.choice(["M", "F"]))
        person = PersonRecord(
            person_id=f"TEST-{i + 1:04d}",
            household_id=f"HH-TEST-{i + 1:04d}",
            age=age,
            sex=sex,
            date_of_birth=__import__("datetime").date(2024 - age, 1, 1),
        )
        patient = activate_patient(person, rng, _demo)

        visit_time = datetime(2024, 6, 15, int(rng.integers(8, 20)), int(rng.integers(0, 60)))
        record = _simulate_ed_visit(
            patient, protocol, visit_time, roster, rng,
            country=args.country, config=config,
        )
        records.append(record)

    # Build CIFDataset for this encounter cohort
    dataset = CIFDataset(
        metadata=CIFMetadata(
            clinosim_version="0.2",
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


# test-disease legacy defaults (adv-1 F-2). Kept out of the argparse defaults so
# an explicit `--seed 42` / `--country US` / `-n 3` is distinguishable from
# "flag omitted" when resolving against a --patient-profile.
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
                f"WARN: {label}={cli_value!r} differs from profile {field}="
                f"{profile_value!r}; using {label}",
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


def _run_regenerate_goldens(args: Any) -> None:
    """AD-66 α-min-2c T3: regenerate narrative goldens for canonical profiles.

    For each target profile: run test-disease pipeline into a tmpdir, walk
    cif/narratives/<version>/documents/**/*.json, write the merged dict to
    the golden path in the fixture dir. Emits stderr note prompting user to
    `git diff + commit if intentional`.

    β-JP-1 chain 1b T1: ``--provider mock|bedrock|ollama`` inserts a
    ``narrate --provider`` subprocess step on top of the structural CIF and
    writes ``<profile>.llm-<tag>.golden.json`` instead (template golden
    naming unchanged). ``<tag>`` defaults to the provider name; override
    with ``--model-tag`` (e.g. a real model id on the remote LLM server).
    """
    import json
    import subprocess
    import tempfile

    from clinosim.types.config import _PATIENT_PROFILE_DIR, load_patient_profile

    if getattr(args, "patient_filter", None):
        print(
            "ERROR: regenerate-goldens must never write partial goldens — "
            "--patient-filter is not allowed here. Iterate with "
            "`clinosim narrate --patient-filter`, then regenerate WITHOUT a filter",
            file=sys.stderr,
        )
        sys.exit(2)

    provider: str = getattr(args, "provider", "template")
    if provider == "template" and (args.model_tag or args.llm_config):
        print(
            "ERROR: --model-tag / --llm-config require an LLM --provider "
            "(mock/bedrock/ollama); they have no effect with --provider template",
            file=sys.stderr,
        )
        sys.exit(2)
    tag = args.model_tag or provider

    # Support env var override for test isolation
    fixture_dir_env = os.environ.get("CLINOSIM_PATIENT_PROFILE_DIR")
    from pathlib import Path

    fixture_dir = Path(fixture_dir_env) if fixture_dir_env else _PATIENT_PROFILE_DIR

    if args.all:
        profile_paths = sorted(
            p for p in fixture_dir.glob("*.yaml")
            if not p.name.endswith(".llm-expectations.yaml")
        )
    else:
        p = fixture_dir / f"{args.profile}.yaml"
        if not p.is_file():
            print(f"ERROR: profile not found: {p}", file=sys.stderr)
            sys.exit(2)
        profile_paths = [p]

    if not profile_paths:
        print(f"ERROR: no profiles found in {fixture_dir}", file=sys.stderr)
        sys.exit(2)

    def _run_step(cmd: list[str], label: str) -> None:
        """Run one pipeline subprocess; fail loud with its stderr on error."""
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            print(f"ERROR: {label} failed (exit {result.returncode}):", file=sys.stderr)
            print(result.stderr, file=sys.stderr)
            sys.exit(1)

    count = 0
    for profile_path in profile_paths:
        profile_id = profile_path.stem
        with tempfile.TemporaryDirectory() as tmpdir:
            _run_step(
                [sys.executable, "-m", "clinosim.simulator.cli", "test-disease",
                 "--patient-profile", str(profile_path),
                 "--format", "cif", "-o", str(tmpdir)],
                label=f"test-disease ({profile_id})",
            )
            cif_dir = Path(tmpdir) / "cif"

            if provider == "template":
                narr_version = "template"
                golden_path = fixture_dir / f"{profile_id}.golden.json"
            else:
                # LLM golden: narrate the structural CIF with the requested
                # provider. Country/seed come from the profile (the pipeline
                # subprocess above already used them for Stage 1).
                narr_version = f"llm-{tag}"
                profile = load_patient_profile(str(profile_path))
                narrate_cmd = [
                    sys.executable, "-m", "clinosim.simulator.cli", "narrate",
                    "--cif-dir", str(cif_dir), "--provider", provider,
                    "--country", profile.country,
                    "--seed", str(profile.random_seed),
                    "--version-id", narr_version, "--no-set-current",
                ]
                if args.llm_config:
                    narrate_cmd += ["--llm-config", args.llm_config]
                _run_step(narrate_cmd, label=f"narrate --provider {provider} ({profile_id})")
                golden_path = fixture_dir / f"{profile_id}.llm-{tag}.golden.json"

            narr_dir = cif_dir / "narratives" / narr_version / "documents"
            actual: dict[str, dict] = {}
            if narr_dir.is_dir():
                for enc_dir in sorted(narr_dir.iterdir()):
                    if not enc_dir.is_dir():
                        continue
                    for doc_file in sorted(enc_dir.iterdir()):
                        if doc_file.suffix != ".json":
                            continue
                        actual[doc_file.stem] = json.loads(doc_file.read_text())

            golden_path.write_text(
                json.dumps(actual, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
            )
            count += 1
            print(f"regenerated: {golden_path}", file=sys.stderr)

    print(
        f"Regenerated {count} golden(s). Review + git diff + commit if intentional.",
        file=sys.stderr,
    )


def _print_debug_record(record: CIFPatientRecord, index: int = 1) -> None:
    """Print detailed debug output for a single patient record."""
    r = record
    enc = r.encounters[0] if r.encounters else None
    los = len(r.physiological_states) - 1 if r.physiological_states else 0

    print(f"\n--- Patient {index}: {r.patient.patient_id} ---")
    print(
        f"  {r.patient.age}yo {r.patient.sex} | Chronic: {[c.code for c in r.patient.chronic_conditions]}"
    )
    if enc:
        print(f"  Encounter: {enc.encounter_type.value} | {enc.encounter_id}")
        print(f"  Chief: {enc.chief_complaint}")
        print(f"  Admit: {enc.admission_datetime}")
        print(f"  Discharge: {enc.discharge_datetime}")
        if enc.ward_id:
            print(f"  Ward: {enc.ward_id} Bed: {enc.bed_number}")
    if los > 0:
        print(f"  LOS: {los} days | Deceased: {r.deceased}")
    from clinosim.codes import lookup as _code_lookup

    _dx_name = _code_lookup(
        r.clinical_diagnosis.discharge_diagnosis_system or "icd-10-cm",
        r.clinical_diagnosis.discharge_diagnosis_code,
    )
    print(f"  Dx: {r.clinical_diagnosis.discharge_diagnosis_code} ({_dx_name[:50]})")

    # Orders
    order_types = {}
    for o in r.orders:
        ot = o.order_type.value
        order_types[ot] = order_types.get(ot, 0) + 1
    print(f"\n  Orders ({len(r.orders)}):")
    for ot, n in sorted(order_types.items()):
        print(f"    {ot}: {n}")

    # Labs
    if r.lab_results:
        print(f"\n  Lab results ({len(r.lab_results)}):")
        for lab in r.lab_results[:10]:
            print(f"    {lab.lab_name:15s} = {lab.value:>8} {lab.unit:10s} {lab.flag or ''}")
        if len(r.lab_results) > 10:
            print(f"    ... and {len(r.lab_results) - 10} more")

    # Vitals
    if r.vital_signs:
        v = r.vital_signs[0]
        print(f"\n  Vitals (first of {len(r.vital_signs)}):")
        print(
            f"    T={v.temperature_celsius}C HR={v.heart_rate} BP={v.systolic_bp}/{v.diastolic_bp} "
            f"RR={v.respiratory_rate} SpO2={v.spo2} Pain={v.pain_score}"
        )
        if v.nursing_note:
            print(f"    Note: {v.nursing_note}")

    # MARs
    if r.medication_administrations:
        print(f"\n  Medications ({len(r.medication_administrations)} MAR entries):")
        seen = set()
        for mar in r.medication_administrations:
            if mar.drug_name not in seen:
                print(f"    {mar.drug_name} ({mar.route})")
                seen.add(mar.drug_name)

    # Complications
    if r.complications_occurred:
        print(f"\n  Complications: {r.complications_occurred}")

    # ADL
    if r.adl_assessments:
        print(
            f"\n  ADL: {len(r.adl_assessments)} assessments, "
            f"Barthel {r.adl_assessments[0].barthel_score}→{r.adl_assessments[-1].barthel_score}"
        )

    # I/O
    if r.intake_output_records:
        io = r.intake_output_records[0]
        print(
            f"\n  I/O (Day 1): IV={io.intake_iv_ml}ml Oral={io.intake_oral_ml}ml "
            f"Urine={io.output_urine_ml}ml Net={io.net_balance_ml:+d}ml"
        )

    print()


def _build_llm_service_for_narrate(provider: str, llm_config: str | None) -> Any:
    """Construct the LLMService behind ``narrate --provider <llm>`` (N-chain).

    Resolution order: explicit ``--llm-config PATH`` wins; otherwise
    bedrock → ``config/llm_service.bedrock.yaml``, ollama →
    ``config/llm_service.yaml``, mock → in-code MockProvider (no YAML).
    """
    from clinosim.modules.llm_service.factory import build_from_config_file

    if llm_config:
        return build_from_config_file(llm_config)
    if provider == "mock":
        from clinosim.modules.llm_service.engine import LLMService
        from clinosim.modules.llm_service.providers import MockProvider

        return LLMService(
            mode="llm",
            narrative_provider=MockProvider(),
            narrative_model_map={"medium": "mock"},
            provider_name_narrative="mock",
        )
    import clinosim

    config_dir = os.path.join(os.path.dirname(os.path.abspath(clinosim.__file__)), "config")
    filename = "llm_service.bedrock.yaml" if provider == "bedrock" else "llm_service.yaml"
    return build_from_config_file(os.path.join(config_dir, filename))


def _run_narrate(args: Any) -> None:
    """Stage 2 handler (AD-65): run a NarrativePass over a structural CIF directory.

    --provider template runs TemplateNarrativeGenerator (deterministic,
    default). bedrock / ollama / mock run LLMNarrativePass backed by an
    LLMService (AD-11) built from config/llm_service*.yaml (or --llm-config).
    """
    from clinosim.modules.document.narrative.passes import (
        LLMNarrativePass,
        TemplateNarrativePass,
    )

    version_id = args.version_id or ("template" if args.provider == "template" else args.provider)
    tasks = [t.strip() for t in args.tasks.split(",")] if args.tasks else None

    pass_impl: TemplateNarrativePass | LLMNarrativePass
    if args.provider == "template":
        pass_impl = TemplateNarrativePass(
            cif_dir=args.cif_dir,
            version_id=version_id,
            country=args.country,
            tasks=tasks,
            rng_seed=args.seed,
            patient_filter=args.patient_filter,
        )
    else:
        llm = _build_llm_service_for_narrate(args.provider, args.llm_config)
        pass_impl = LLMNarrativePass(
            cif_dir=args.cif_dir,
            llm=llm,
            version_id=version_id,
            country=args.country,
            tasks=tasks,
            rng_seed=args.seed,
            patient_filter=args.patient_filter,
        )

    manifest = pass_impl.run()
    # M-3 (N-chain adv-1): tri-state --set-current. None (no flag) resolves to
    # True only for the template provider — an LLM/mock trial must not
    # silently repoint current_version.txt (export-fhir defaults to "current",
    # so a repointed trial would leak mock narratives into production
    # exports). Explicit --set-current / --no-set-current always wins.
    set_current = (
        args.set_current if args.set_current is not None else args.provider == "template"
    )
    if set_current:
        os.makedirs(os.path.join(args.cif_dir, "narratives"), exist_ok=True)
        with open(os.path.join(args.cif_dir, "narratives", "current_version.txt"), "w") as f:
            f.write(version_id)
        print(f"narrate: current -> {version_id}")
    print(
        f"narrate: wrote {manifest.document_count} narrative documents across "
        f"{manifest.encounter_count} encounters → narratives/{version_id}/"
    )


def _run_check_narratives(args: Any) -> None:
    """β-JP-1 chain 1b T2: semantic check CLI over one narrative version.

    Expectations resolution: explicit ``--expectations PATH`` wins; else
    ``--profile <name>`` resolves ``<fixtures>/<name>.llm-expectations.yaml``
    (CLINOSIM_PATIENT_PROFILE_DIR env override respected, mirroring
    regenerate-goldens); neither → builtin axes only. Exit code: 0 = pass,
    1 = findings, 2 = bad inputs (missing/invalid expectations file).
    """
    import json
    from pathlib import Path

    from clinosim.modules.document.narrative.semantic_check import (
        check_narratives,
        load_expectations,
    )
    from clinosim.types.config import _PATIENT_PROFILE_DIR

    expectations = None
    expectations_path: Path | None = None
    if args.expectations:
        expectations_path = Path(args.expectations)
    elif args.profile:
        fixture_dir_env = os.environ.get("CLINOSIM_PATIENT_PROFILE_DIR")
        fixture_dir = Path(fixture_dir_env) if fixture_dir_env else _PATIENT_PROFILE_DIR
        expectations_path = fixture_dir / f"{args.profile}.llm-expectations.yaml"

    if expectations_path is not None:
        try:
            expectations = load_expectations(expectations_path)
        except FileNotFoundError:
            print(f"ERROR: expectations file not found: {expectations_path}", file=sys.stderr)
            sys.exit(2)
        except ValueError as e:
            print(f"ERROR: invalid expectations file: {e}", file=sys.stderr)
            sys.exit(2)

    report = check_narratives(args.cif_dir, args.version, expectations)

    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
        print(f"check-narratives: report written to {args.report}")

    print(
        f"check-narratives: version={args.version} documents={report.document_count} "
        f"findings={len(report.findings)} generator={report.info.get('generator', '?')}"
    )
    for finding in report.findings:
        loc = finding.document_id or "-"
        if finding.section:
            loc += f"/{finding.section}"
        print(f"  [{finding.axis}] {loc}: {finding.message}")

    if not report.passed:
        print("check-narratives: FAIL", file=sys.stderr)
        sys.exit(1)
    print("check-narratives: PASS")


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
    files = sorted(
        f for f in os.listdir(output_dir) if f.endswith(".ndjson") or f == "manifest.json"
    )
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


if __name__ == "__main__":
    main()
