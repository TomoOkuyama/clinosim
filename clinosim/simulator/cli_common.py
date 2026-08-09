"""Shared CLI helpers used by main + subcommand handlers.

Split from `clinosim/simulator/cli.py` — see PR K.
The subcommand handler modules (`cli_regenerate`, `cli_narrate`,
`cli_test_encounter`, `cli_test_disease`, `cli_enumerate`, `cli_export_fhir`)
import their shared print / export / debug helpers from here so they can be
imported by `cli.py::main()` without creating a cycle.
"""

from __future__ import annotations

import os
from typing import Any

from clinosim.types.encounter import EncounterType
from clinosim.types.output import CIFDataset, CIFPatientRecord

# Back-compat alias: legacy "--format fhir" means FHIR R4.
_FORMAT_ALIASES = {"fhir": "fhir-r4"}


# ---- _validate_formats (moved from cli.py) ----
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


# ---- _run_exports (moved from cli.py) ----
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


# ---- _print_summary (moved from cli.py) ----
def _print_summary(dataset: CIFDataset, output_dir: str) -> None:
    """Print a summary report of generated data."""
    from collections import Counter, defaultdict

    all_records = dataset.patients
    inpatients = [r for r in all_records if r.encounters and r.encounters[0].encounter_type.value == "inpatient"]
    outpatients = [r for r in all_records if r.encounters and r.encounters[0].encounter_type.value == "outpatient"]
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
    by_disease: Counter[str] = Counter()
    los_by_disease: dict[str, list[float]] = defaultdict(list)
    for r in inpatients:
        d = r.condition_event.ground_truth_diseases[0] if r.condition_event.ground_truth_diseases else "?"
        by_disease[d] += 1
        los_by_disease[d].append(len(r.physiological_states) - 1)

    if by_disease:
        print("\n  Disease distribution (inpatient):")
        for d, n in by_disease.most_common(10):
            avg_los = sum(los_by_disease[d]) / len(los_by_disease[d])
            print(f"    {d:30s} {n:4d}  (LOS avg {avg_los:.1f}d)")

    print(f"\n  Output: {output_dir}/")


# ---- _run_quality_checks (moved from cli.py) ----
def _run_quality_checks(dataset: CIFDataset) -> None:
    """Run comprehensive quality checks on generated data."""
    from collections import Counter

    records = dataset.patients
    inpatients = [r for r in records if r.encounters and r.encounters[0].encounter_type == EncounterType.INPATIENT]
    outpatients = [r for r in records if r.encounters and r.encounters[0].encounter_type == EncounterType.OUTPATIENT]
    ed_visits = [r for r in records if r.encounters and r.encounters[0].encounter_type == EncounterType.EMERGENCY]

    print(f"\n{'=' * 50}")
    print("  Data Quality Report")
    print(f"{'=' * 50}")
    print(f"  Records: {len(records)} (inp={len(inpatients)}, opd={len(outpatients)}, ed={len(ed_visits)})")

    issues = 0

    # Check: labs have units
    no_unit = sum(1 for r in records for lab in r.lab_results if not lab.unit)
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
    print(f"  {'❌' if inp_no_ward else '✅'} Ward/bed assignment: {len(inpatients) - inp_no_ward}/{len(inpatients)}")
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
    by_disease: Counter[str] = Counter()
    for r in inpatients:
        d = r.condition_event.ground_truth_diseases[0] if r.condition_event.ground_truth_diseases else "?"
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


# ---- _print_debug_record (moved from cli.py) ----
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
    order_types: dict[str, int] = {}
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
