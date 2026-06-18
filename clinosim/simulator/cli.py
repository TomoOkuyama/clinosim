"""CLI entry point for clinosim."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import numpy as np

from clinosim.modules.patient.activator import activate_patient
from clinosim.modules.staff.engine import generate_roster
from clinosim.types.config import ForcedScenario, SimulatorConfig
from clinosim.types.encounter import EncounterType
from clinosim.types.output import CIFDataset, CIFPatientRecord

from clinosim.simulator.emergency import _simulate_ed_visit
from clinosim.simulator.engine import run_beta, run_forced
from clinosim.simulator.helpers import _load_all_disease_protocols


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
    gen.add_argument("-p", "--population", type=int, default=10_000, help="Catchment population (default: from hospital config)")
    gen.add_argument("-s", "--seed", type=int, default=42, help="Random seed")
    gen.add_argument("--country", default="US", help="Country code (US or JP)")
    gen.add_argument("--start", default=None, help="Simulation start date YYYY-MM-DD (default: 1 year before --end)")
    gen.add_argument("--end", default=None, help="Simulation end date / snapshot date YYYY-MM-DD (default: today). Inpatients still admitted on this date have no discharge.")
    gen.add_argument("--format", nargs="+", default=["cif"], help="Output formats: cif, csv, fhir-r4 (alias: fhir). Add more by registering an OutputAdapter (AD-58).")
    gen.add_argument("--narrative", action="store_true", help="Generate narrative layer (requires Ollama)")
    gen.add_argument("--narrative-model", default="qwen:7b", help="Ollama model for narratives")
    gen.add_argument("--hospital-config", default=None, help="Hospital operations YAML (default: config/hospital_operations.yaml)")
    gen.add_argument(
        "--jp-insurance",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="(JP only) Include Japanese insurance enrollment / 被保険者番号 "
             "(emitted as FHIR Coverage). Use --no-jp-insurance to omit. "
             "Ignored for non-JP countries.",
    )
    gen.add_argument(
        "--narrative-version",
        default=None,
        help="Narrative version directory name to include in FHIR export "
             "as DocumentReference (used only when --format includes fhir)",
    )
    gen.add_argument(
        "--llm-config",
        default=None,
        help="LLM service YAML config (used when --narrative is set). "
             "Defaults to a local Ollama template setup.",
    )

    # === test-disease: generate specific disease/archetype ===
    td = sub.add_parser("test-disease", help="Generate data for a specific disease and archetype")
    td.add_argument("disease_id", help="Disease ID (e.g., bacterial_pneumonia)")
    td.add_argument("-o", "--output", default="./output", help="Output directory")
    td.add_argument("-n", "--count", type=int, default=3, help="Number of patients")
    td.add_argument("--severity", default=None, help="Force severity: mild/moderate/severe")
    td.add_argument("--archetype", default=None, help="Force archetype name")
    td.add_argument("-s", "--seed", type=int, default=42, help="Random seed")
    td.add_argument("--country", default="US", help="Country code (US or JP)")
    td.add_argument("--format", nargs="+", default=["cif", "csv"], help="Output formats")

    # === validate: run quality checks on generated data ===
    val = sub.add_parser("validate", help="Run data quality checks on generated data")
    val.add_argument("-p", "--population", type=int, default=5_000, help="Population size")
    val.add_argument("-s", "--seed", type=int, default=42, help="Random seed")
    val.add_argument("--country", default="US", help="Country code")

    # === list-diseases: show available disease protocols ===
    sub.add_parser("list-diseases", help="List all available disease protocols")

    # === narrate: Stage 2 — generate clinical documents from CIF ===
    nr = sub.add_parser(
        "narrate",
        help="Generate clinical documents (discharge/death/op/H&P/procedure notes) from an existing CIF directory",
    )
    nr.add_argument("--cif-dir", required=True, help="Path to an existing CIF directory (contains structural/)")
    nr.add_argument("--llm-config", default=None, help="LLM service YAML config (default: template mode)")
    nr.add_argument("--version-id", default=None, help="Narrative version directory name (default: auto-generated)")
    nr.add_argument("--language", default="en", help="Document language (en|ja)")
    nr.add_argument(
        "--tasks",
        default=None,
        help="Comma-separated list of LLMTaskType values to generate "
             "(default: all Tier A+B types)",
    )

    # === export-fhir: Stage 3 — convert CIF (+narrative) to FHIR NDJSON ===
    ef = sub.add_parser(
        "export-fhir",
        help="Convert an existing CIF directory (with optional narrative version) to FHIR R4 Bulk Data NDJSON",
    )
    ef.add_argument("--cif-dir", required=True, help="Path to an existing CIF directory")
    ef.add_argument("-o", "--output", default=None, help="Output directory (default: <cif-dir>/../fhir_r4)")
    ef.add_argument("--country", default="US", help="Country code (US or JP)")
    ef.add_argument(
        "--narrative-version",
        default=None,
        help="Narrative version to include as DocumentReference. Use 'current' "
             "to read the pointer at <cif-dir>/narratives/current_version.txt.",
    )

    # === test-encounter: debug single encounter condition ===
    te = sub.add_parser("test-encounter", help="Simulate one patient for an encounter condition (debug)")
    te.add_argument("condition_id", help="Condition ID (e.g., chest_pain_noncardiac, flu_vaccination)")
    te.add_argument("-n", "--count", type=int, default=1, help="Number of patients")
    te.add_argument("-s", "--seed", type=int, default=42, help="Random seed")
    te.add_argument("--country", default="US", help="Country code")
    te.add_argument("--age", type=int, default=None, help="Force patient age")
    te.add_argument("--sex", default=None, help="Force patient sex (M/F)")

    args = parser.parse_args()

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
        _run_test_encounter(args)
        return

    if args.command == "narrate":
        _run_narrate(args)
        return

    if args.command == "export-fhir":
        _run_export_fhir(args)
        return

    if args.command == "validate":
        config = SimulatorConfig(
            catchment_population=args.population,
            random_seed=args.seed, country=args.country,
        )
        print(f"clinosim validate: pop={args.population}, country={args.country}")
        dataset = run_beta(config)
        _run_quality_checks(dataset)
        return

    if args.command == "generate":
        from datetime import date, timedelta as _td
        # Default end = today, default start = end - 1 year
        end_date = (datetime.strptime(args.end, "%Y-%m-%d").date()
                    if args.end else date.today())
        start_date = (datetime.strptime(args.start, "%Y-%m-%d").date()
                      if args.start else end_date - _td(days=365))
        end = end_date.strftime("%Y-%m-%d")
        start = start_date.strftime("%Y-%m-%d")
        config = SimulatorConfig(
            catchment_population=args.population,
            time_range=(start, end),
            random_seed=args.seed,
            country=args.country,
            snapshot_date=end,
            jp_insurance_numbers=args.jp_insurance,
        )
        hospital_cfg = getattr(args, "hospital_config", None)
        print(f"clinosim generate: population={args.population}, seed={args.seed}, country={args.country}, period={start}~{end}")
        if args.country == "JP":
            status = "on" if args.jp_insurance else "off"
            print(f"  JP insurance numbers (被保険者番号): {status}")
        if hospital_cfg:
            print(f"  Hospital config: {hospital_cfg}")
        dataset = run_beta(config, hospital_config_path=hospital_cfg)

    elif args.command == "test-disease":
        scenario = ForcedScenario(
            disease_id=args.disease_id,
            count=args.count,
            severity=args.severity,
            archetype=args.archetype,
        )
        config = SimulatorConfig(random_seed=args.seed, country=args.country)
        print(f"clinosim test-disease: {args.disease_id} x{args.count}, country={args.country}")
        dataset = run_forced(scenario, config)

        # Debug output for each patient
        for i, record in enumerate(dataset.patients):
            _print_debug_record(record, i + 1)

    else:
        parser.print_help()
        return

    # Output
    from clinosim.modules.output.cif_writer import write_cif
    cif_dir = os.path.join(args.output, "cif")
    write_cif(dataset, cif_dir)

    # Narrative layer (Stage 2, optional) — runs BEFORE FHIR export so that
    # DocumentReference can reference the freshly generated version.
    narrative_version = getattr(args, "narrative_version", None)
    if getattr(args, "narrative", False):
        from clinosim.modules.llm_service.engine import LLMService
        from clinosim.modules.llm_service.factory import build_from_config_file
        from clinosim.modules.output.document_generator import generate_documents

        lang = "ja" if getattr(args, "country", "US") == "JP" else "en"
        llm_config = getattr(args, "llm_config", None)
        if llm_config:
            llm = build_from_config_file(llm_config)
            print(f"  Using LLM config: {llm_config}")
        else:
            from clinosim.modules.llm_service.providers.ollama import OllamaProvider
            model = getattr(args, "narrative_model", "qwen:7b")
            print(f"  Generating narratives with local Ollama model={model}")
            llm = LLMService(
                mode="llm",
                narrative_provider=OllamaProvider({"model": model}),
                narrative_model_map={"small": model, "medium": model},
                provider_name_narrative="ollama",
            )
        narrative_version = generate_documents(
            cif_dir, llm, version_id=narrative_version, language=lang
        )
        print(f"  Narrative version: {narrative_version}")
        print(f"  LLM cost report: {llm.cost_report()}")

    # Format exports via the adapter registry (AD-58). Add a format = register an adapter.
    _run_exports(
        args.format,
        cif_dir,
        args.output,
        getattr(args, "country", "US"),
        narrative_version or "",
    )

    # Summary
    _print_summary(dataset, args.output)


# Back-compat alias: legacy "--format fhir" means FHIR R4.
_FORMAT_ALIASES = {"fhir": "fhir-r4"}


def _run_exports(
    formats: list[str],
    cif_dir: str,
    output_root: str,
    country: str,
    narrative_version: str,
) -> None:
    """Run each requested export format through the adapter registry (AD-58).

    CIF is assumed already written. "cif" is a no-op (CIF-only). Unknown formats raise
    ValueError. Output goes to <output_root>/<adapter.subdir>.
    """
    from clinosim.modules.output.adapter import OutputContext, get_adapter

    ctx = OutputContext(country=country, narrative_version=narrative_version or "")
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
    inpatients = [r for r in all_records if r.encounters and r.encounters[0].encounter_type.value == "inpatient"]
    outpatients = [r for r in all_records if r.encounters and r.encounters[0].encounter_type.value == "outpatient"]
    readmits = [r for r in inpatients if r.is_readmission]
    deceased = [r for r in all_records if r.deceased]

    print(f"\n{'='*50}")
    print(f"  clinosim generation complete")
    print(f"{'='*50}")
    print(f"  Total records:  {len(all_records)}")
    print(f"    Inpatient:    {len(inpatients)} ({len(readmits)} readmissions)")
    print(f"    Outpatient:   {len(outpatients)}")
    print(f"    Deceased:     {len(deceased)}")
    print(f"  Data volume:")
    print(f"    Lab results:  {sum(len(r.lab_results) for r in all_records):,}")
    print(f"    Vital signs:  {sum(len(r.vital_signs) for r in all_records):,}")
    print(f"    MAR entries:  {sum(len(r.medication_administrations) for r in all_records):,}")
    print(f"    I/O records:  {sum(len(r.intake_output_records) for r in all_records):,}")
    print(f"    Orders:       {sum(len(r.orders) for r in all_records):,}")

    # Disease distribution (inpatient only)
    by_disease = Counter()
    los_by_disease = defaultdict(list)
    for r in inpatients:
        d = r.condition_event.ground_truth_diseases[0] if r.condition_event.ground_truth_diseases else "?"
        by_disease[d] += 1
        los_by_disease[d].append(len(r.physiological_states) - 1)

    if by_disease:
        print(f"\n  Disease distribution (inpatient):")
        for d, n in by_disease.most_common(10):
            avg_los = sum(los_by_disease[d]) / len(los_by_disease[d])
            print(f"    {d:30s} {n:4d}  (LOS avg {avg_los:.1f}d)")

    print(f"\n  Output: {output_dir}/")


def _run_quality_checks(dataset: CIFDataset) -> None:
    """Run comprehensive quality checks on generated data."""
    from collections import Counter

    records = dataset.patients
    inpatients = [r for r in records if r.encounters and r.encounters[0].encounter_type == EncounterType.INPATIENT]
    outpatients = [r for r in records if r.encounters and r.encounters[0].encounter_type == EncounterType.OUTPATIENT]
    ed_visits = [r for r in records if r.encounters and r.encounters[0].encounter_type == EncounterType.EMERGENCY]

    print(f"\n{'='*50}")
    print("  Data Quality Report")
    print(f"{'='*50}")
    print(f"  Records: {len(records)} (inp={len(inpatients)}, opd={len(outpatients)}, ed={len(ed_visits)})")

    issues = 0

    # Check: labs have units
    no_unit = sum(1 for r in records for l in r.lab_results if not l.unit)
    if no_unit:
        print(f"  ❌ Labs missing units: {no_unit}")
        issues += 1
    else:
        print(f"  ✅ All labs have units")

    # Check: all records have diagnosis
    no_dx = sum(1 for r in records if not r.clinical_diagnosis.discharge_diagnosis_code)
    if no_dx:
        print(f"  ❌ Records missing diagnosis: {no_dx}")
        issues += 1
    else:
        print(f"  ✅ All records have diagnosis codes")

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
    print(f"  {'❌' if inp_no_ward else '✅'} Ward/bed assignment: {len(inpatients)-inp_no_ward}/{len(inpatients)}")
    if inp_no_ward: issues += 1

    # Check: pain scores
    vitals_with_pain = sum(1 for r in records for v in r.vital_signs if v.pain_score is not None)
    total_vitals = sum(len(r.vital_signs) for r in records)
    pct = vitals_with_pain / total_vitals * 100 if total_vitals else 0
    print(f"  ✅ Pain scores: {pct:.0f}% of vitals")

    # Check: ADL for inpatients
    adl_count = sum(len(r.adl_assessments) for r in inpatients)
    print(f"  ✅ ADL assessments: {adl_count} (avg {adl_count/len(inpatients):.1f}/patient)" if inpatients else "  - No inpatients")

    # Check: I/O for inpatients
    io_count = sum(len(r.intake_output_records) for r in inpatients)
    print(f"  ✅ I/O records: {io_count}")

    # Check: diet orders
    diet_count = sum(1 for r in inpatients if any(o.order_type.value == "diet" for o in r.orders))
    print(f"  ✅ Diet orders: {diet_count}/{len(inpatients)} inpatients")

    # Disease distribution
    by_disease = Counter()
    for r in inpatients:
        d = r.condition_event.ground_truth_diseases[0] if r.condition_event.ground_truth_diseases else "?"
        by_disease[d] += 1
    print(f"\n  Disease distribution ({len(by_disease)} types):")
    for d, n in by_disease.most_common(5):
        print(f"    {d:30s} {n:4d}")
    if len(by_disease) > 5:
        print(f"    ... and {len(by_disease)-5} more")

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
    """Debug CLI: simulate patients for a specific encounter condition."""
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
    print(f"\n{'='*60}")
    print(f"  test-encounter: {args.condition_id}")
    print(f"  Type: {enc_type} | Dept: {protocol.get('department', '?')}")
    print(f"  Chief: {protocol.get('chief_complaint', '?')}")
    print(f"{'='*60}")

    from clinosim.locale.loader import load_demographics as _ld
    _demo = _ld(args.country)
    for i in range(args.count):
        # Create patient
        age = args.age or int(rng.integers(30, 85))
        sex = args.sex or str(rng.choice(["M", "F"]))
        person = PersonRecord(
            person_id=f"TEST-{i+1:04d}",
            household_id=f"HH-TEST-{i+1:04d}",
            age=age, sex=sex,
            date_of_birth=__import__("datetime").date(2024 - age, 1, 1),
        )
        patient = activate_patient(person, rng, _demo)

        visit_time = datetime(2024, 6, 15, int(rng.integers(8, 20)), int(rng.integers(0, 60)))
        record = _simulate_ed_visit(patient, protocol, visit_time, roster, rng, country=args.country)

        _print_debug_record(record, i + 1)


def _print_debug_record(record: CIFPatientRecord, index: int = 1) -> None:
    """Print detailed debug output for a single patient record."""
    r = record
    enc = r.encounters[0] if r.encounters else None
    los = len(r.physiological_states) - 1 if r.physiological_states else 0

    print(f"\n--- Patient {index}: {r.patient.patient_id} ---")
    print(f"  {r.patient.age}yo {r.patient.sex} | Chronic: {[c.code for c in r.patient.chronic_conditions]}")
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
        print(f"    T={v.temperature_celsius}C HR={v.heart_rate} BP={v.systolic_bp}/{v.diastolic_bp} "
              f"RR={v.respiratory_rate} SpO2={v.spo2} Pain={v.pain_score}")
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
        print(f"\n  ADL: {len(r.adl_assessments)} assessments, "
              f"Barthel {r.adl_assessments[0].barthel_score}→{r.adl_assessments[-1].barthel_score}")

    # I/O
    if r.intake_output_records:
        io = r.intake_output_records[0]
        print(f"\n  I/O (Day 1): IV={io.intake_iv_ml}ml Oral={io.intake_oral_ml}ml "
              f"Urine={io.output_urine_ml}ml Net={io.net_balance_ml:+d}ml")

    print()


def _run_narrate(args: Any) -> None:
    """Stage 2 handler: read an existing CIF and generate clinical documents."""
    from clinosim.modules.llm_service.engine import LLMService
    from clinosim.modules.llm_service.factory import build_from_config_file
    from clinosim.modules.output.document_generator import generate_documents

    cif_dir = args.cif_dir
    if not os.path.isdir(os.path.join(cif_dir, "structural", "patients")):
        print(f"❌ CIF directory not valid: {cif_dir} (missing structural/patients/)")
        return

    # Build LLMService
    if args.llm_config:
        print(f"clinosim narrate: loading LLM config {args.llm_config}")
        llm = build_from_config_file(args.llm_config)
    else:
        print("clinosim narrate: no --llm-config provided, using template mode")
        llm = LLMService(mode="template")

    tasks = None
    if args.tasks:
        tasks = [t.strip() for t in args.tasks.split(",") if t.strip()]

    print(f"  CIF directory: {cif_dir}")
    print(f"  Language:      {args.language}")
    print(f"  Mode:          {llm.mode}")
    print(f"  Tasks:         {tasks or 'all Tier A+B'}")

    version_id = generate_documents(
        cif_dir,
        llm,
        version_id=args.version_id,
        language=args.language,
        tasks=tasks,
    )

    import json as _json
    manifest_path = os.path.join(cif_dir, "narratives", version_id, "manifest.json")
    if os.path.exists(manifest_path):
        with open(manifest_path) as f:
            manifest = _json.load(f)
        print("\n  === Narrative Generation Summary ===")
        print(f"  Version ID:       {version_id}")
        print(f"  Patients:         {manifest.get('patient_count', 0)}")
        print(f"  Total documents:  {manifest.get('total_documents', 0)}")
        counts = manifest.get("document_counts_by_type", {})
        for tname, n in sorted(counts.items()):
            print(f"    {tname:20s} {n}")
        cost = manifest.get("llm_cost_report", {})
        if cost:
            print(f"  LLM calls:        {cost.get('total_calls', 0)}")
            print(f"  LLM input tokens: {cost.get('total_input_tokens', 0):,}")
            print(f"  LLM output tokens:{cost.get('total_output_tokens', 0):,}")
            print(f"  Fallbacks:        {cost.get('fallback_count', 0)}")
            print(f"  Cache hits:       {cost.get('cache_hit_count', 0)}")


def _run_export_fhir(args: Any) -> None:
    """Stage 3 handler: convert an existing CIF (+narrative) into FHIR NDJSON."""
    from clinosim.modules.output.fhir_r4_adapter import convert_cif_to_fhir

    cif_dir = args.cif_dir
    if not os.path.isdir(os.path.join(cif_dir, "structural", "patients")):
        print(f"❌ CIF directory not valid: {cif_dir} (missing structural/patients/)")
        return

    if args.output:
        output_dir = args.output
    else:
        parent = os.path.dirname(os.path.abspath(cif_dir))
        output_dir = os.path.join(parent, "fhir_r4")

    print(f"clinosim export-fhir:")
    print(f"  CIF directory:      {cif_dir}")
    print(f"  Output:             {output_dir}")
    print(f"  Country:            {args.country}")
    print(f"  Narrative version:  {args.narrative_version or '(none)'}")

    convert_cif_to_fhir(
        cif_dir,
        output_dir,
        country=args.country,
        narrative_version=args.narrative_version,
    )

    # Summarize output
    files = sorted(
        f for f in os.listdir(output_dir)
        if f.endswith(".ndjson") or f == "manifest.json"
    )
    print(f"\n  === FHIR Export Summary ===")
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
