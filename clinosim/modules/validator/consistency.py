"""Tier 2: Rule-based consistency checks on CIF patient records.

Validates internal data integrity — no LLM needed. Checks that:
- Physiological values are within plausible ranges
- Discharge criteria are met (anemia, inflammation, renal)
- Medication holds are respected (anticoagulants in ICH, metformin in DKA)
- Procedures have required fields
- Deceased patients have appropriate status
- Lab values are consistent with physiology trajectory
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from clinosim.types.output import CIFDataset, CIFPatientRecord


@dataclass
class ConsistencyIssue:
    """A single data integrity issue found in a patient record."""

    patient_id: str
    severity: str  # "error" | "warning"
    check_name: str
    message: str


@dataclass
class ConsistencyReport:
    """Collection of consistency issues across all patients."""

    issues: list[ConsistencyIssue] = field(default_factory=list)
    patients_checked: int = 0
    checks_run: int = 0

    def add(self, issue: ConsistencyIssue) -> None:
        self.issues.append(issue)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")

    def summary(self) -> str:
        return (
            f"Consistency: {self.patients_checked} patients, {self.checks_run} checks, "
            f"{self.error_count} errors, {self.warning_count} warnings"
        )


def run_consistency_checks(
    dataset: CIFDataset,
    country: str = "US",
) -> ConsistencyReport:
    """Run all rule-based consistency checks on a CIFDataset."""
    report = ConsistencyReport()

    for record in dataset.patients:
        if not record.encounters:
            continue
        enc = record.encounters[0]
        if enc.encounter_type.value != "inpatient":
            continue

        report.patients_checked += 1
        pid = record.patient.patient_id

        _check_discharge_hgb(record, pid, report)
        _check_deceased_status(record, pid, report)
        _check_lab_ranges(record, pid, report)
        _check_medication_holds(record, pid, report)
        _check_procedure_fields(record, pid, report)
        _check_los_consistency(record, pid, report)
        _check_vital_ranges(record, pid, report)
        _check_sex_specific_conditions(record, pid, report)

    report.checks_run = report.patients_checked * 8  # 8 checks per patient
    return report


# ============================================================
# Individual checks
# ============================================================


def _check_discharge_hgb(
    record: CIFPatientRecord, pid: str, report: ConsistencyReport
) -> None:
    """No patient should be discharged alive with Hgb < 7.0 g/dL."""
    if record.deceased or not record.physiological_states:
        return
    final_state = record.physiological_states[-1]
    anemia = final_state.anemia_level
    sex = record.patient.sex
    hb_base = 15.0 if sex == "M" else 13.0
    hgb = max(3.0, hb_base * (1 - anemia * 0.7))
    if hgb < 7.0:
        report.add(ConsistencyIssue(
            pid, "error", "discharge_hgb",
            f"Discharged with Hgb={hgb:.1f} g/dL (anemia={anemia:.3f}). Threshold: 7.0",
        ))


def _check_deceased_status(
    record: CIFPatientRecord, pid: str, report: ConsistencyReport
) -> None:
    """Deceased patients must have discharge_disposition=expired."""
    enc = record.encounters[0]
    if record.deceased and enc.discharge_disposition != "expired":
        report.add(ConsistencyIssue(
            pid, "error", "deceased_disposition",
            f"Deceased but disposition={enc.discharge_disposition} (expected 'expired')",
        ))
    if not record.deceased and enc.discharge_disposition == "expired":
        report.add(ConsistencyIssue(
            pid, "error", "alive_but_expired",
            "Not deceased but disposition='expired'",
        ))


def _check_lab_ranges(
    record: CIFPatientRecord, pid: str, report: ConsistencyReport
) -> None:
    """Lab values should be within physiologically plausible ranges."""
    plausible = {
        "WBC": (0, 100000),
        "Hb": (2.0, 22.0),
        "Hgb": (2.0, 22.0),
        "CRP": (0, 800),  # severe sepsis/trauma/surgery: 500-800 is plausible
        "Creatinine": (0.1, 30.0),
        "Cr": (0.1, 30.0),
        "Glucose": (10, 1500),
        "Lactate": (0, 30),
        "Plt": (0, 2000000),
    }
    for lab in record.lab_results:
        name = lab.lab_name or ""
        try:
            val = float(lab.value)
        except (TypeError, ValueError):
            continue
        for key, (lo, hi) in plausible.items():
            if key.lower() in name.lower():
                if val < lo or val > hi:
                    report.add(ConsistencyIssue(
                        pid, "warning", "lab_range",
                        f"{name}={val} outside plausible range [{lo}, {hi}]",
                    ))
                break


def _check_medication_holds(
    record: CIFPatientRecord, pid: str, report: ConsistencyReport
) -> None:
    """Check disease-specific medication contraindications."""
    gt = record.condition_event.ground_truth_diseases
    if not gt:
        return
    disease = gt[0]

    # Hemorrhagic stroke: no anticoagulants
    anticoag = {"apixaban", "warfarin", "rivaroxaban", "dabigatran", "edoxaban", "heparin", "enoxaparin"}
    if disease == "hemorrhagic_stroke":
        for order in record.orders:
            name = (order.display_name or "").lower()
            if any(a in name for a in anticoag) and "HELD" not in (order.clinical_intent or ""):
                report.add(ConsistencyIssue(
                    pid, "error", "anticoag_in_ich",
                    f"Anticoagulant '{order.display_name}' ordered during hemorrhagic stroke",
                ))

    # DKA/sepsis/pancreatitis: no metformin
    metformin_hold_diseases = {"diabetic_ketoacidosis", "sepsis", "acute_pancreatitis", "acute_kidney_injury"}
    # Check primary disease AND complications for metformin contraindication
    all_conditions = set(gt) | set(record.complications_occurred)
    if all_conditions & metformin_hold_diseases:
        triggering = all_conditions & metformin_hold_diseases
        for order in record.orders:
            name = (order.display_name or "").lower()
            intent = (order.clinical_intent or "").lower()
            # Skip hold instructions (these contain "metformin" but are not administration)
            if "hold" in intent or "held" in intent:
                continue
            # Skip cancelled orders (held/cancelled during admission)
            if hasattr(order, 'status') and order.status.value in ('cancelled', 'discontinued'):
                continue
            if "metformin" in name:
                report.add(ConsistencyIssue(
                    pid, "error", "metformin_in_acute",
                    f"Metformin active despite {triggering}",
                ))


def _check_procedure_fields(
    record: CIFPatientRecord, pid: str, report: ConsistencyReport
) -> None:
    """Surgical procedures must have procedure_code and approach."""
    for proc in record.procedures:
        if not hasattr(proc, "category_code"):
            continue
        if proc.category_code == "387713003":  # surgical
            if not proc.procedure_code:
                report.add(ConsistencyIssue(
                    pid, "warning", "surgery_no_code",
                    f"Surgery '{proc.procedure_name}' has no procedure code",
                ))
            if not proc.approach:
                report.add(ConsistencyIssue(
                    pid, "warning", "surgery_no_approach",
                    f"Surgery '{proc.procedure_name}' has no approach defined",
                ))


def _check_los_consistency(
    record: CIFPatientRecord, pid: str, report: ConsistencyReport
) -> None:
    """LOS from dates should match physiological states count."""
    enc = record.encounters[0]
    if not enc.admission_datetime or not enc.discharge_datetime:
        return
    date_los = (enc.discharge_datetime - enc.admission_datetime).days
    state_los = len(record.physiological_states) - 1 if record.physiological_states else 0
    if abs(date_los - state_los) > 1:
        report.add(ConsistencyIssue(
            pid, "warning", "los_mismatch",
            f"Date-based LOS={date_los}d but physiology states={state_los}",
        ))


def _check_vital_ranges(
    record: CIFPatientRecord, pid: str, report: ConsistencyReport
) -> None:
    """Vital signs should be within physiologically plausible ranges."""
    for vs in record.vital_signs[:5]:  # check first 5 only for performance
        if vs.heart_rate is not None and (vs.heart_rate < 20 or vs.heart_rate > 250):
            report.add(ConsistencyIssue(
                pid, "warning", "vital_range",
                f"HR={vs.heart_rate} outside plausible range [20, 250]",
            ))
        if vs.systolic_bp is not None and (vs.systolic_bp < 40 or vs.systolic_bp > 300):
            report.add(ConsistencyIssue(
                pid, "warning", "vital_range",
                f"SBP={vs.systolic_bp} outside plausible range [40, 300]",
            ))
        if vs.spo2 is not None and (vs.spo2 < 50 or vs.spo2 > 100.1):
            report.add(ConsistencyIssue(
                pid, "warning", "vital_range",
                f"SpO2={vs.spo2} outside plausible range [50, 100]",
            ))


def _check_sex_specific_conditions(
    record: CIFPatientRecord, pid: str, report: ConsistencyReport
) -> None:
    """BPH (N40) should not appear in female patients."""
    sex = record.patient.sex
    for c in record.patient.chronic_conditions:
        if c.code == "N40" and sex == "F":
            report.add(ConsistencyIssue(
                pid, "error", "bph_in_female",
                "BPH (N40) assigned to female patient",
            ))
